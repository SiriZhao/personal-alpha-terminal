from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.universe import ResearchAsset
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
from personal_alpha_terminal.data.market_data.providers.stooq import (
    StooqETFAdapter,
    StooqStockAdapter,
)
from personal_alpha_terminal.models import CorporateAction, Price, Stock


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNING = "PASS_WITH_WARNING"
    FAIL_BLOCKING = "FAIL_BLOCKING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    event_type: str
    effective_date: date
    value: float
    announcement_at: datetime | None
    available_at: datetime
    source: str
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class CorporateActionSymbolEvidence:
    symbol: str
    status: EvidenceStatus
    events_found: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorporateActionCertificate:
    status: EvidenceStatus
    provider: str
    policy: str
    retrieved_at: datetime
    symbols_checked: tuple[str, ...]
    events_found: int
    adjustment_consistency: str
    pit_policy: str
    events: tuple[ActionEvidence, ...]
    symbol_results: tuple[CorporateActionSymbolEvidence, ...]
    validation_errors: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class ReconciliationSymbolEvidence:
    symbol: str
    status: EvidenceStatus
    secondary_provider: str
    primary_rows: int
    secondary_rows: int
    matched_rows: int
    coverage: float
    warning_divergences: int
    blocking_divergences: int
    reason: str


@dataclass(frozen=True, slots=True)
class ProviderReconciliationCertificate:
    status: EvidenceStatus
    primary_provider: str
    secondary_providers: tuple[str, ...]
    minimum_coverage: float
    warning_return_tolerance: float
    blocking_return_tolerance: float
    symbol_results: tuple[ReconciliationSymbolEvidence, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class BarCoverageEvidence:
    symbol: str
    required: bool
    expected: int
    matched: int
    missing: int
    unexpected: int
    duplicate: int
    rejected: int
    valid: int
    latest: date | None
    missing_dates: tuple[date, ...] = ()
    unexpected_dates: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class LineageEvidenceBundle:
    corporate_actions: CorporateActionCertificate
    reconciliation: ProviderReconciliationCertificate
    coverage: tuple[BarCoverageEvidence, ...]
    data_cutoff: datetime | None
    latest_completed_session: date
    decision_timestamp_convention: str

    def document(self) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(asdict(self)))


ActionFetcher = Callable[[ResearchAsset, date, date, datetime], Sequence[ActionEvidence]]
SecondaryFetcher = Callable[[ResearchAsset, date, date], Mapping[date, float]]


