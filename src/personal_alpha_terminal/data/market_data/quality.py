from datetime import date
from decimal import Decimal, InvalidOperation

from personal_alpha_terminal.core.data_timestamps import DataTimestamps
from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc
from personal_alpha_terminal.data.market_data.contracts import AssetType, VolumeUnit
from personal_alpha_terminal.data.market_data.schemas import (
    DataQualityResult,
    Market,
    PriceBar,
    QualityIssue,
    QualitySeverity,
)


class DataQualityChecker:
    """Validate, reject structurally unsafe bars, and remove duplicates."""

    def validate(
        self,
        bars: list[PriceBar],
        *,
        expected_symbol: str,
        expected_market: Market,
        expected_asset_type: AssetType = "stock",
        expected_price_currency: str | None = None,
        expected_volume_unit: VolumeUnit = "share",
        start_date: date,
        end_date: date,
        require_volume: bool = True,
    ) -> DataQualityResult:
        accepted: dict[tuple[str, Market, date], PriceBar] = {}
        issues: list[QualityIssue] = []
        rejected_count = 0

        for bar in bars:
            bar_issues = self._validate_bar(
                bar,
                expected_symbol=expected_symbol,
                expected_market=expected_market,
                expected_asset_type=expected_asset_type,
                expected_price_currency=(
                    expected_price_currency
                    if expected_price_currency is not None
                    else {"A": "CNY", "HK": "HKD", "US": "USD"}[expected_market]
                ),
                expected_volume_unit=expected_volume_unit,
                start_date=start_date,
                end_date=end_date,
                require_volume=require_volume,
            )
            issues.extend(bar_issues)
            if any(issue.severity == QualitySeverity.ERROR for issue in bar_issues):
                rejected_count += 1
                continue

            key = (bar.symbol, bar.market, bar.date)
            if key in accepted:
                issues.append(
                    QualityIssue(
                        code="duplicate_bar",
                        message=(
                            "Duplicate daily bar received; the batch is unsafe "
                            "until the provider conflict is resolved."
                        ),
                        severity=QualitySeverity.ERROR,
                        date=bar.date,
                    )
                )
            accepted[key] = bar

        ordered = tuple(sorted(accepted.values(), key=lambda item: item.date))
        issues.extend(self._validate_series(ordered))
        return DataQualityResult(
            bars=ordered,
            issues=tuple(issues),
            input_count=len(bars),
            rejected_count=rejected_count,
        )

    def _validate_bar(
        self,
        bar: PriceBar,
        *,
        expected_symbol: str,
        expected_market: Market,
        expected_asset_type: AssetType,
        expected_price_currency: str,
        expected_volume_unit: VolumeUnit,
        start_date: date,
        end_date: date,
        require_volume: bool,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []

        if bar.symbol != expected_symbol or bar.market != expected_market:
            issues.append(
                self._error(
                    "instrument_mismatch",
                    "Provider row does not match the requested symbol and market.",
                    bar.date,
                )
            )
        if bar.asset_type != expected_asset_type:
            issues.append(
                self._error(
                    "asset_type_mismatch",
                    "Normalized row asset_type does not match the requested asset schema.",
                    bar.date,
                )
            )
        if bar.volume_unit != expected_volume_unit:
            issues.append(
                self._error(
                    "volume_unit_mismatch",
                    "Normalized row volume_unit violates the provider capability.",
                    bar.date,
                )
            )
        if bar.price_currency != expected_price_currency:
            issues.append(
                self._error(
                    "price_currency_mismatch",
                    "Normalized row currency does not match the stock master.",
                    bar.date,
                )
            )
        if bar.share_unit != Decimal("1"):
            issues.append(
                self._error(
                    "share_unit_mismatch",
                    "Research-layer rows require share_unit=1.",
                    bar.date,
                )
            )
        if not start_date <= bar.date <= end_date:
            issues.append(
                self._error(
                    "date_out_of_range",
                    "Daily bar falls outside the requested date range.",
                    bar.date,
                )
            )
        if bar.date.weekday() >= 5:
            issues.append(
                self._error(
                    "non_session_weekend",
                    "Daily bar falls on a weekend and cannot be a cash-market session.",
                    bar.date,
                )
            )
        try:
            timestamps = DataTimestamps(
                event_time=bar.event_time,
                available_time=bar.available_time,
                ingested_time=bar.ingested_time,
            )
            expected_event = market_close_utc(bar.date, bar.market)
            if timestamps.event_time != expected_event:
                issues.append(
                    self._error(
                        "event_time_mismatch",
                        "Daily bar event_time must equal the configured market close.",
                        bar.date,
                    )
                )
            if normalize_utc(bar.available_time) < expected_event:
                issues.append(
                    self._error(
                        "available_before_close",
                        "Daily bar cannot be available before its market close.",
                        bar.date,
                    )
                )
        except ValueError as error:
            issues.append(self._error("invalid_data_timestamps", str(error), bar.date))

        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(self._is_positive_finite(value) for value in prices):
            issues.append(
                self._error(
                    "invalid_price",
                    "OHLC values must be finite and greater than zero.",
                    bar.date,
                )
            )
            return issues
        if bar.adjusted_close is not None and not self._is_positive_finite(bar.adjusted_close):
            issues.append(
                self._error(
                    "invalid_adjusted_close",
                    "Adjusted close must be finite and greater than zero.",
                    bar.date,
                )
            )
        for mode, value in (
            ("forward", bar.forward_adjusted_close),
            ("backward", bar.backward_adjusted_close),
        ):
            if value is not None and not self._is_positive_finite(value):
                issues.append(
                    self._error(
                        f"invalid_{mode}_adjusted_close",
                        f"{mode.title()}-adjusted close must be finite and greater than zero.",
                        bar.date,
                    )
                )
        if (
            any(
                value is not None
                for value in (
                    bar.adjusted_close,
                    bar.forward_adjusted_close,
                    bar.backward_adjusted_close,
                )
            )
            and not bar.adjustment_method
        ):
            issues.append(
                self._error(
                    "missing_adjustment_lineage",
                    "Adjusted values require an explicit adjustment_method.",
                    bar.date,
                )
            )

        if bar.high < max(bar.open, bar.close, bar.low):
            issues.append(
                self._error(
                    "invalid_high",
                    "High price is below another OHLC value.",
                    bar.date,
                )
            )
        if bar.low > min(bar.open, bar.close, bar.high):
            issues.append(
                self._error(
                    "invalid_low",
                    "Low price is above another OHLC value.",
                    bar.date,
                )
            )
        if bar.volume is None:
            issues.append(
                QualityIssue(
                    code="missing_volume",
                    message="Volume is unavailable for this daily bar.",
                    severity=(QualitySeverity.ERROR if require_volume else QualitySeverity.WARNING),
                    date=bar.date,
                )
            )
        elif bar.volume < 0:
            issues.append(
                self._error(
                    "negative_volume",
                    "Volume cannot be negative.",
                    bar.date,
                )
            )
        if bar.open_tradable is None:
            issues.append(
                QualityIssue(
                    code="unknown_open_tradability",
                    message=(
                        "Daily OHLCV does not prove that an order could execute "
                        "at the opening auction."
                    ),
                    severity=QualitySeverity.WARNING,
                    date=bar.date,
                )
            )

        return issues

    def _validate_series(
        self,
        bars: tuple[PriceBar, ...],
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for previous, current in zip(bars, bars[1:], strict=False):
            gap_days = (current.date - previous.date).days
            if gap_days > 10:
                issues.append(
                    QualityIssue(
                        code="long_data_gap",
                        message=(
                            f"No observations for {gap_days - 1} calendar days; "
                            "verify suspension versus missing provider data."
                        ),
                        severity=QualitySeverity.ERROR,
                        date=current.date,
                    )
                )
            prior_price = previous.adjusted_close or previous.close
            current_price = current.adjusted_close or current.close
            adjusted_return = current_price / prior_price - 1
            if adjusted_return < Decimal("-0.50") or adjusted_return > Decimal("1.00"):
                issues.append(
                    self._error(
                        "extreme_adjusted_return",
                        (
                            f"Adjusted one-session return {adjusted_return:.2%} "
                            "requires corporate-action or source verification."
                        ),
                        current.date,
                    )
                )
            if previous.adjusted_close is not None and current.adjusted_close is not None:
                prior_factor = previous.adjusted_close / previous.close
                current_factor = current.adjusted_close / current.close
                factor_change = current_factor / prior_factor - 1
                if abs(factor_change) > Decimal("0.20"):
                    issues.append(
                        QualityIssue(
                            code="adjustment_factor_jump",
                            message=(
                                f"Adjustment factor changed {factor_change:.2%}; "
                                "verify split/dividend/rights-event provenance."
                            ),
                            severity=QualitySeverity.ERROR,
                            date=current.date,
                        )
                    )
        return issues

    @staticmethod
    def _is_positive_finite(value: Decimal) -> bool:
        try:
            return value.is_finite() and value > 0
        except (InvalidOperation, ValueError):
            return False

    @staticmethod
    def _error(code: str, message: str, bar_date: date) -> QualityIssue:
        return QualityIssue(
            code=code,
            message=message,
            severity=QualitySeverity.ERROR,
            date=bar_date,
        )
