from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from personal_alpha_terminal.core.data_timestamps import DataTimestamps
from personal_alpha_terminal.data.market_data_quality.schemas import (
    CalendarSession,
    CorporateActionRecord,
    CorporateActionType,
    HistoricalBar,
    HistoricalQualityIssue,
    InstrumentQualityMetrics,
    UniverseCandidate,
)


class HistoricalQualityAnalyzer:
    """Validate historical coverage against a verified exchange calendar."""

    def analyze(
        self,
        *,
        instrument: UniverseCandidate,
        bars: list[HistoricalBar],
        sessions: list[CalendarSession],
        corporate_actions: list[CorporateActionRecord],
        start_date: date,
        end_date: date,
    ) -> InstrumentQualityMetrics:
        if start_date > end_date:
            raise ValueError("start_date cannot be later than end_date.")

        effective_start = max(
            start_date,
            instrument.list_date or start_date,
        )
        effective_end = min(
            end_date,
            instrument.delist_date or end_date,
        )
        expected_dates = {
            item.session_date
            for item in sessions
            if item.is_open and effective_start <= item.session_date <= effective_end
        }
        issues: list[HistoricalQualityIssue] = []
        required_calendar_dates: set[date] = set()
        current_date = effective_start
        while current_date <= effective_end:
            required_calendar_dates.add(current_date)
            current_date += timedelta(days=1)
        covered_calendar_dates = {
            item.session_date
            for item in sessions
            if effective_start <= item.session_date <= effective_end
        }
        uncovered_calendar_dates = sorted(
            required_calendar_dates - covered_calendar_dates
        )
        if uncovered_calendar_dates:
            issues.append(
                HistoricalQualityIssue(
                    code="incomplete_calendar_coverage",
                    severity="error",
                    message=(
                        f"{len(uncovered_calendar_dates)} calendar dates lack an explicit "
                        "open/closed exchange-calendar record."
                    ),
                    trade_date=uncovered_calendar_dates[0],
                )
            )
        if not expected_dates:
            issues.append(
                HistoricalQualityIssue(
                    code="missing_verified_calendar",
                    severity="error",
                    message="No verified open sessions cover the instrument period.",
                )
            )

        counts = Counter(item.trade_date for item in bars)
        duplicate_dates = sorted(day for day, count in counts.items() if count > 1)
        if duplicate_dates:
            issues.append(
                HistoricalQualityIssue(
                    code="duplicate_history",
                    severity="error",
                    message=f"{len(duplicate_dates)} duplicate trading dates were found.",
                    trade_date=duplicate_dates[0],
                )
            )

        observed_dates = set(counts)
        off_calendar = sorted(observed_dates - expected_dates)
        if off_calendar:
            issues.append(
                HistoricalQualityIssue(
                    code="off_calendar_observation",
                    severity="error",
                    message=f"{len(off_calendar)} observations fall outside verified sessions.",
                    trade_date=off_calendar[0],
                )
            )

        missing = sorted(expected_dates - observed_dates)
        if missing:
            issues.append(
                HistoricalQualityIssue(
                    code="unclassified_missing_session",
                    severity="error",
                    message=(
                        f"{len(missing)} open sessions have no bar. A suspension/trading-status "
                        "record is required before treating these as legitimate gaps."
                    ),
                    trade_date=missing[0],
                )
            )

        actions_by_date: dict[date, list[CorporateActionRecord]] = {}
        for corporate_action in corporate_actions:
            actions_by_date.setdefault(corporate_action.effective_date, []).append(
                corporate_action
            )
        action_dates = set(actions_by_date)
        ordered = sorted(
            (item for item in bars if item.trade_date in expected_dates),
            key=lambda item: item.trade_date,
        )
        anomalous_dates: set[date] = set()
        for previous, current in zip(ordered, ordered[1:], strict=False):
            raw_return = current.close / previous.close - Decimal("1")
            if abs(raw_return) > Decimal("0.40"):
                actions = actions_by_date.get(current.trade_date, [])
                split_actions = [
                    action
                    for action in actions
                    if action.action_type
                    in {CorporateActionType.SPLIT, CorporateActionType.REVERSE_SPLIT}
                    and action.split_ratio is not None
                    and action.split_ratio > 0
                ]
                if not split_actions:
                    anomalous_dates.add(current.trade_date)
                    issues.append(
                        HistoricalQualityIssue(
                            code="unexplained_raw_price_jump",
                            severity="error",
                            message=(
                                f"Raw close changed {raw_return:.2%} without a matching "
                                "split ratio. A dividend label alone is insufficient."
                            ),
                            trade_date=current.trade_date,
                        )
                    )
                else:
                    observed_ratio = current.close / previous.close
                    ratio_errors = [
                        abs(observed_ratio - (Decimal("1") / action.split_ratio))
                        / (Decimal("1") / action.split_ratio)
                        for action in split_actions
                        if action.split_ratio is not None
                    ]
                    if not ratio_errors or min(ratio_errors) > Decimal("0.15"):
                        anomalous_dates.add(current.trade_date)
                        issues.append(
                            HistoricalQualityIssue(
                                code="split_ratio_mismatch",
                                severity="error",
                                message=(
                                    "Raw price jump is inconsistent with the recorded "
                                    "split ratio within a 15% tolerance."
                                ),
                                trade_date=current.trade_date,
                            )
                        )

            if previous.adjusted_close is not None and current.adjusted_close is not None:
                adjusted_return = current.adjusted_close / previous.adjusted_close - Decimal("1")
                if abs(adjusted_return) > Decimal("0.50"):
                    anomalous_dates.add(current.trade_date)
                    issues.append(
                        HistoricalQualityIssue(
                            code="extreme_adjusted_return",
                            severity="error",
                            message=(
                                f"Adjusted close changed {adjusted_return:.2%}; source and "
                                "corporate-action treatment require reconciliation."
                            ),
                            trade_date=current.trade_date,
                        )
                    )

                prior_factor = previous.adjusted_close / previous.close
                current_factor = current.adjusted_close / current.close
                factor_change = current_factor / prior_factor - Decimal("1")
                if abs(factor_change) > Decimal("0.20") and current.trade_date not in action_dates:
                    anomalous_dates.add(current.trade_date)
                    issues.append(
                        HistoricalQualityIssue(
                            code="unexplained_adjustment_change",
                            severity="error",
                            message=(
                                f"Adjustment factor changed {factor_change:.2%} without "
                                "matching point-in-time corporate-action provenance."
                            ),
                            trade_date=current.trade_date,
                        )
                    )

        if instrument.delist_date is not None:
            post_delist = sorted(
                item.trade_date for item in bars if item.trade_date > instrument.delist_date
            )
            if post_delist:
                issues.append(
                    HistoricalQualityIssue(
                        code="post_delisting_price",
                        severity="error",
                        message="Price observations exist after the stock-master delisting date.",
                        trade_date=post_delist[0],
                    )
                )

        source_values = {item.source for item in bars}
        provider_values = {item.provider for item in bars}
        missing_lineage_values = {"", "unknown", "legacy_unknown"}
        if (
            not bars
            or not source_values
            or bool(source_values & missing_lineage_values)
        ):
            issues.append(
                HistoricalQualityIssue(
                    code="missing_source_lineage",
                    severity="error",
                    message="Historical rows do not have complete source lineage.",
                )
            )
        if (
            not bars
            or not provider_values
            or bool(provider_values & missing_lineage_values)
        ):
            issues.append(
                HistoricalQualityIssue(
                    code="missing_provider_lineage",
                    severity="error",
                    message="Historical rows do not have complete provider lineage.",
                )
            )
        for price_bar in bars:
            if (
                price_bar.event_time is None
                or price_bar.available_time is None
                or price_bar.ingested_time is None
            ):
                issues.append(
                    HistoricalQualityIssue(
                        code="missing_price_timestamps",
                        severity="error",
                        message=(
                            "Price lineage requires event_time, available_time, and "
                            "ingested_time."
                        ),
                        trade_date=price_bar.trade_date,
                    )
                )
                continue
            try:
                DataTimestamps(
                    event_time=price_bar.event_time,
                    available_time=price_bar.available_time,
                    ingested_time=price_bar.ingested_time,
                )
            except ValueError as error:
                issues.append(
                    HistoricalQualityIssue(
                        code="invalid_price_timestamps",
                        severity="error",
                        message=str(error),
                        trade_date=price_bar.trade_date,
                    )
                )

        expected_count = len(expected_dates)
        observed_count = len(observed_dates & expected_dates)
        return InstrumentQualityMetrics(
            stock_id=instrument.stock_id,
            symbol=instrument.symbol,
            market=instrument.market,
            segment=instrument.segment,
            expected_sessions=expected_count,
            observed_sessions=observed_count,
            missing_sessions=len(missing),
            missing_rate=(len(missing) / expected_count if expected_count else 1.0),
            anomalous_observations=len(anomalous_dates),
            anomaly_rate=(len(anomalous_dates) / observed_count if observed_count else 1.0),
            first_date=min(observed_dates) if observed_dates else None,
            last_date=max(observed_dates) if observed_dates else None,
            issues=tuple(issues),
        )