class DataLineageCertifier:
    """Create evidence for actions, independent prices and exact calendar coverage.

    It does not downgrade failures.  A primary download and a fallback label are not
    independent reconciliation; a required symbol is certified only when both evidence
    chains are actually available and pass.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        action_fetcher: ActionFetcher | None = None,
        secondary_fetcher: SecondaryFetcher | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.action_fetcher = action_fetcher or self._fetch_yahoo_actions
        self.secondary_fetcher = secondary_fetcher or self._fetch_secondary

    def certify(
        self,
        *,
        assets: Sequence[ResearchAsset],
        start_date: date,
        analysis_date: date,
        decision_time: datetime,
    ) -> LineageEvidenceBundle:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        primary = self._primary_prices(assets, start_date, analysis_date, decision_time)
        action_certificate = self._certify_actions(
            assets, start_date, analysis_date, decision_time
        )
        reconciliation, secondary_dates = self._reconcile(
            assets, primary, start_date, analysis_date
        )
        coverage = self._coverage(
            assets, primary, secondary_dates, start_date, analysis_date
        )
        timestamps = [
            normalize_utc(item.available_time)
            for rows in primary.values()
            for item in rows
            if item.available_time is not None
            and normalize_utc(item.available_time) <= normalize_utc(decision_time)
        ]
        cutoff = max(timestamps, default=None)
        if cutoff is not None and cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        return LineageEvidenceBundle(
            action_certificate,
            reconciliation,
            coverage,
            cutoff,
            analysis_date,
            (
                "daily close inputs available after provider publication; "
                "next-session manual execution"
            ),
        )

    def _primary_prices(
        self,
        assets: Sequence[ResearchAsset],
        start_date: date,
        end_date: date,
        decision_time: datetime,
    ) -> dict[str, tuple[Price, ...]]:
        symbols = [item.ticker for item in assets]
        stocks = {
            item.id: item.symbol
            for item in self.session.scalars(
                select(Stock).where(Stock.market == "US", Stock.symbol.in_(symbols))
            )
        }
        result: dict[str, list[Price]] = {symbol: [] for symbol in symbols}
        rows = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(stocks),
                Price.trade_date.between(start_date, end_date),
                Price.source == "yahoo_finance",
                Price.price_type.in_(("unadjusted_ohlcv", "index_level_ohlcv")),
                Price.available_time.is_not(None),
                Price.available_time <= decision_time,
            )
            .order_by(Price.stock_id, Price.trade_date)
        )
        for row in rows:
            result[stocks[row.stock_id]].append(row)
        return {symbol: tuple(values) for symbol, values in result.items()}

    def _certify_actions(
        self,
        assets: Sequence[ResearchAsset],
        start_date: date,
        end_date: date,
        retrieved_at: datetime,
    ) -> CorporateActionCertificate:
        stocks = {
            item.symbol: item
            for item in self.session.scalars(
                select(Stock).where(
                    Stock.market == "US",
                    Stock.symbol.in_([asset.ticker for asset in assets]),
                )
            )
        }
        results: list[CorporateActionSymbolEvidence] = []
        errors: list[str] = []
        events_found = 0
        observed_events: list[ActionEvidence] = []
        for asset in assets:
            try:
                events = tuple(self.action_fetcher(asset, start_date, end_date, retrieved_at))
                stock = stocks.get(asset.ticker)
                if stock is None:
                    raise ValueError("security master record missing")
                for raw_event in events:
                    event = replace(raw_event, symbol=raw_event.symbol or asset.ticker)
                    if event.symbol != asset.ticker:
                        raise ValueError("corporate action symbol does not match request")
                    self._validate_action(event, start_date, end_date, retrieved_at)
                    self._persist_action(stock, event, retrieved_at)
                    observed_events.append(event)
                events_found += len(events)
                results.append(
                    CorporateActionSymbolEvidence(
                        asset.ticker, EvidenceStatus.PASS, len(events), ()
                    )
                )
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                message = str(exc)
                errors.append(f"{asset.ticker}: {message}")
                results.append(
                    CorporateActionSymbolEvidence(
                        asset.ticker, EvidenceStatus.FAIL_BLOCKING, 0, (message,)
                    )
                )
        required = {item.ticker for item in assets if item.required}
        required_failed = any(
            item.symbol in required and item.status is not EvidenceStatus.PASS
            for item in results
        )
        optional_failed = any(
            item.symbol not in required and item.status is not EvidenceStatus.PASS
            for item in results
        )
        status = (
            EvidenceStatus.FAIL_BLOCKING
            if required_failed
            else EvidenceStatus.PASS_WITH_WARNING
            if optional_failed
            else EvidenceStatus.PASS
        )
        self.session.flush()
        payload = {
            "status": status.value,
            "provider": "yahoo_finance.actions",
            "policy": "raw_ohlcv_plus_explicit_actions_no_double_adjustment",
            "symbols": [asdict(item) for item in results],
            "events": [asdict(item) for item in observed_events],
            "errors": errors,
        }
        return CorporateActionCertificate(
            status=status,
            provider="yahoo_finance.actions",
            policy="raw_ohlcv_plus_explicit_actions_no_double_adjustment",
            retrieved_at=retrieved_at,
            symbols_checked=tuple(item.ticker for item in assets),
            events_found=events_found,
            adjustment_consistency=(
                "RAW_OHLCV and explicit actions are isolated; provider adjusted close is "
                "supporting evidence only and is never re-adjusted"
            ),
            pit_policy=(
                "announcement timestamp unavailable: action becomes usable only at actual "
                "application ingestion time; no historical availability is backdated and "
                "historical revision certification remains unavailable"
            ),
            events=tuple(observed_events),
            symbol_results=tuple(results),
            validation_errors=tuple(errors),
            content_hash=_hash(payload),
        )

    def _reconcile(
        self,
        assets: Sequence[ResearchAsset],
        primary: Mapping[str, Sequence[Price]],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderReconciliationCertificate, dict[str, set[date]]]:
        results: list[ReconciliationSymbolEvidence] = []
        secondary_dates: dict[str, set[date]] = {}
        stooq_unavailable_reason: str | None = None
        session_dates = _xnys_dates(start_date, end_date)
        for asset in assets:
            primary_close = {
                item.trade_date: float(item.close)
                for item in primary[asset.ticker]
                if item.trade_date in session_dates
            }
            if asset.ticker != "^VIX" and stooq_unavailable_reason is not None:
                results.append(
                    ReconciliationSymbolEvidence(
                        asset.ticker,
                        EvidenceStatus.UNAVAILABLE,
                        "stooq",
                        len(primary_close),
                        0,
                        0,
                        0.0,
                        0,
                        0,
                        stooq_unavailable_reason,
                    )
                )
                continue
            try:
                raw_secondary = dict(self.secondary_fetcher(asset, start_date, end_date))
                secondary = {
                    observed: value
                    for observed, value in raw_secondary.items()
                    if observed in session_dates
                }
                secondary_dates[asset.ticker] = set(secondary)
                results.append(self._compare(asset.ticker, primary_close, secondary))
            except (OSError, ProviderRequestError, RuntimeError, TypeError, ValueError) as exc:
                if asset.ticker != "^VIX":
                    stooq_unavailable_reason = str(exc)
                results.append(
                    ReconciliationSymbolEvidence(
                        asset.ticker,
                        EvidenceStatus.UNAVAILABLE,
                        "cboe_global_indices" if asset.ticker == "^VIX" else "stooq",
                        len(primary_close),
                        0,
                        0,
                        0.0,
                        0,
                        0,
                        str(exc),
                    )
                )
        required = {item.ticker for item in assets if item.required}
        required_bad = any(
            item.symbol in required
            and item.status not in {EvidenceStatus.PASS, EvidenceStatus.PASS_WITH_WARNING}
            for item in results
        )
        optional_bad = any(
            item.symbol not in required
            and item.status not in {EvidenceStatus.PASS, EvidenceStatus.PASS_WITH_WARNING}
            for item in results
        )
        status = (
            EvidenceStatus.FAIL_BLOCKING
            if required_bad
            else EvidenceStatus.PASS_WITH_WARNING
            if optional_bad
            or any(item.status is EvidenceStatus.PASS_WITH_WARNING for item in results)
            else EvidenceStatus.PASS
        )
        payload = {
            "status": status.value,
            "primary": "yahoo_finance",
            "symbols": [asdict(item) for item in results],
        }
        return (
            ProviderReconciliationCertificate(
                status,
                "yahoo_finance",
                ("stooq", "cboe_global_indices"),
                self.settings.market_data_reconciliation_minimum_coverage,
                self.settings.market_data_reconciliation_warning_return_tolerance,
                self.settings.market_data_reconciliation_blocking_return_tolerance,
                tuple(results),
                _hash(payload),
            ),
            secondary_dates,
        )

    def _compare(
        self,
        symbol: str,
        primary: Mapping[date, float],
        secondary: Mapping[date, float],
    ) -> ReconciliationSymbolEvidence:
        common = sorted(set(primary) & set(secondary))
        denominator = max(1, len(primary))
        coverage = len(common) / denominator
        warning = 0
        blocking = 0
        for previous, current in zip(common, common[1:], strict=False):
            if primary[previous] <= 0 or secondary[previous] <= 0:
                blocking += 1
                continue
            delta = abs(
                (primary[current] / primary[previous] - 1.0)
                - (secondary[current] / secondary[previous] - 1.0)
            )
            if delta > self.settings.market_data_reconciliation_blocking_return_tolerance:
                blocking += 1
            elif delta > self.settings.market_data_reconciliation_warning_return_tolerance:
                warning += 1
        ratio = blocking / max(1, len(common) - 1)
        if coverage < self.settings.market_data_reconciliation_minimum_coverage:
            status = EvidenceStatus.FAIL_BLOCKING
            reason = f"independent coverage {coverage:.2%} below minimum"
        elif ratio > self.settings.market_data_reconciliation_maximum_blocking_ratio:
            status = EvidenceStatus.FAIL_BLOCKING
            reason = f"blocking return divergence ratio {ratio:.2%}"
        elif warning or blocking:
            status = EvidenceStatus.PASS_WITH_WARNING
            reason = (
                f"{warning} warning and {blocking} blocking-threshold return "
                "differences observed within the configured aggregate blocking ratio"
            )
        else:
            status = EvidenceStatus.PASS
            reason = "normalized daily-return path reconciled"
        return ReconciliationSymbolEvidence(
            symbol,
            status,
            "cboe_global_indices" if symbol == "^VIX" else "stooq",
            len(primary),
            len(secondary),
            len(common),
            coverage,
            warning,
            blocking,
            reason,
        )

    def _coverage(
        self,
        assets: Sequence[ResearchAsset],
        primary: Mapping[str, Sequence[Price]],
        secondary_dates: Mapping[str, set[date]],
        start_date: date,
        end_date: date,
    ) -> tuple[BarCoverageEvidence, ...]:
        calendar_dates = _xnys_dates(start_date, end_date)
        rows: list[BarCoverageEvidence] = []
        for asset in assets:
            dates = [item.trade_date for item in primary[asset.ticker]]
            expected_dates = calendar_dates
            observed = set(dates)
            matched = observed & expected_dates
            unexpected = observed - expected_dates
            missing = expected_dates - observed
            rows.append(
                BarCoverageEvidence(
                    asset.ticker,
                    asset.required,
                    len(expected_dates),
                    len(matched),
                    len(missing),
                    len(unexpected),
                    len(dates) - len(observed),
                    len(unexpected),
                    len(matched),
                    max(dates, default=None),
                    tuple(sorted(missing)),
                    tuple(sorted(unexpected)),
                )
            )
        return tuple(rows)

    @staticmethod
    def _validate_action(
        event: ActionEvidence, start_date: date, end_date: date, retrieved_at: datetime
    ) -> None:
        if event.event_type not in {"cash_dividend", "split", "reverse_split"}:
            raise ValueError(f"unsupported action type: {event.event_type}")
        if not start_date <= event.effective_date <= end_date:
            raise ValueError("corporate action outside requested range")
        if not isfinite(event.value) or event.value < 0:
            raise ValueError("corporate action value is invalid")
        if event.event_type != "cash_dividend" and event.value <= 0:
            raise ValueError("split ratio must be positive")
        if event.available_at.tzinfo is None or event.available_at > retrieved_at:
            raise ValueError("corporate action availability is invalid")
        if event.announcement_at is not None and event.announcement_at > event.available_at:
            raise ValueError("announcement is after availability")

    def _persist_action(
        self, stock: Stock, event: ActionEvidence, retrieved_at: datetime
    ) -> None:
        action_id = sha256(
            f"{stock.canonical_code}|{event.event_type}|{event.effective_date}|{event.value}".encode()
        ).hexdigest()[:32]
        existing = self.session.scalar(
            select(CorporateAction).where(
                CorporateAction.stock_id == stock.id,
                CorporateAction.action_id == action_id,
                CorporateAction.revision_id == "observed-v1",
                CorporateAction.provider == "yfinance.download.actions",
            )
        )
        if existing is not None:
            return
        self.session.add(
            CorporateAction(
                stock_id=stock.id,
                action_id=action_id,
                revision_id="observed-v1",
                action_type=event.event_type,
                effective_date=event.effective_date,
                announcement_date=(
                    event.announcement_at.date() if event.announcement_at is not None else None
                ),
                available_date=event.available_at.date(),
                event_time=event.available_at,
                available_time=event.available_at,
                ingested_time=retrieved_at,
                split_ratio=(
                    Decimal(str(event.value)) if event.event_type != "cash_dividend" else None
                ),
                cash_amount=(
                    Decimal(str(event.value)) if event.event_type == "cash_dividend" else None
                ),
                currency="USD" if event.event_type == "cash_dividend" else None,
                source=event.source,
                provider="yfinance.download.actions",
                details={
                    "announcement_known": event.announcement_at is not None,
                    "pit_policy": "actual_ingestion_when_announcement_unavailable",
                },
            )
        )

    @staticmethod
    def _fetch_yahoo_actions(
        asset: ResearchAsset, start_date: date, end_date: date, retrieved_at: datetime
    ) -> Sequence[ActionEvidence]:
        import yfinance as yf

        frame = yf.download(
            asset.ticker,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
            repair=False,
            progress=False,
            threads=False,
            timeout=20,
            multi_level_index=False,
        )
        if frame.empty:
            raise ValueError("Yahoo action request returned no market rows")
        result: list[ActionEvidence] = []
        for timestamp, row in frame.iterrows():
            effective = pd.Timestamp(timestamp).date()
            # Yahoo does not expose a reliable announcement/first-publication timestamp
            # through this endpoint.  Never backdate knowledge to the effective session:
            # the action first becomes PIT-visible when this application actually ingests it.
            available = retrieved_at
            for column, action_type in (
                ("Dividends", "cash_dividend"),
                ("Stock Splits", "split"),
            ):
                value = float(row.get(column, 0.0) or 0.0)
                if value:
                    resolved_type = (
                        "reverse_split"
                        if action_type == "split" and 0.0 < value < 1.0
                        else action_type
                    )
                    result.append(
                        ActionEvidence(
                            resolved_type,
                            effective,
                            value,
                            None,
                            available,
                            "yahoo_finance.actions",
                            asset.ticker,
                        )
                    )
        return result

    def _fetch_secondary(
        self, asset: ResearchAsset, start_date: date, end_date: date
    ) -> Mapping[date, float]:
        if asset.ticker == "^VIX":
            request = Request(
                "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
                headers={"User-Agent": "PersonalAlphaTerminal/1.1"},
            )
            with urlopen(request, timeout=self.settings.market_data_timeout_seconds) as response:  # noqa: S310
                payload = response.read().decode("utf-8-sig")
            result: dict[date, float] = {}
            for row in csv.DictReader(io.StringIO(payload)):
                observed = datetime.strptime(row["DATE"], "%m/%d/%Y").date()
                if start_date <= observed <= end_date:
                    result[observed] = float(row["CLOSE"])
            if not result:
                raise ValueError("CBOE VIX history returned no comparable rows")
            return result
        adapter: StooqStockAdapter | StooqETFAdapter
        if asset.asset_type == "stock":
            adapter = StooqStockAdapter(timeout_seconds=self.settings.market_data_timeout_seconds)
        elif asset.asset_type == "etf":
            adapter = StooqETFAdapter(timeout_seconds=self.settings.market_data_timeout_seconds)
        else:
            raise ProviderRequestError("no independent secondary adapter for asset type")
        batch = adapter.fetch_raw(
            AssetPriceRequest(
                symbol=asset.ticker,
                market="US",
                asset_type=asset.asset_type,  # type: ignore[arg-type]
                price_currency="USD",
                start_date=start_date,
                end_date=end_date,
            )
        )
        bars = PriceNormalizer().normalize(batch)
        return {item.date: float(item.close) for item in bars}


def write_evidence(path: Path, document: Mapping[str, Any]) -> str:
    payload = json.dumps(_jsonable(dict(document)), sort_keys=True, ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return sha256(payload.encode("utf-8")).hexdigest()


def _xnys_dates(start_date: date, end_date: date) -> set[date]:
    import exchange_calendars as xcals  # type: ignore[import-untyped]

    calendar = xcals.get_calendar("XNYS")
    return {
        item.date()
        for item in calendar.sessions_in_range(start_date.isoformat(), end_date.isoformat())
    }


def _hash(document: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(_jsonable(dict(document)), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value
