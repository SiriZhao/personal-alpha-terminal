from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.daily_result import StageStatus
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import CorporateAction, DataSnapshotManifest, Price, Stock


@dataclass(frozen=True, slots=True)
class DailyDataCertification:
    status: StageStatus
    snapshot_id: str | None
    data_hash: str | None
    provider: str
    fallback_provider: str | None
    requested_symbols: tuple[str, ...]
    received_symbols: tuple[str, ...]
    primary_valid_symbols: tuple[str, ...]
    secondary_checked_symbols: tuple[str, ...]
    certified_symbols: tuple[str, ...]
    rejected_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    optional_missing_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...]
    expected_bars: int
    matched_bars: int
    unexpected_bars: int
    missing_bars: int
    received_bars: int
    valid_bars: int
    coverage: float
    latest_date: date | None
    latest_timestamp: datetime | None
    pit_cutoff: datetime | None
    latest_completed_session: date | None
    decision_timestamp_convention: str
    corporate_action_status: str
    provider_reconciliation: str
    duplicate_rows: int
    invalid_ohlc: int
    nan_counts: dict[str, int]
    future_rows: int
    timezone_violations: int
    adjustment_status: str
    symbol_matrix: tuple[dict[str, object], ...]
    evidence_paths: dict[str, str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    required_certified: int = 0
    required_total: int = 0
    optional_certified: int = 0
    optional_total: int = 0
    quarantined_bars: int = 0
    fallback_usage: tuple[dict[str, object], ...] = ()
    pit_integrity_status: str = "NOT_CERTIFIED"
    freshness_status: str = "NOT_CERTIFIED"
    live_refresh_status: str = "LIVE_REFRESH_FAIL"
    requested_security_count: int = 0
    actual_refresh_count: int = 0
    cache_reuse_count: int = 0
    provider_returned_count: int = 0
    certified_coverage: float = 0.0
    quarantine_count: int = 0
    provider_incident_count: int = 0
    coverage_collapse: bool = False

    def metadata(self) -> dict[str, object]:
        return asdict(self)


class DailyDataCertifier:
    """Certify canonical inputs from immutable evidence, never from a green label."""

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
        assets = {item.ticker: item for item in MINIMUM_US_RESEARCH_UNIVERSE}
        required = {symbol for symbol, item in assets.items() if item.required}
        optional = set(assets) - required
        window_start = manifest.start_date if manifest is not None else date.min
        stocks = {
            item.symbol: item.id
            for item in self.session.scalars(
                select(Stock).where(Stock.market == "US", Stock.symbol.in_(assets))
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
                Stock.symbol.in_(assets),
                Price.price_type.in_(("unadjusted_ohlcv", "index_level_ohlcv")),
                Price.trade_date <= analysis_date,
            )
            .group_by(Stock.symbol)
        ).all()
        counts = {symbol: int(count) for symbol, count, _latest, _available in rows}
        minimum_bars = max(
            126,
            min(504, int(self.settings.console_initial_history_days * 0.68)),
        )
        latest_dates = {symbol: latest for symbol, _count, latest, _available in rows}
        received = {symbol for symbol, count in counts.items() if count > 0}
        missing = required - received
        optional_missing = optional - received
        stale = {
            symbol
            for symbol in required
            if latest_dates.get(symbol) != analysis_date
        }
        stock_ids = tuple(stocks.values())
        invalid_rows = self.session.execute(
            select(Stock.symbol, func.count(Price.id))
            .join(Price, Price.stock_id == Stock.id)
            .where(
                Price.stock_id.in_(stock_ids),
                Price.trade_date.between(window_start, analysis_date),
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
            .group_by(Stock.symbol)
        ).all()
        invalid_by_symbol = {symbol: int(count) for symbol, count in invalid_rows}
        invalid_ohlc = sum(invalid_by_symbol.values())
        future_rows = int(
            self.session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.stock_id.in_(stock_ids),
                    Price.trade_date.between(window_start, analysis_date),
                    Price.available_time.is_not(None),
                    Price.available_time > decision_time,
                )
            )
            or 0
        )
        timestamp_violations = int(
            self.session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.stock_id.in_(stock_ids),
                    Price.trade_date.between(window_start, analysis_date),
                    (
                        Price.event_time.is_(None)
                        | Price.available_time.is_(None)
                        | (Price.available_time < Price.event_time)
                    ),
                )
            )
            or 0
        )
        action_future_rows = int(
            self.session.scalar(
                select(func.count()).select_from(CorporateAction).where(
                    CorporateAction.stock_id.in_(stock_ids),
                    CorporateAction.effective_date.between(window_start, analysis_date),
                    CorporateAction.available_time > decision_time,
                )
            )
            or 0
        )
        nan_counts = {
            column: int(
                self.session.scalar(
                    select(func.count()).select_from(Price).where(
                        Price.stock_id.in_(stock_ids),
                        Price.trade_date.between(window_start, analysis_date),
                        getattr(Price, column).is_(None),
                    )
                )
                or 0
            )
            for column in ("open", "high", "low", "close")
        }
        document = self._manifest_document(manifest)
        coverage_rows = {
            str(item.get("symbol")): item
            for item in document.get("bar_coverage", [])
            if isinstance(item, dict) and item.get("symbol")
        }
        action_rows = {
            str(item.get("symbol")): item
            for item in document.get("corporate_action_symbol_results", [])
            if isinstance(item, dict) and item.get("symbol")
        }
        reconciliation_rows = {
            str(item.get("symbol")): item
            for item in document.get("provider_reconciliation_symbol_results", [])
            if isinstance(item, dict) and item.get("symbol")
        }
        corporate_status = str(document.get("corporate_action_status", "NOT_CERTIFIED"))
        reconciliation_status = "NOT_REQUIRED"
        accepted_statuses = {"PASS", "PASS_WITH_WARNING"}
        symbol_matrix: list[dict[str, object]] = []
        certified: set[str] = set()
        secondary_checked: set[str] = set()
        rejected: set[str] = set()
        for symbol, asset in assets.items():
            coverage = coverage_rows.get(symbol, {})
            action = action_rows.get(symbol, {})
            reconciliation = reconciliation_rows.get(symbol, {})
            primary_ok = (
                symbol in received
                and symbol not in stale
                and counts.get(symbol, 0) >= minimum_bars
                and int(coverage.get("missing", 1)) == 0
                and int(coverage.get("unexpected", 1))
                == int(coverage.get("rejected", 0))
                and int(coverage.get("duplicate", 1)) == 0
            )
            action_status = str(action.get("status", "UNAVAILABLE"))
            cross_status = str(reconciliation.get("status", "UNAVAILABLE"))
            attempts = reconciliation.get("secondary_candidates_attempted", [])
            if cross_status != "UNAVAILABLE" or attempts:
                secondary_checked.add(symbol)
            final = (
                primary_ok
                and action_status in accepted_statuses
                and invalid_by_symbol.get(symbol, 0) == 0
            )
            reasons: list[str] = []
            if not primary_ok:
                reasons.append("primary/calendar coverage failed")
            if action_status not in accepted_statuses:
                reasons.append("corporate actions " + action_status)
            if final:
                certified.add(symbol)
            else:
                rejected.add(symbol)
            symbol_matrix.append(
                {
                    "symbol": symbol,
                    "required": asset.required,
                    "primary": "PASS" if primary_ok else "FAIL",
                    "secondary": cross_status,
                    "freshness": "FAIL" if symbol in stale else "PASS",
                    "ohlc": "PASS" if invalid_by_symbol.get(symbol, 0) == 0 else "FAIL",
                    "calendar": (
                        (
                            "PASS_WITH_QUARANTINE"
                            if int(coverage.get("rejected", 0))
                            else "PASS"
                        )
                        if not int(coverage.get("missing", 1))
                        and int(coverage.get("unexpected", 1))
                        == int(coverage.get("rejected", 0))
                        else "FAIL"
                    ),
                    "corporate_action": action_status,
                    "cross_provider": "NOT_REQUIRED",
                    "secondary_provider": reconciliation.get("secondary_provider"),
                    "secondary_candidates_attempted": attempts,
                    "primary_latest_session": reconciliation.get("primary_latest_session"),
                    "secondary_latest_session": reconciliation.get("secondary_latest_session"),
                    "overlap_rows": reconciliation.get("matched_rows", 0),
                    "max_return_diff": reconciliation.get("max_return_diff"),
                    "median_return_diff": reconciliation.get("median_return_diff"),
                    "large_divergence_ratio": reconciliation.get("large_divergence_ratio"),
                    "failure_category": reconciliation.get("failure_category"),
                    "pit": "PASS" if final and document.get("pit_data_cutoff") else "FAIL",
                    "final": "CERTIFIED" if final else "REJECTED",
                    "reason": "; ".join(reasons),
                }
            )
        expected = sum(int(item.get("expected", 0)) for item in coverage_rows.values())
        matched = sum(int(item.get("matched", 0)) for item in coverage_rows.values())
        unexpected = sum(int(item.get("unexpected", 0)) for item in coverage_rows.values())
        missing_bars = sum(int(item.get("missing", 0)) for item in coverage_rows.values())
        duplicate_rows = sum(int(item.get("duplicate", 0)) for item in coverage_rows.values())
        quarantined_bars = sum(
            int(item.get("rejected", 0)) for item in coverage_rows.values()
        )
        received_bars = sum(
            int(item.get("valid", 0))
            + int(item.get("rejected", 0))
            + int(item.get("duplicate", 0))
            for item in coverage_rows.values()
        )
        valid_bars = max(0, matched - invalid_ohlc - future_rows)
        blockers: list[str] = []
        warnings: list[str] = []
        if manifest is None:
            blockers.append("immutable market-data snapshot manifest is missing")
        if missing:
            blockers.append("required symbols missing: " + ", ".join(sorted(missing)))
        if stale:
            blockers.append("required symbols are stale: " + ", ".join(sorted(stale)))
        required_rejected = rejected & required
        insufficient_required = {
            symbol for symbol in required if 0 < counts.get(symbol, 0) < minimum_bars
        }
        if insufficient_required:
            blockers.append(
                f"insufficient history (<{minimum_bars} bars): "
                + ", ".join(sorted(insufficient_required))
            )
        if required_rejected:
            blockers.append(
                "required symbols rejected by certification: "
                + ", ".join(sorted(required_rejected))
            )
        if invalid_ohlc:
            blockers.append(f"invalid OHLC rows detected: {invalid_ohlc}")
        if future_rows:
            blockers.append(f"future-available rows detected: {future_rows}")
        if action_future_rows:
            blockers.append(
                f"future-available corporate actions detected: {action_future_rows}"
            )
        if any(nan_counts.values()):
            blockers.append(
                "null OHLC values detected: "
                + ", ".join(f"{key}={value}" for key, value in nan_counts.items() if value)
            )
        if timestamp_violations:
            blockers.append(f"timestamp contract violations detected: {timestamp_violations}")
        if corporate_status not in accepted_statuses:
            blockers.append("corporate-action ledger is not certified for PIT decisions")
        unquarantined = max(unexpected - quarantined_bars, 0)
        if unquarantined:
            blockers.append(
                f"unquarantined calendar observations detected: {unquarantined}"
            )
        if quarantined_bars:
            warnings.append(
                f"non-session observations quarantined from PIT inputs: {quarantined_bars}"
            )
        optional_rejected = rejected & optional
        if optional_rejected:
            warnings.append("optional symbols rejected: " + ", ".join(sorted(optional_rejected)))
        if optional_missing:
            warnings.append("optional symbols missing: " + ", ".join(sorted(optional_missing)))
        pit_cutoff = _parse_datetime(document.get("pit_data_cutoff"))
        if pit_cutoff is None:
            blockers.append("PIT data cutoff is unavailable")
        elif pit_cutoff > decision_time:
            blockers.append("PIT data cutoff is after decision time")
        status = (
            StageStatus.FAIL_BLOCKING
            if blockers
            else StageStatus.PASS_DEGRADED
            if warnings or corporate_status == "PASS_WITH_WARNING"
            else StageStatus.PASS
        )
        latest_timestamp = max(
            (value for _symbol, _count, _latest, value in rows if value is not None),
            default=None,
        )
        if latest_timestamp is not None and latest_timestamp.tzinfo is None:
            latest_timestamp = latest_timestamp.replace(tzinfo=UTC)
        latest_completed = _parse_date(document.get("latest_completed_session"))
        return DailyDataCertification(
            status=status,
            snapshot_id=manifest.snapshot_id if manifest else None,
            data_hash=manifest.content_hash if manifest else None,
            provider=manifest.provider_name if manifest else "UNAVAILABLE",
            fallback_provider=self._fallback_provider(manifest, document),
            requested_symbols=tuple(manifest.symbols) if manifest else tuple(sorted(assets)),
            received_symbols=tuple(sorted(received)),
            primary_valid_symbols=tuple(
                sorted(
                    str(item["symbol"])
                    for item in symbol_matrix
                    if item["primary"] == "PASS"
                )
            ),
            secondary_checked_symbols=tuple(sorted(secondary_checked)),
            certified_symbols=tuple(sorted(certified)),
            rejected_symbols=tuple(sorted(rejected)),
            missing_symbols=tuple(sorted(missing)),
            optional_missing_symbols=tuple(sorted(optional_missing)),
            stale_symbols=tuple(sorted(stale)),
            expected_bars=expected,
            matched_bars=matched,
            unexpected_bars=unexpected,
            missing_bars=missing_bars,
            received_bars=received_bars,
            valid_bars=valid_bars,
            coverage=matched / expected if expected else 0.0,
            latest_date=max((value for value in latest_dates.values() if value), default=None),
            latest_timestamp=latest_timestamp,
            pit_cutoff=pit_cutoff,
            latest_completed_session=latest_completed,
            decision_timestamp_convention=str(
                document.get("decision_timestamp_convention", "UNAVAILABLE")
            ),
            corporate_action_status=corporate_status,
            provider_reconciliation=reconciliation_status,
            duplicate_rows=duplicate_rows,
            invalid_ohlc=invalid_ohlc,
            nan_counts=nan_counts,
            future_rows=future_rows + action_future_rows,
            timezone_violations=timestamp_violations,
            adjustment_status=(
                manifest.price_adjustment_policy if manifest else "UNAVAILABLE"
            ),
            symbol_matrix=tuple(symbol_matrix),
            evidence_paths={
                str(key): str(value)
                for key, value in document.get("evidence", {}).items()
            }
            if isinstance(document.get("evidence"), dict)
            else {},
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            required_certified=len(certified & required),
            required_total=len(required),
            optional_certified=len(certified & optional),
            optional_total=len(optional),
            quarantined_bars=quarantined_bars,
            fallback_usage=tuple(
                dict(item)
                for item in document.get("fallback_usage", [])
                if isinstance(item, dict)
            ),
            pit_integrity_status=(
                "PASS"
                if pit_cutoff is not None
                and pit_cutoff <= decision_time
                and not future_rows
                and not action_future_rows
                and not timestamp_violations
                else "FAIL"
            ),
            freshness_status="PASS" if not stale else "FAIL",
            live_refresh_status=_live_refresh_status(
                manifest=manifest,
                status=status,
                quarantined_bars=quarantined_bars,
                fallback_usage=tuple(
                    dict(item)
                    for item in document.get("fallback_usage", [])
                    if isinstance(item, dict)
                ),
                coverage_collapse=bool(blockers),
            ),
            requested_security_count=len(manifest.symbols) if manifest is not None else 0,
            actual_refresh_count=_status_count(manifest, "success"),
            cache_reuse_count=_status_count(manifest, "cached"),
            provider_returned_count=len(received),
            certified_coverage=matched / expected if expected else 0.0,
            quarantine_count=quarantined_bars,
            provider_incident_count=_provider_incident_count(manifest),
            coverage_collapse=bool(blockers),
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
    def _fallback_provider(
        cls, manifest: DataSnapshotManifest | None, document: Mapping[str, Any] | None = None
    ) -> str | None:
        fallbacks = document.get("fallback_usage") if isinstance(document, Mapping) else None
        if isinstance(fallbacks, list):
            used = sorted(
                {
                    str(item.get("provider"))
                    for item in fallbacks
                    if isinstance(item, Mapping) and item.get("provider")
                }
            )
            if used:
                return ",".join(used)
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _live_refresh_status(
    *,
    manifest: DataSnapshotManifest | None,
    status: StageStatus,
    quarantined_bars: int,
    fallback_usage: tuple[dict[str, object], ...],
    coverage_collapse: bool,
) -> str:
    if status is StageStatus.FAIL_BLOCKING:
        return "LIVE_REFRESH_FAIL"
    if _provider_incident_count(manifest):
        return "LIVE_REFRESH_DEGRADED_PROVIDER"
    if coverage_collapse:
        return "LIVE_REFRESH_PARTIAL_COVERAGE"
    if quarantined_bars or fallback_usage or (
        manifest is not None and bool(manifest.failed_symbols)
    ):
        return "LIVE_REFRESH_PASS_WITH_QUARANTINE"
    return "LIVE_REFRESH_PASS"


def _status_count(manifest: DataSnapshotManifest | None, status: str) -> int:
    if manifest is None:
        return 0
    return sum(
        1
        for item in manifest.missingness_summary.values()
        if isinstance(item, dict) and item.get("status") == status
    )


def _provider_incident_count(manifest: DataSnapshotManifest | None) -> int:
    if manifest is None:
        return 0
    incident_markers = {
        "RATE_LIMIT",
        "TIMEOUT",
        "SCHEMA",
        "BOT_CHALLENGE",
        "PROVIDER_ERROR",
        "CIRCUIT",
    }
    return sum(
        1
        for item in manifest.missingness_summary.values()
        if isinstance(item, dict)
        and (
            item.get("status") == "failed"
            and any(
                marker in str(item.get("error", "")).upper()
                for marker in incident_markers
            )
        )
    )
