from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.daily_result import StageStatus
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data.capabilities import PROVIDER_CAPABILITIES
from personal_alpha_terminal.models import DataSnapshotManifest, Price, Stock


@dataclass(frozen=True, slots=True)
class DailyDataCertification:
    status: StageStatus
    snapshot_id: str | None
    provider: str
    fallback_provider: str | None
    requested_symbols: tuple[str, ...]
    received_symbols: tuple[str, ...]
    certified_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    optional_missing_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...]
    expected_bars: int
    received_bars: int
    valid_bars: int
    coverage: float
    latest_date: date | None
    latest_timestamp: datetime | None
    corporate_action_status: str
    provider_reconciliation: str
    duplicate_rows: int
    invalid_ohlc: int
    nan_counts: dict[str, int]
    future_rows: int
    timezone_violations: int
    adjustment_status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def metadata(self) -> dict[str, object]:
        return asdict(self)


class DailyDataCertifier:
    """Certify the canonical raw input without confusing it with PIT approval."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def certify(
        self,
        *,
        analysis_date: date,
        decision_time: datetime,
        manifest: DataSnapshotManifest | None,
    ) -> DailyDataCertification:
        required = {
            item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required
        }
        optional = {
            item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if not item.required
        }
        stocks = {
            item.symbol: item.id
            for item in self.session.scalars(
                select(Stock).where(Stock.market == "US", Stock.symbol.in_(required | optional))
            )
        }
        rows = self.session.execute(
            select(
                Stock.symbol,
                func.count(Price.id),
                func.max(Price.trade_date),
                func.max(Price.available_time),
            )
            .join(Price, Price.stock_id == Stock.id)
            .where(
                Stock.market == "US",
                Stock.symbol.in_(required | optional),
                Price.price_type.in_(("unadjusted_ohlcv", "index_level_ohlcv")),
                Price.trade_date <= analysis_date,
            )
            .group_by(Stock.symbol)
        ).all()
        counts = {symbol: int(count) for symbol, count, _latest, _available in rows}
        latest_dates = {symbol: latest for symbol, _count, latest, _available in rows}
        received = {symbol for symbol, count in counts.items() if count > 0}
        minimum_bars = max(126, min(504, int(self.settings.console_initial_history_days * 0.68)))
        certified = {
            symbol
            for symbol in required
            if counts.get(symbol, 0) >= minimum_bars
            and latest_dates.get(symbol) is not None
            and (analysis_date - latest_dates[symbol]).days <= self.settings.console_data_stale_days
        }
        missing = required - received
        insufficient = required - certified - missing
        optional_missing = optional - received
        stale = {
            symbol
            for symbol in required
            if latest_dates.get(symbol) is not None
            and (analysis_date - latest_dates[symbol]).days > self.settings.console_data_stale_days
        }
        required_stock_ids = tuple(
            stock_id for symbol, stock_id in stocks.items() if symbol in required
        )
        invalid_ohlc = int(
            self.session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.stock_id.in_(required_stock_ids),
                    Price.trade_date <= analysis_date,
                    (
                        (Price.open <= 0)
                        | (Price.high <= 0)
                        | (Price.low <= 0)
                        | (Price.close <= 0)
                        | (Price.high < Price.low)
                        | (Price.high < Price.open)
                        | (Price.high < Price.close)
                        | (Price.low > Price.open)
                        | (Price.low > Price.close)
                    ),
                )
            )
            or 0
        )
        future_rows = int(
            self.session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.stock_id.in_(required_stock_ids),
                    Price.available_time.is_not(None),
                    Price.available_time > decision_time,
                )
            )
            or 0
        )
        timestamp_violations = int(
            self.session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.stock_id.in_(required_stock_ids),
                    Price.trade_date <= analysis_date,
                    (
                        Price.event_time.is_(None)
                        | Price.available_time.is_(None)
                        | (Price.available_time < Price.event_time)
                    ),
                )
            )
            or 0
        )
        duplicate_rows = int(manifest.duplicate_count if manifest is not None else 0)
        document = self._manifest_document(manifest)
        reconciled = bool(document.get("provider_reconciled", False))
        corporate_action_status = (
            "CERTIFIED"
            if manifest is not None
            and manifest.corporate_action_policy == "certified_pit_ledger"
            else "NOT_CERTIFIED"
        )
        blockers: list[str] = []
        warnings: list[str] = []
        if manifest is None:
            blockers.append("immutable market-data snapshot manifest is missing")
        if missing:
            blockers.append("required symbols missing: " + ", ".join(sorted(missing)))
        if insufficient:
            blockers.append(
                f"required symbols have insufficient history (<{minimum_bars} bars): "
                + ", ".join(sorted(insufficient))
            )
        if stale:
            blockers.append("required symbols are stale: " + ", ".join(sorted(stale)))
        if invalid_ohlc:
            blockers.append(f"invalid OHLC rows detected: {invalid_ohlc}")
        if future_rows:
            blockers.append(f"future-available rows detected: {future_rows}")
        if timestamp_violations:
            blockers.append(
                f"timestamp/timezone contract violations detected: {timestamp_violations}"
            )
        if corporate_action_status != "CERTIFIED":
            blockers.append("corporate-action ledger is not certified for PIT decisions")
        if not reconciled:
            blockers.append("independent provider reconciliation is not certified")
        if duplicate_rows:
            warnings.append(f"provider update/duplicate observations reported: {duplicate_rows}")
        if optional_missing:
            warnings.append("optional symbols missing: " + ", ".join(sorted(optional_missing)))
        received_bars = sum(counts.get(symbol, 0) for symbol in required)
        expected_bars = minimum_bars * len(required)
        valid_bars = max(0, received_bars - invalid_ohlc - future_rows)
        status = StageStatus.FAIL_BLOCKING if blockers else (
            StageStatus.PASS_DEGRADED if warnings else StageStatus.PASS
        )
        latest_date = max((value for value in latest_dates.values() if value), default=None)
        latest_timestamp = max(
            (value for _symbol, _count, _latest, value in rows if value is not None),
            default=None,
        )
        if latest_timestamp is not None and latest_timestamp.tzinfo is None:
            latest_timestamp = latest_timestamp.replace(tzinfo=UTC)
        return DailyDataCertification(
            status,
            manifest.snapshot_id if manifest else None,
            manifest.provider_name if manifest else "UNAVAILABLE",
            self._fallback_provider(manifest),
            tuple(manifest.symbols) if manifest else tuple(sorted(required | optional)),
            tuple(sorted(received)),
            tuple(sorted(certified)),
            tuple(sorted(missing | insufficient)),
            tuple(sorted(optional_missing)),
            tuple(sorted(stale)),
            expected_bars,
            received_bars,
            valid_bars,
            min(1.0, valid_bars / expected_bars) if expected_bars else 0.0,
            latest_date,
            latest_timestamp,
            corporate_action_status,
            "CERTIFIED" if reconciled else "NOT_CERTIFIED",
            duplicate_rows,
            invalid_ohlc,
            {"open": 0, "high": 0, "low": 0, "close": 0},
            future_rows,
            timestamp_violations,
            manifest.price_adjustment_policy if manifest else "UNAVAILABLE",
            tuple(blockers),
            tuple(warnings),
        )

    @staticmethod
    def _manifest_document(manifest: DataSnapshotManifest | None) -> dict[str, Any]:
        if manifest is None:
            return {}
        try:
            payload = json.loads(Path(manifest.immutable_reference).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _fallback_provider(cls, manifest: DataSnapshotManifest | None) -> str | None:
        active = {
            item.strip()
            for item in (manifest.provider_name if manifest is not None else "").split(",")
            if item.strip()
        }
        coverage: dict[str, set[str]] = {}
        for capability in PROVIDER_CAPABILITIES:
            if (
                capability.market == "US"
                and capability.supported
                and capability.provider not in active
            ):
                coverage.setdefault(capability.provider, set()).add(capability.asset_type)
        if not coverage:
            return None
        return ",".join(
            f"{provider}:{'/'.join(sorted(asset_types))}"
            for provider, asset_types in sorted(coverage.items())
        )
