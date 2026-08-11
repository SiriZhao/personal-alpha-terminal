"""Normalized, provider-neutral historical research dataset packages.

The importer accepts evidence; it does not improve it. Current snapshots,
final adjusted price series and unknown lifecycle fields remain explicit
blockers rather than being inferred into a survivorship-safe history.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import canonical_json, fingerprint
from personal_alpha_terminal.quant_engine.research_data import DataDomain, ResearchDatasetState


class SecurityType(StrEnum):
    US_EQUITY = "US_EQUITY"
    US_ETF = "US_ETF"
    BENCHMARK = "BENCHMARK"


class ResearchUseScope(StrEnum):
    PRODUCTION_RESEARCH = "PRODUCTION_RESEARCH"
    TEST_FIXTURE = "TEST_FIXTURE"


class AdjustmentKind(StrEnum):
    RAW = "RAW"
    PIT_TOTAL_RETURN_VINTAGE = "PIT_TOTAL_RETURN_VINTAGE"
    CURRENT_FINAL_ADJUSTED = "CURRENT_FINAL_ADJUSTED"


class ResearchRecordType(StrEnum):
    SECURITY = "SECURITY"
    MEMBERSHIP = "MEMBERSHIP"
    PRICE = "PRICE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    CALENDAR = "CALENDAR"


@dataclass(frozen=True, slots=True)
class HistoricalSecurity:
    permanent_security_id: str
    ticker: str
    ticker_valid_from: date
    ticker_valid_to: date | None
    exchange: str
    listing_date: date | None
    delisting_date: date | None
    delisting_reason: str
    security_type: SecurityType
    available_at: datetime
    source: str
    provider: str

    def __post_init__(self) -> None:
        _require_lineage(
            self.permanent_security_id, self.ticker, self.exchange, self.source, self.provider
        )
        _require_aware(self.available_at, "security available_at")
        if self.ticker_valid_to is not None and self.ticker_valid_to < self.ticker_valid_from:
            raise ValueError("ticker validity end cannot precede start")
        if self.delisting_date is not None and self.listing_date is not None:
            if self.delisting_date < self.listing_date:
                raise ValueError("delisting date cannot precede listing date")


@dataclass(frozen=True, slots=True)
class HistoricalUniverseMembership:
    permanent_security_id: str
    universe_id: str
    universe_type: SecurityType
    effective_from: date
    effective_to: date | None
    available_at: datetime
    source_timestamp: datetime
    membership_source_type: str
    source: str
    provider: str

    def __post_init__(self) -> None:
        _require_lineage(self.permanent_security_id, self.universe_id, self.source, self.provider)
        _require_aware(self.available_at, "membership available_at")
        _require_aware(self.source_timestamp, "membership source_timestamp")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("membership end cannot precede start")

    def active_on(self, session: date, decision_time: datetime) -> bool:
        _require_aware(decision_time, "membership decision_time")
        return (
            self.available_at <= decision_time
            and self.effective_from <= session
            and (self.effective_to is None or session <= self.effective_to)
        )


@dataclass(frozen=True, slots=True)
class ResearchPrice:
    permanent_security_id: str
    ticker: str
    observation_date: date
    available_at: datetime
    exchange: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjustment_kind: AdjustmentKind
    total_return_value: float | None
    total_return_available_at: datetime | None
    adjustment_vintage_id: str | None
    source: str
    provider: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "open", float(self.open))
        object.__setattr__(self, "high", float(self.high))
        object.__setattr__(self, "low", float(self.low))
        object.__setattr__(self, "close", float(self.close))
        object.__setattr__(self, "volume", int(self.volume))
        if self.total_return_value is not None:
            object.__setattr__(self, "total_return_value", float(self.total_return_value))
        _require_lineage(
            self.permanent_security_id, self.ticker, self.exchange, self.source, self.provider
        )
        _require_aware(self.available_at, "price available_at")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("price row contains invalid OHLCV")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("price row violates OHLC bounds")
        if self.total_return_available_at is not None:
            _require_aware(self.total_return_available_at, "total return available_at")


@dataclass(frozen=True, slots=True)
class ResearchCorporateAction:
    permanent_security_id: str
    action_type: str
    effective_date: date
    announcement_date: date | None
    available_at: datetime
    source: str
    provider: str
    ratio: float | None = None
    cash_amount: float | None = None
    terminal_return: float | None = None
    successor_security_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("ratio", "cash_amount", "terminal_return"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, float(value))
        _require_lineage(self.permanent_security_id, self.action_type, self.source, self.provider)
        _require_aware(self.available_at, "corporate action available_at")
        if self.announcement_date is not None and self.announcement_date > self.effective_date:
            raise ValueError("corporate action announcement cannot follow effective date")
        if self.action_type == "SPLIT" and (self.ratio is None or self.ratio <= 0):
            raise ValueError("split requires a positive ratio")


@dataclass(frozen=True, slots=True)
class ExchangeSession:
    calendar_id: str
    session_date: date
    open_time: datetime
    close_time: datetime
    is_early_close: bool
    available_at: datetime
    source: str
    provider: str

    def __post_init__(self) -> None:
        _require_lineage(self.calendar_id, self.source, self.provider)
        _require_aware(self.open_time, "session open_time")
        _require_aware(self.close_time, "session close_time")
        _require_aware(self.available_at, "session available_at")
        if self.close_time <= self.open_time:
            raise ValueError("calendar close must follow open")


@dataclass(frozen=True, slots=True)
class ResearchDatasetPackage:
    dataset_id: str
    schema_version: str
    provider: str
    source: str
    retrieved_at: datetime
    as_of: date
    cutoff: datetime
    use_scope: ResearchUseScope
    securities: tuple[HistoricalSecurity, ...]
    memberships: tuple[HistoricalUniverseMembership, ...]
    prices: tuple[ResearchPrice, ...]
    corporate_actions: tuple[ResearchCorporateAction, ...]
    calendar: tuple[ExchangeSession, ...]
    data_domain: DataDomain = DataDomain.RESEARCH_RAW_DATA

    def __post_init__(self) -> None:
        _require_lineage(self.dataset_id, self.schema_version, self.provider, self.source)
        _require_aware(self.retrieved_at, "dataset retrieved_at")
        _require_aware(self.cutoff, "dataset cutoff")
        if self.as_of > self.cutoff.date():
            raise ValueError("dataset as_of cannot follow cutoff")
        if self.data_domain is not DataDomain.RESEARCH_RAW_DATA:
            raise ValueError("imports must enter through RESEARCH_RAW_DATA")

    def content_document(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "securities": _sorted_documents(self.securities),
            "memberships": _sorted_documents(self.memberships),
            "prices": _sorted_documents(self.prices),
            "corporate_actions": _sorted_documents(self.corporate_actions),
            "calendar": _sorted_documents(self.calendar),
        }

    @property
    def content_hash(self) -> str:
        return fingerprint(self.content_document())


@dataclass(frozen=True, slots=True)
class ResearchDatasetManifestV2:
    dataset_id: str
    dataset_version: str
    schema_version: str
    data_domain: DataDomain
    use_scope: ResearchUseScope
    production_eligible: bool
    provider: str
    source: str
    retrieved_at: datetime
    as_of: date
    cutoff: datetime
    required_start: date | None
    required_end: date | None
    date_start: date | None
    date_end: date | None
    row_count: int
    security_count: int
    ticker_vintage_count: int
    universe_count: int
    membership_count: int
    delisted_count: int
    corporate_action_count: int
    calendar_session_count: int
    raw_price_certified: bool
    total_return_certified: bool
    content_hash: str
    inventory_hash: str
    certification_state: ResearchDatasetState
    blockers: tuple[str, ...]
    manifest_hash: str

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider_id: str
    prices: bool
    historical_membership: bool
    delistings: bool
    identifier_history: bool
    corporate_actions: str
    total_return_vintages: bool
    exchange_calendar: bool
    access: str
    certification_note: str


def builtin_provider_capabilities() -> tuple[ProviderCapability, ...]:
    """Capabilities of adapters that are actually present in this repository."""

    return (
        ProviderCapability(
            "yfinance", True, False, False, False, "PARTIAL", False, False,
            "AUTOMATIC_LIVE", "final adjusted history is not a PIT vintage",
        ),
        ProviderCapability(
            "stooq", True, False, False, False, "NONE", False, False,
            "AUTOMATIC_BEST_EFFORT", "daily prices only; not certifiable alone",
        ),
        ProviderCapability(
            "twelve_data", True, False, False, False, "NONE", False, False,
            "API_KEY_OPTIONAL", "recent daily price validation only",
        ),
        ProviderCapability(
            "alpha_vantage", True, False, False, False, "NONE", False, False,
            "API_KEY_OPTIONAL", "recent daily price validation only",
        ),
        ProviderCapability(
            "exchange_calendars", False, False, False, False, "NONE", False, True,
            "AUTOMATIC_LOCAL", "US sessions, holidays and early closes",
        ),
    )


def certify_research_package(
    package: ResearchDatasetPackage,
    *,
    required_start: date | None = None,
    required_end: date | None = None,
) -> ResearchDatasetManifestV2:
    """Normalize and validate a package without inferring missing evidence."""

    blockers: list[str] = []
    rejected: list[str] = []
    securities = {item.permanent_security_id for item in package.securities}
    if not package.securities:
        blockers.append("SECURITY_IDENTIFIER_HISTORY_INCOMPLETE")
    if not package.memberships:
        blockers.append("HISTORICAL_MEMBERSHIP_INCOMPLETE")
    if not package.prices:
        blockers.append("RAW_OHLCV_DATA_NOT_AVAILABLE")
    if not package.calendar:
        blockers.append("EXCHANGE_CALENDAR_INCOMPLETE")

    _validate_ticker_vintages(package.securities, rejected)
    for membership in package.memberships:
        if membership.permanent_security_id not in securities:
            rejected.append("MEMBERSHIP_SECURITY_ID_ORPHANED")
        if membership.membership_source_type.upper() == "CURRENT_SNAPSHOT":
            blockers.append("CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED")
        if membership.available_at > package.cutoff:
            rejected.append("FUTURE_MEMBERSHIP_LEAKAGE")
        expected = _security_type_on(package.securities, membership.permanent_security_id)
        if expected is not None and expected is not membership.universe_type:
            rejected.append("ETF_EQUITY_BENCHMARK_UNIVERSE_MIXED")

    for price in package.prices:
        if price.permanent_security_id not in securities:
            rejected.append("PRICE_SECURITY_ID_ORPHANED")
        if price.observation_date > package.as_of or price.available_at > package.cutoff:
            rejected.append("FUTURE_PRICE_ROW")
        if price.adjustment_kind is AdjustmentKind.CURRENT_FINAL_ADJUSTED:
            blockers.append("CURRENT_ADJUSTED_SERIES_NOT_PIT_VINTAGE")

    for action in package.corporate_actions:
        if action.permanent_security_id not in securities:
            rejected.append("CORPORATE_ACTION_SECURITY_ID_ORPHANED")
        if action.available_at.date() > action.effective_date:
            rejected.append("FUTURE_CORPORATE_ACTION_LEAKAGE")
        if action.action_type == "SYMBOL_CHANGE" and action.successor_security_id not in {
            None,
            action.permanent_security_id,
        }:
            rejected.append("SYMBOL_CHANGE_CREATED_NEW_SECURITY_ID")

    _validate_lifecycle(package, blockers)
    calendar_valid = _validate_calendar(package.calendar, blockers, rejected)
    date_start = min((item.observation_date for item in package.prices), default=None)
    date_end = max((item.observation_date for item in package.prices), default=None)
    if required_start is not None and (date_start is None or date_start > required_start):
        blockers.append("STRATEGY_PERIOD_START_COVERAGE_INCOMPLETE")
    if required_end is not None and (date_end is None or date_end < required_end):
        blockers.append("STRATEGY_PERIOD_END_COVERAGE_INCOMPLETE")

    raw_price_certified = bool(package.prices) and calendar_valid and not any(
        item in rejected for item in ("FUTURE_PRICE_ROW", "PRICE_SECURITY_ID_ORPHANED")
    )
    total_return_certified = bool(package.prices) and all(
        item.adjustment_kind is AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE
        and item.total_return_value is not None
        and item.total_return_available_at is not None
        and item.total_return_available_at <= package.cutoff
        and bool(item.adjustment_vintage_id)
        for item in package.prices
    )
    if not total_return_certified:
        blockers.append("PIT_TOTAL_RETURN_HISTORY_INCOMPLETE")
    if not package.corporate_actions:
        blockers.append("CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE")

    blockers = sorted(set(blockers))
    rejected = sorted(set(rejected))
    all_blockers = tuple([*rejected, *blockers])
    state = (
        ResearchDatasetState.REJECTED
        if rejected
        else ResearchDatasetState.NOT_CERTIFIABLE
        if blockers
        else ResearchDatasetState.CERTIFIED
    )
    output_domain = (
        DataDomain.RESEARCH_CERTIFIED_DATA
        if state is ResearchDatasetState.CERTIFIED
        else DataDomain.RESEARCH_RAW_DATA
    )
    content_hash = package.content_hash
    dataset_version = f"research-{content_hash[:24]}"
    counts = {
        "security_count": len({item.permanent_security_id for item in package.securities}),
        "ticker_vintage_count": len(package.securities),
        "membership_count": len(package.memberships),
        "price_count": len(package.prices),
        "corporate_action_count": len(package.corporate_actions),
        "calendar_session_count": len(package.calendar),
    }
    row_count = (
        counts["ticker_vintage_count"]
        + counts["membership_count"]
        + counts["price_count"]
        + counts["corporate_action_count"]
        + counts["calendar_session_count"]
    )
    inventory_hash = fingerprint(counts)
    universe_count = len({item.universe_id for item in package.memberships})
    delisted_count = len(
        {item.permanent_security_id for item in package.securities if item.delisting_date}
    )
    material: dict[str, object] = {
        "dataset_id": package.dataset_id,
        "dataset_version": dataset_version,
        "schema_version": package.schema_version,
        "data_domain": output_domain,
        "use_scope": package.use_scope,
        "provider": package.provider,
        "source": package.source,
        "retrieved_at": package.retrieved_at,
        "as_of": package.as_of,
        "cutoff": package.cutoff,
        "required_start": required_start,
        "required_end": required_end,
        "date_start": date_start,
        "date_end": date_end,
        "row_count": row_count,
        **counts,
        "universe_count": universe_count,
        "delisted_count": delisted_count,
        "raw_price_certified": raw_price_certified,
        "total_return_certified": total_return_certified,
        "content_hash": content_hash,
        "inventory_hash": inventory_hash,
        "certification_state": state,
        "blockers": all_blockers,
    }
    manifest_hash = fingerprint(material)
    return ResearchDatasetManifestV2(
        dataset_id=package.dataset_id,
        dataset_version=dataset_version,
        schema_version=package.schema_version,
        data_domain=output_domain,
        use_scope=package.use_scope,
        production_eligible=(
            state is ResearchDatasetState.CERTIFIED
            and package.use_scope is ResearchUseScope.PRODUCTION_RESEARCH
        ),
        provider=package.provider,
        source=package.source,
        retrieved_at=package.retrieved_at,
        as_of=package.as_of,
        cutoff=package.cutoff,
        required_start=required_start,
        required_end=required_end,
        date_start=date_start,
        date_end=date_end,
        row_count=row_count,
        security_count=counts["security_count"],
        ticker_vintage_count=counts["ticker_vintage_count"],
        universe_count=universe_count,
        membership_count=counts["membership_count"],
        delisted_count=delisted_count,
        corporate_action_count=counts["corporate_action_count"],
        calendar_session_count=counts["calendar_session_count"],
        raw_price_certified=raw_price_certified,
        total_return_certified=total_return_certified,
        content_hash=content_hash,
        inventory_hash=inventory_hash,
        certification_state=state,
        blockers=all_blockers,
        manifest_hash=manifest_hash,
    )


def import_research_package(path: Path) -> ResearchDatasetPackage:
    """Import a long-form CSV/Parquet file or SQLite research package."""

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [cast(dict[str, object], dict(item)) for item in csv.DictReader(handle)]
    elif path.suffix.lower() in {".parquet", ".pq"}:
        import pandas as pd

        rows = cast(list[dict[str, object]], pd.read_parquet(path).to_dict("records"))
    elif path.suffix.lower() in {".sqlite", ".db"}:
        rows = _read_sqlite_rows(path)
    else:
        raise ValueError("research import supports CSV, Parquet or SQLite")
    if not rows:
        raise ValueError("research package contains no rows")
    return _package_from_rows(rows)


def package_to_import_rows(package: ResearchDatasetPackage) -> list[dict[str, object]]:
    """Render the documented long-form interchange schema deterministically."""

    common: dict[str, object] = {
        "dataset_id": package.dataset_id,
        "schema_version": package.schema_version,
        "dataset_provider": package.provider,
        "dataset_source": package.source,
        "retrieved_at": package.retrieved_at.isoformat(),
        "as_of": package.as_of.isoformat(),
        "cutoff": package.cutoff.isoformat(),
        "use_scope": package.use_scope.value,
    }
    groups: tuple[tuple[ResearchRecordType, Iterable[Any]], ...] = (
        (ResearchRecordType.SECURITY, package.securities),
        (ResearchRecordType.MEMBERSHIP, package.memberships),
        (ResearchRecordType.PRICE, package.prices),
        (ResearchRecordType.CORPORATE_ACTION, package.corporate_actions),
        (ResearchRecordType.CALENDAR, package.calendar),
    )
    rows: list[dict[str, object]] = []
    for record_type, records in groups:
        for record in records:
            payload = cast(
                dict[str, object],
                json.loads(json.dumps(asdict(record), default=str, sort_keys=True)),
            )
            rows.append({**common, **payload, "record_type": record_type.value})
    return rows


def persist_research_dataset(
    package: ResearchDatasetPackage,
    manifest: ResearchDatasetManifestV2,
    root: Path,
) -> Path:
    """Persist normalized rows and manifest immutably outside source control."""

    target = root / manifest.dataset_version
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    rows_path = target / "rows.jsonl"
    rendered_manifest = json.dumps(
        manifest.document(), ensure_ascii=False, indent=2, sort_keys=True
    )
    row_documents = package.content_document()
    rendered_rows = "\n".join(
        canonical_json({"record_type": key, "row": item})
        for key in sorted(row_documents)
        if key != "schema_version"
        for item in cast(list[object], row_documents[key])
    ) + "\n"
    _write_immutable(manifest_path, rendered_manifest)
    _write_immutable(rows_path, rendered_rows)
    return manifest_path


def latest_manifest(root: Path) -> Path | None:
    paths = list(root.glob("research-*/manifest.json")) if root.exists() else []
    return max(paths, key=lambda item: item.stat().st_mtime_ns) if paths else None


def load_persisted_research_dataset(manifest_path: Path) -> ResearchDatasetPackage:
    """Reload normalized rows and verify their content hash before re-certification."""

    manifest = cast(
        dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    group_types = {
        "securities": ResearchRecordType.SECURITY,
        "memberships": ResearchRecordType.MEMBERSHIP,
        "prices": ResearchRecordType.PRICE,
        "corporate_actions": ResearchRecordType.CORPORATE_ACTION,
        "calendar": ResearchRecordType.CALENDAR,
    }
    common: dict[str, object] = {
        "dataset_id": manifest["dataset_id"],
        "schema_version": manifest["schema_version"],
        "dataset_provider": manifest["provider"],
        "dataset_source": manifest["source"],
        "retrieved_at": manifest["retrieved_at"],
        "as_of": manifest["as_of"],
        "cutoff": manifest["cutoff"],
        "use_scope": manifest["use_scope"],
    }
    rows: list[dict[str, object]] = []
    rows_path = manifest_path.with_name("rows.jsonl")
    for line in rows_path.read_text(encoding="utf-8").splitlines():
        document = cast(dict[str, object], json.loads(line))
        group = str(document["record_type"])
        payload = cast(dict[str, object], document["row"])
        rows.append({**common, **payload, "record_type": group_types[group].value})
    package = _package_from_rows(rows)
    if package.content_hash != manifest.get("content_hash"):
        raise ValueError("persisted research dataset content hash mismatch")
    return package


def generate_xnys_sessions(
    start: date, end: date, *, available_at: datetime
) -> tuple[ExchangeSession, ...]:
    """Generate an auditable XNYS calendar from the installed rules package."""

    _require_aware(available_at, "calendar available_at")
    import importlib.metadata

    import exchange_calendars as xcals  # type: ignore[import-untyped]

    calendar = xcals.get_calendar("XNYS")
    version = importlib.metadata.version("exchange-calendars")
    sessions = calendar.sessions_in_range(start, end)
    output: list[ExchangeSession] = []
    for session in sessions:
        opened = calendar.session_open(session).to_pydatetime()
        closed = calendar.session_close(session).to_pydatetime()
        output.append(
            ExchangeSession(
                "XNYS",
                session.date(),
                opened,
                closed,
                (closed - opened).total_seconds() < 6.5 * 60 * 60,
                available_at,
                "installed exchange rules",
                f"exchange_calendars:{version}:XNYS",
            )
        )
    return tuple(output)


def _validate_ticker_vintages(
    records: tuple[HistoricalSecurity, ...], rejected: list[str]
) -> None:
    grouped: dict[str, list[HistoricalSecurity]] = {}
    for record in records:
        grouped.setdefault(record.permanent_security_id, []).append(record)
    for vintages in grouped.values():
        ordered = sorted(vintages, key=lambda item: item.ticker_valid_from)
        for left, right in zip(ordered, ordered[1:], strict=False):
            if left.ticker_valid_to is None or left.ticker_valid_to >= right.ticker_valid_from:
                rejected.append("TICKER_VINTAGE_OVERLAP")


def _validate_lifecycle(package: ResearchDatasetPackage, blockers: list[str]) -> None:
    delisted = {
        item.permanent_security_id
        for item in package.securities
        if item.delisting_date is not None
    }
    actions: dict[str, list[ResearchCorporateAction]] = {}
    for action in package.corporate_actions:
        actions.setdefault(action.permanent_security_id, []).append(action)
    for security_id in delisted:
        lifecycle = actions.get(security_id, [])
        terminal = [
            item
            for item in lifecycle
            if item.action_type in {"DELISTING", "MERGER", "ACQUISITION"}
        ]
        if not terminal:
            blockers.append("DELISTED_SECURITY_LIFECYCLE_INCOMPLETE")
        elif all(item.terminal_return is None for item in terminal):
            blockers.append("DELISTING_RETURN_UNAVAILABLE")
    last_session = max((item.session_date for item in package.calendar), default=None)
    if last_session is None:
        return
    prices_by_security: dict[str, list[ResearchPrice]] = {}
    for row in package.prices:
        prices_by_security.setdefault(row.permanent_security_id, []).append(row)
    for membership in package.memberships:
        security_prices = prices_by_security.get(membership.permanent_security_id, [])
        if not security_prices:
            blockers.append("MEMBER_PRICE_HISTORY_MISSING")
            continue
        if membership.effective_to is None or membership.effective_to >= last_session:
            last_price = max(
                (
                    item.observation_date
                    for item in security_prices
                ),
                default=None,
            )
            has_terminal = any(
                item.action_type in {"DELISTING", "MERGER", "ACQUISITION"}
                for item in actions.get(membership.permanent_security_id, [])
            )
            if last_price is not None and last_price < last_session and not has_terminal:
                blockers.append("MEMBER_PRICE_TERMINATES_WITHOUT_LIFECYCLE")


def _validate_calendar(
    rows: tuple[ExchangeSession, ...], blockers: list[str], rejected: list[str]
) -> bool:
    if not rows:
        return False
    dates = tuple(item.session_date for item in rows)
    if tuple(sorted(set(dates))) != dates:
        rejected.append("EXCHANGE_CALENDAR_DUPLICATE_OR_UNSORTED")
        return False
    expected = generate_xnys_sessions(dates[0], dates[-1], available_at=rows[0].available_at)
    expected_by_date = {item.session_date: item for item in expected}
    if set(dates) != set(expected_by_date):
        blockers.append("EXCHANGE_CALENDAR_INCOMPLETE")
        return False
    for row in rows:
        reference = expected_by_date[row.session_date]
        if (
            row.open_time != reference.open_time
            or row.close_time != reference.close_time
            or row.is_early_close != reference.is_early_close
        ):
            blockers.append("EXCHANGE_CALENDAR_SESSION_RULE_MISMATCH")
            return False
    return True


def _security_type_on(
    records: tuple[HistoricalSecurity, ...], permanent_security_id: str
) -> SecurityType | None:
    values = {
        item.security_type
        for item in records
        if item.permanent_security_id == permanent_security_id
    }
    return next(iter(values)) if len(values) == 1 else None


def _read_sqlite_rows(path: Path) -> list[dict[str, object]]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(item[0])
            for item in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "research_rows" in tables:
            return [dict(item) for item in connection.execute("SELECT * FROM research_rows")]
        mapping = {
            "securities": ResearchRecordType.SECURITY,
            "memberships": ResearchRecordType.MEMBERSHIP,
            "prices": ResearchRecordType.PRICE,
            "corporate_actions": ResearchRecordType.CORPORATE_ACTION,
            "calendar_sessions": ResearchRecordType.CALENDAR,
        }
        rows: list[dict[str, object]] = []
        for table, record_type in mapping.items():
            if table not in tables:
                continue
            for item in connection.execute(f"SELECT * FROM {table}"):
                document = dict(item)
                document["record_type"] = record_type.value
                rows.append(document)
        return rows


def _package_from_rows(rows: list[dict[str, object]]) -> ResearchDatasetPackage:
    first = rows[0]
    common: dict[str, object] = {
        "dataset_id": _required(first, "dataset_id"),
        "schema_version": _required(first, "schema_version"),
        "provider": _required(first, "dataset_provider"),
        "source": _required(first, "dataset_source"),
        "retrieved_at": _datetime(first, "retrieved_at"),
        "as_of": _date(first, "as_of"),
        "cutoff": _datetime(first, "cutoff"),
        "use_scope": ResearchUseScope(_required(first, "use_scope")),
    }
    common_keys = (
        "dataset_id", "schema_version", "dataset_provider", "dataset_source",
        "retrieved_at", "as_of", "cutoff", "use_scope",
    )
    for row in rows[1:]:
        for key in common_keys:
            if _required(row, key) != _required(first, key):
                raise ValueError(f"research package has mixed {key}")
    securities: list[HistoricalSecurity] = []
    memberships: list[HistoricalUniverseMembership] = []
    prices: list[ResearchPrice] = []
    actions: list[ResearchCorporateAction] = []
    calendar: list[ExchangeSession] = []
    for row in rows:
        record_type = ResearchRecordType(_required(row, "record_type"))
        source = _required(row, "source")
        provider = _required(row, "provider")
        if record_type is ResearchRecordType.SECURITY:
            securities.append(
                HistoricalSecurity(
                    _required(row, "permanent_security_id"),
                    _required(row, "ticker"),
                    _date(row, "ticker_valid_from"),
                    _optional_date(row, "ticker_valid_to"),
                    _required(row, "exchange"),
                    _optional_date(row, "listing_date"),
                    _optional_date(row, "delisting_date"),
                    _optional(row, "delisting_reason") or "UNKNOWN",
                    SecurityType(_required(row, "security_type")),
                    _datetime(row, "available_at"),
                    source,
                    provider,
                )
            )
        elif record_type is ResearchRecordType.MEMBERSHIP:
            memberships.append(
                HistoricalUniverseMembership(
                    _required(row, "permanent_security_id"),
                    _required(row, "universe_id"),
                    SecurityType(_required(row, "universe_type")),
                    _date(row, "effective_from"),
                    _optional_date(row, "effective_to"),
                    _datetime(row, "available_at"),
                    _datetime(row, "source_timestamp"),
                    _required(row, "membership_source_type"),
                    source,
                    provider,
                )
            )
        elif record_type is ResearchRecordType.PRICE:
            prices.append(
                ResearchPrice(
                    _required(row, "permanent_security_id"),
                    _required(row, "ticker"),
                    _date(row, "observation_date"),
                    _datetime(row, "available_at"),
                    _required(row, "exchange"),
                    _float(row, "open"),
                    _float(row, "high"),
                    _float(row, "low"),
                    _float(row, "close"),
                    _int(row, "volume"),
                    AdjustmentKind(_required(row, "adjustment_kind")),
                    _optional_float(row, "total_return_value"),
                    _optional_datetime(row, "total_return_available_at"),
                    _optional(row, "adjustment_vintage_id"),
                    source,
                    provider,
                )
            )
        elif record_type is ResearchRecordType.CORPORATE_ACTION:
            actions.append(
                ResearchCorporateAction(
                    _required(row, "permanent_security_id"),
                    _required(row, "action_type"),
                    _date(row, "effective_date"),
                    _optional_date(row, "announcement_date"),
                    _datetime(row, "available_at"),
                    source,
                    provider,
                    _optional_float(row, "ratio"),
                    _optional_float(row, "cash_amount"),
                    _optional_float(row, "terminal_return"),
                    _optional(row, "successor_security_id"),
                )
            )
        else:
            calendar.append(
                ExchangeSession(
                    _required(row, "calendar_id"),
                    _date(row, "session_date"),
                    _datetime(row, "open_time"),
                    _datetime(row, "close_time"),
                    _bool(row, "is_early_close"),
                    _datetime(row, "available_at"),
                    source,
                    provider,
                )
            )
    return ResearchDatasetPackage(
        dataset_id=cast(str, common["dataset_id"]),
        schema_version=cast(str, common["schema_version"]),
        provider=cast(str, common["provider"]),
        source=cast(str, common["source"]),
        retrieved_at=cast(datetime, common["retrieved_at"]),
        as_of=cast(date, common["as_of"]),
        cutoff=cast(datetime, common["cutoff"]),
        use_scope=cast(ResearchUseScope, common["use_scope"]),
        securities=tuple(securities),
        memberships=tuple(memberships),
        prices=tuple(
            sorted(prices, key=lambda item: (item.observation_date, item.permanent_security_id))
        ),
        corporate_actions=tuple(actions),
        calendar=tuple(sorted(calendar, key=lambda item: item.session_date)),
    )


def _sorted_documents(items: Iterable[Any]) -> list[dict[str, Any]]:
    documents = [asdict(item) for item in items]
    return sorted(documents, key=canonical_json)


def _require_lineage(*values: str) -> None:
    if any(
        not value.strip() or value.strip().upper() in {"UNKNOWN", "UNAVAILABLE"}
        for value in values
    ):
        raise ValueError("research evidence requires known identity and provenance")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")


def _required(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"research row is missing {key}")
    return str(value).strip()


def _optional(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    rendered = str(value).strip()
    return None if rendered in {"", "<NA>", "NaT", "nan"} else rendered


def _date(row: Mapping[str, object], key: str) -> date:
    return date.fromisoformat(_required(row, key))


def _optional_date(row: Mapping[str, object], key: str) -> date | None:
    value = _optional(row, key)
    return date.fromisoformat(value) if value else None


def _datetime(row: Mapping[str, object], key: str) -> datetime:
    value = datetime.fromisoformat(_required(row, key).replace("Z", "+00:00"))
    _require_aware(value, key)
    return value


def _optional_datetime(row: Mapping[str, object], key: str) -> datetime | None:
    return _datetime(row, key) if _optional(row, key) else None


def _float(row: Mapping[str, object], key: str) -> float:
    return float(_required(row, key))


def _optional_float(row: Mapping[str, object], key: str) -> float | None:
    return float(value) if (value := _optional(row, key)) else None


def _int(row: Mapping[str, object], key: str) -> int:
    value = float(_required(row, key))
    if not value.is_integer():
        raise ValueError(f"{key} must be an integer")
    return int(value)


def _bool(row: Mapping[str, object], key: str) -> bool:
    value = _required(row, key).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{key} must be boolean")
    return value in {"true", "1"}


def _write_immutable(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite immutable research data: {path}")
    path.write_text(content, encoding="utf-8")
