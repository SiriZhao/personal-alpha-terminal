"""ROUND80 Part 2 contracts for survivorship-safe research evidence.

The objects in this module are deliberately provider-neutral and side-effect
free.  They describe what a historical import must prove before it can become
research evidence; they do not turn the current operational Yahoo/Stooq cache
into certified PIT history.  The normal terminal fast-start path never imports
this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path

from personal_alpha_terminal.data.authority.contracts import (
    DataDomain,
    DataQualityStatus,
    ProviderMetadata,
)


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _nonblank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _hash(document: object) -> str:
    return sha256(
        json.dumps(document, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class HistoricalUniverseQualityStatus(StrEnum):
    """Quality of a historical universe import, not an investment outcome."""

    CERTIFIED = "CERTIFIED"
    RESEARCH_GRADE = "RESEARCH_GRADE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class ReturnSemantics(StrEnum):
    RAW_PRICE = "RAW_PRICE"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    POINT_IN_TIME_TOTAL_RETURN = "POINT_IN_TIME_TOTAL_RETURN"
    PROVIDER_ADJUSTED_UNVERIFIED = "PROVIDER_ADJUSTED_UNVERIFIED"


class TotalReturnReconciliationStatus(StrEnum):
    MATCH = "MATCH"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    MISSING_SECONDARY = "MISSING_SECONDARY"


class ExecutableOpenQualityStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class ProviderConflictResolution(StrEnum):
    AGREE = "AGREE"
    TOLERATED = "TOLERATED"
    PRIMARY_ACCEPTED_WITH_REASON = "PRIMARY_ACCEPTED_WITH_REASON"
    SECONDARY_ACCEPTED_WITH_REASON = "SECONDARY_ACCEPTED_WITH_REASON"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"


class ProviderOperationalStatus(StrEnum):
    """Runtime health classification separate from authority/certification."""

    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    SOURCE_ERROR = "SOURCE_ERROR"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class ProviderOperationalHealth:
    provider_id: str
    status: ProviderOperationalStatus
    reason: str
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        _nonblank(self.provider_id, "provider_id")
        _nonblank(self.reason, "reason")
        if self.checked_at is not None:
            object.__setattr__(self, "checked_at", _aware(self.checked_at, "checked_at"))


@dataclass(frozen=True, slots=True)
class PITUniverseCandidate:
    """Evidence required to decide if one security was investable at a cutoff."""

    security_id: str
    session_date: date
    known_at: datetime
    security_type: str
    listing_date: date | None
    delisting_date: date | None
    active: bool
    tradable: bool
    identity_resolved: bool
    raw_price: float | None
    average_dollar_volume: float | None
    observed_sessions: int
    lifecycle_evidence_complete: bool
    permanent_identifier_evidence_complete: bool
    historical_membership_evidence_complete: bool
    delisting_return_evidence_complete: bool
    source: str

    def __post_init__(self) -> None:
        _nonblank(self.security_id, "security_id")
        _nonblank(self.security_type, "security_type")
        _nonblank(self.source, "source")
        object.__setattr__(self, "known_at", _aware(self.known_at, "known_at"))
        if self.observed_sessions < 0:
            raise ValueError("observed_sessions cannot be negative")
        if self.listing_date is not None and self.listing_date > self.session_date:
            raise ValueError("listing_date cannot be after the investable session")
        if self.delisting_date is not None and self.delisting_date < self.session_date:
            raise ValueError("delisted security cannot be active after delisting")
        for field_name in ("raw_price", "average_dollar_volume"):
            value = getattr(self, field_name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PITInvestableUniverse:
    decision_timestamp: datetime
    session_date: date
    members: tuple[str, ...]
    exclusions: Mapping[str, tuple[str, ...]]
    quality_status: HistoricalUniverseQualityStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    universe_hash: str


def build_pit_investable_universe(
    candidates: Sequence[PITUniverseCandidate],
    *,
    decision_timestamp: datetime,
    minimum_price: float,
    minimum_average_dollar_volume: float,
    minimum_history_sessions: int,
    allowed_security_types: frozenset[str] = frozenset({"COMMON", "STOCK", "ETF"}),
) -> PITInvestableUniverse:
    """Build an as-of universe without looking at future lifecycle evidence.

    This is intentionally independent of index membership.  A strategy that
    trades a broad US universe must not silently become an S&P 500 backtest.
    """

    cutoff = _aware(decision_timestamp, "decision_timestamp")
    if minimum_price <= 0 or minimum_average_dollar_volume <= 0:
        raise ValueError("price and liquidity thresholds must be positive")
    if minimum_history_sessions < 1:
        raise ValueError("minimum_history_sessions must be positive")
    if not allowed_security_types:
        raise ValueError("allowed_security_types cannot be empty")
    seen: set[str] = set()
    members: list[str] = []
    exclusions: dict[str, tuple[str, ...]] = {}
    visible: list[PITUniverseCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.security_id):
        if candidate.security_id in seen:
            raise ValueError("historical universe contains duplicate security_id")
        seen.add(candidate.security_id)
        reasons: list[str] = []
        if candidate.known_at > cutoff:
            reasons.append("FUTURE_UNIVERSE_EVIDENCE")
        else:
            visible.append(candidate)
        if candidate.security_type.upper() not in allowed_security_types:
            reasons.append("UNSUPPORTED_SECURITY_TYPE")
        if not candidate.identity_resolved:
            reasons.append("UNRESOLVED_PERMANENT_IDENTITY")
        if not candidate.permanent_identifier_evidence_complete:
            reasons.append("PERMANENT_IDENTIFIER_EVIDENCE_INCOMPLETE")
        if not candidate.historical_membership_evidence_complete:
            reasons.append("HISTORICAL_MEMBERSHIP_EVIDENCE_INCOMPLETE")
        if not candidate.lifecycle_evidence_complete:
            reasons.append("LIFECYCLE_EVIDENCE_INCOMPLETE")
        if not candidate.delisting_return_evidence_complete:
            reasons.append("DELISTING_RETURN_EVIDENCE_INCOMPLETE")
        if not candidate.active:
            reasons.append("INACTIVE_SECURITY")
        if not candidate.tradable:
            reasons.append("NOT_TRADABLE_AT_DECISION")
        if candidate.raw_price is None or candidate.raw_price < minimum_price:
            reasons.append("PRICE_MISSING_OR_BELOW_THRESHOLD")
        if (
            candidate.average_dollar_volume is None
            or candidate.average_dollar_volume < minimum_average_dollar_volume
        ):
            reasons.append("LIQUIDITY_MISSING_OR_BELOW_THRESHOLD")
        if candidate.observed_sessions < minimum_history_sessions:
            reasons.append("INSUFFICIENT_HISTORY_AT_DECISION")
        if reasons:
            exclusions[candidate.security_id] = tuple(sorted(set(reasons)))
        else:
            members.append(candidate.security_id)

    evidence_blockers: list[str] = []
    evidence_warnings: list[str] = []
    if not visible:
        evidence_blockers.append("NO_PIT_UNIVERSE_OBSERVATIONS_VISIBLE")
    if visible and not all(item.permanent_identifier_evidence_complete for item in visible):
        evidence_blockers.append("PERMANENT_IDENTIFIER_HISTORY_INCOMPLETE")
    if visible and not all(item.historical_membership_evidence_complete for item in visible):
        evidence_blockers.append("HISTORICAL_UNIVERSE_MEMBERSHIP_INCOMPLETE")
    if visible and not all(item.lifecycle_evidence_complete for item in visible):
        evidence_blockers.append("LIFECYCLE_EVIDENCE_INCOMPLETE")
    if visible and not all(item.delisting_return_evidence_complete for item in visible):
        evidence_blockers.append("DELISTING_RETURN_EVIDENCE_INCOMPLETE")
    if not members and visible:
        evidence_warnings.append("NO_ELIGIBLE_SECURITIES_AFTER_LEGAL_FILTERS")
    if evidence_blockers:
        status = (
            HistoricalUniverseQualityStatus.PARTIAL
            if visible
            else HistoricalUniverseQualityStatus.BLOCKED
        )
    elif members:
        status = HistoricalUniverseQualityStatus.CERTIFIED
    else:
        status = HistoricalUniverseQualityStatus.RESEARCH_GRADE
    session_date = max((item.session_date for item in candidates), default=cutoff.date())
    document = {
        "decision_timestamp": cutoff.isoformat(),
        "session_date": session_date.isoformat(),
        "members": members,
        "exclusions": exclusions,
        "quality_status": status.value,
        "blockers": evidence_blockers,
        "warnings": evidence_warnings,
    }
    return PITInvestableUniverse(
        decision_timestamp=cutoff,
        session_date=session_date,
        members=tuple(members),
        exclusions=exclusions,
        quality_status=status,
        blockers=tuple(evidence_blockers),
        warnings=tuple(evidence_warnings),
        universe_hash=_hash(document),
    )


@dataclass(frozen=True, slots=True)
class HistoricalIndexConstituent:
    """Time-bounded constituent evidence for research metadata only."""

    index_id: str
    security_id: str
    effective_from: date
    effective_to: date | None
    announcement_time: datetime | None
    known_at: datetime
    source: str
    source_record_id: str
    confidence: float

    def __post_init__(self) -> None:
        for field_name in ("index_id", "security_id", "source", "source_record_id"):
            _nonblank(str(getattr(self, field_name)), field_name)
        if self.index_id not in {"SP500", "NASDAQ100"}:
            raise ValueError("index_id must be SP500 or NASDAQ100")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("constituent effective_to cannot precede effective_from")
        known = _aware(self.known_at, "known_at")
        announcement = (
            _aware(self.announcement_time, "announcement_time")
            if self.announcement_time is not None
            else None
        )
        if announcement is not None and announcement > known:
            raise ValueError("announcement_time cannot be after known_at")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("constituent confidence must be between zero and one")
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "announcement_time", announcement)


def index_constituents_visible_at(
    records: Sequence[HistoricalIndexConstituent],
    *,
    index_id: str,
    session_date: date,
    decision_timestamp: datetime,
) -> tuple[str, ...]:
    """Return only records effective and known by the historical cutoff."""

    cutoff = _aware(decision_timestamp, "decision_timestamp")
    return tuple(
        sorted(
            {
                item.security_id
                for item in records
                if item.index_id == index_id
                and item.known_at <= cutoff
                and item.effective_from <= session_date
                and (item.effective_to is None or session_date <= item.effective_to)
            }
        )
    )


@dataclass(frozen=True, slots=True)
class CanonicalCorporateAction:
    """PIT-safe corporate action that remains separate from price bars."""

    action_id: str
    revision_id: str
    security_id: str
    action_type: str
    announcement_time: datetime | None
    ex_date: date | None
    record_date: date | None
    pay_date: date | None
    effective_date: date
    cash_amount: float | None
    ratio: float | None
    currency: str | None
    known_at: datetime
    fetched_at: datetime
    source: str
    source_record_id: str
    confidence: float

    def __post_init__(self) -> None:
        for field_name in (
            "action_id",
            "revision_id",
            "security_id",
            "action_type",
            "source",
            "source_record_id",
        ):
            _nonblank(str(getattr(self, field_name)), field_name)
        known = _aware(self.known_at, "known_at")
        fetched = _aware(self.fetched_at, "fetched_at")
        announcement = (
            _aware(self.announcement_time, "announcement_time")
            if self.announcement_time is not None
            else None
        )
        if announcement is not None and announcement > known:
            raise ValueError("corporate action announcement cannot be after known_at")
        if known > fetched:
            raise ValueError("corporate action known_at cannot be after fetched_at")
        if (
            self.ex_date is not None
            and self.record_date is not None
            and self.record_date < self.ex_date
        ):
            raise ValueError("record_date cannot precede ex_date")
        if self.pay_date is not None and self.ex_date is not None and self.pay_date < self.ex_date:
            raise ValueError("pay_date cannot precede ex_date")
        for field_name in ("cash_amount", "ratio"):
            value = getattr(self, field_name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be finite and nonnegative")
        if self.action_type in {"split", "reverse_split", "stock_dividend"} and (
            self.ratio is None or self.ratio <= 0
        ):
            raise ValueError("share-changing action requires a positive ratio")
        if self.action_type == "cash_dividend" and self.cash_amount is None:
            raise ValueError("cash dividend requires cash_amount")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("corporate action confidence must be between zero and one")
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "fetched_at", fetched)
        object.__setattr__(self, "announcement_time", announcement)


def corporate_actions_visible_at(
    actions: Sequence[CanonicalCorporateAction], *, decision_timestamp: datetime
) -> tuple[CanonicalCorporateAction, ...]:
    cutoff = _aware(decision_timestamp, "decision_timestamp")
    return tuple(
        sorted(
            (item for item in actions if item.known_at <= cutoff),
            key=lambda item: (item.effective_date, item.known_at, item.action_id, item.revision_id),
        )
    )


@dataclass(frozen=True, slots=True)
class TotalReturnObservation:
    session_date: date
    total_return_index: float
    known_at: datetime
    source: str
    semantics: ReturnSemantics

    def __post_init__(self) -> None:
        _nonblank(self.source, "source")
        if not isfinite(self.total_return_index) or self.total_return_index <= 0:
            raise ValueError("total_return_index must be finite and positive")
        object.__setattr__(self, "known_at", _aware(self.known_at, "known_at"))


@dataclass(frozen=True, slots=True)
class TotalReturnReconciliation:
    security_id: str
    status: TotalReturnReconciliationStatus
    compared_sessions: int
    maximum_difference_bps: float | None
    tolerance_bps: float
    blockers: tuple[str, ...]
    primary_source: str
    secondary_source: str | None


def reconcile_total_return(
    *,
    security_id: str,
    primary: Sequence[TotalReturnObservation],
    secondary: Sequence[TotalReturnObservation],
    decision_timestamp: datetime,
    tolerance_bps: float = 5.0,
) -> TotalReturnReconciliation:
    """Cross-check a reconstructed PIT total-return index without picking winners."""

    _nonblank(security_id, "security_id")
    cutoff = _aware(decision_timestamp, "decision_timestamp")
    if tolerance_bps < 0 or not isfinite(tolerance_bps):
        raise ValueError("tolerance_bps must be finite and nonnegative")
    first = {item.session_date: item for item in primary if item.known_at <= cutoff}
    second = {item.session_date: item for item in secondary if item.known_at <= cutoff}
    primary_source = primary[0].source if primary else "UNAVAILABLE"
    secondary_source = secondary[0].source if secondary else None
    if not second:
        return TotalReturnReconciliation(
            security_id,
            TotalReturnReconciliationStatus.MISSING_SECONDARY,
            0,
            None,
            tolerance_bps,
            ("SECONDARY_TOTAL_RETURN_SERIES_MISSING",),
            primary_source,
            None,
        )
    common = sorted(set(first) & set(second))
    if not common:
        return TotalReturnReconciliation(
            security_id,
            TotalReturnReconciliationStatus.MATERIAL_CONFLICT,
            0,
            None,
            tolerance_bps,
            ("TOTAL_RETURN_SESSION_OVERLAP_MISSING",),
            primary_source,
            secondary_source,
        )
    differences = [
        abs(first[item].total_return_index / second[item].total_return_index - 1.0) * 10_000
        for item in common
    ]
    maximum = max(differences)
    status = (
        TotalReturnReconciliationStatus.MATCH
        if maximum == 0
        else TotalReturnReconciliationStatus.WITHIN_TOLERANCE
        if maximum <= tolerance_bps
        else TotalReturnReconciliationStatus.MATERIAL_CONFLICT
    )
    blockers = (
        ("TOTAL_RETURN_MATERIAL_PROVIDER_CONFLICT",)
        if status is TotalReturnReconciliationStatus.MATERIAL_CONFLICT
        else ()
    )
    return TotalReturnReconciliation(
        security_id,
        status,
        len(common),
        maximum,
        tolerance_bps,
        blockers,
        primary_source,
        secondary_source,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    benchmark_id: str
    session_dates: tuple[date, ...]
    semantics: ReturnSemantics
    known_at: datetime
    source: str
    market_timezone: str
    data_cutoff: datetime

    def __post_init__(self) -> None:
        _nonblank(self.benchmark_id, "benchmark_id")
        _nonblank(self.source, "source")
        _nonblank(self.market_timezone, "market_timezone")
        if not self.session_dates:
            raise ValueError("benchmark session_dates cannot be empty")
        if tuple(sorted(set(self.session_dates))) != self.session_dates:
            raise ValueError("benchmark session_dates must be sorted and unique")
        known = _aware(self.known_at, "known_at")
        cutoff = _aware(self.data_cutoff, "data_cutoff")
        if known > cutoff:
            raise ValueError("benchmark known_at cannot be after data_cutoff")
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "data_cutoff", cutoff)


@dataclass(frozen=True, slots=True)
class BenchmarkAlignmentAudit:
    status: DataQualityStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    benchmark_id: str


def audit_benchmark_alignment(
    *,
    strategy_semantics: ReturnSemantics,
    strategy_sessions: Sequence[date],
    strategy_cutoff: datetime,
    benchmark: BenchmarkEvidence | None,
) -> BenchmarkAlignmentAudit:
    """Prevent raw-price benchmark comparisons against strategy total returns."""

    cutoff = _aware(strategy_cutoff, "strategy_cutoff")
    blockers: list[str] = []
    warnings: list[str] = []
    if benchmark is None:
        return BenchmarkAlignmentAudit(
            DataQualityStatus.BLOCKED_WITH_EVIDENCE,
            ("BENCHMARK_EVIDENCE_MISSING",),
            (),
            "UNAVAILABLE",
        )
    if benchmark.semantics is not strategy_semantics:
        blockers.append("BENCHMARK_RETURN_SEMANTICS_MISMATCH")
    if benchmark.known_at > cutoff or benchmark.data_cutoff > cutoff:
        blockers.append("BENCHMARK_FUTURE_AVAILABILITY")
    missing_sessions = set(strategy_sessions) - set(benchmark.session_dates)
    if missing_sessions:
        blockers.append("BENCHMARK_SESSION_ALIGNMENT_INCOMPLETE")
    if strategy_semantics is ReturnSemantics.PROVIDER_ADJUSTED_UNVERIFIED:
        warnings.append("STRATEGY_RETURN_SEMANTICS_NOT_PIT_CERTIFIED")
    return BenchmarkAlignmentAudit(
        (
            DataQualityStatus.PASS_WITH_WARNINGS
            if not blockers
            else DataQualityStatus.BLOCKED_WITH_EVIDENCE
        ),
        tuple(blockers),
        tuple(warnings),
        benchmark.benchmark_id,
    )


@dataclass(frozen=True, slots=True)
class MacroVintageObservation:
    series_id: str
    observation_date: date
    value: float
    vintage_date: date
    release_timestamp: datetime | None
    known_at: datetime
    source: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        _nonblank(self.series_id, "series_id")
        _nonblank(self.source, "source")
        if not isfinite(self.value):
            raise ValueError("macro value must be finite")
        release = (
            _aware(self.release_timestamp, "release_timestamp")
            if self.release_timestamp is not None
            else None
        )
        known = _aware(self.known_at, "known_at")
        fetched = _aware(self.fetched_at, "fetched_at")
        if release is not None and release > known:
            raise ValueError("macro release_timestamp cannot be after known_at")
        if known > fetched:
            raise ValueError("macro known_at cannot be after fetched_at")
        object.__setattr__(self, "release_timestamp", release)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "fetched_at", fetched)


def macro_vintages_visible_at(
    observations: Sequence[MacroVintageObservation], *, decision_timestamp: datetime
) -> tuple[MacroVintageObservation, ...]:
    cutoff = _aware(decision_timestamp, "decision_timestamp")
    selected: dict[tuple[str, date], MacroVintageObservation] = {}
    for observation in observations:
        if observation.known_at > cutoff:
            continue
        key = (observation.series_id, observation.observation_date)
        current = selected.get(key)
        if current is None or (observation.known_at, observation.vintage_date) > (
            current.known_at,
            current.vintage_date,
        ):
            selected[key] = observation
    return tuple(
        sorted(selected.values(), key=lambda item: (item.series_id, item.observation_date))
    )


@dataclass(frozen=True, slots=True)
class ExecutableNextSessionOpen:
    security_id: str
    signal_timestamp: datetime
    decision_timestamp: datetime
    market_timezone: str
    next_session_date: date
    execution_price_type: str
    open_timestamp: datetime | None
    raw_open: float | None
    volume: int | None
    provider: str
    feed: str
    adjustment_semantics: str
    fetched_at: datetime
    halted_or_nontradable: bool
    symbol_transition_resolved: bool
    benchmark_session_aligned: bool

    def __post_init__(self) -> None:
        for field_name in (
            "security_id",
            "market_timezone",
            "execution_price_type",
            "provider",
            "feed",
            "adjustment_semantics",
        ):
            _nonblank(str(getattr(self, field_name)), field_name)
        signal = _aware(self.signal_timestamp, "signal_timestamp")
        decision = _aware(self.decision_timestamp, "decision_timestamp")
        fetched = _aware(self.fetched_at, "fetched_at")
        if signal > decision:
            raise ValueError("signal_timestamp cannot be after decision_timestamp")
        if decision > fetched:
            raise ValueError("decision_timestamp cannot be after fetched_at")
        if self.raw_open is not None and (not isfinite(self.raw_open) or self.raw_open <= 0):
            raise ValueError("raw_open must be finite and positive when provided")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")
        open_timestamp = (
            _aware(self.open_timestamp, "open_timestamp")
            if self.open_timestamp is not None
            else None
        )
        object.__setattr__(self, "signal_timestamp", signal)
        object.__setattr__(self, "decision_timestamp", decision)
        object.__setattr__(self, "fetched_at", fetched)
        object.__setattr__(self, "open_timestamp", open_timestamp)


def audit_executable_next_session_open(
    evidence: ExecutableNextSessionOpen,
    *,
    expected_next_session_date: date,
    require_positive_volume: bool = True,
) -> tuple[ExecutableOpenQualityStatus, tuple[str, ...]]:
    """Reject same-session/impossible fills and incomplete tradability evidence."""

    blockers: list[str] = []
    if evidence.next_session_date != expected_next_session_date:
        blockers.append("NEXT_LEGAL_SESSION_MISMATCH")
    if evidence.open_timestamp is None:
        blockers.append("EXECUTABLE_OPEN_TIMESTAMP_MISSING")
    elif evidence.open_timestamp <= evidence.decision_timestamp:
        blockers.append("SAME_SESSION_OR_PRE_DECISION_OPEN")
    if evidence.raw_open is None or evidence.raw_open <= 0:
        blockers.append("EXECUTABLE_RAW_OPEN_MISSING_OR_INVALID")
    if require_positive_volume and (evidence.volume is None or evidence.volume <= 0):
        blockers.append("EXECUTABLE_VOLUME_MISSING_OR_INVALID")
    if evidence.halted_or_nontradable:
        blockers.append("KNOWN_HALT_OR_NONTRADABLE")
    if not evidence.symbol_transition_resolved:
        blockers.append("UNRESOLVED_SYMBOL_TRANSITION")
    if not evidence.benchmark_session_aligned:
        blockers.append("BENCHMARK_SESSION_MISMATCH")
    return (
        ExecutableOpenQualityStatus.PASS if not blockers else ExecutableOpenQualityStatus.BLOCKED,
        tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class ProviderValueConflict:
    domain: DataDomain
    entity_id: str
    effective_at: datetime
    provider_a: str
    provider_b: str
    value_a: float | str
    value_b: float | str
    tolerance: float
    resolution: ProviderConflictResolution
    resolved_provider: str | None
    reason: str
    quality_status: DataQualityStatus

    def __post_init__(self) -> None:
        for field_name in ("entity_id", "provider_a", "provider_b", "reason"):
            _nonblank(str(getattr(self, field_name)), field_name)
        if self.provider_a == self.provider_b:
            raise ValueError("provider conflict requires two distinct providers")
        if self.tolerance < 0 or not isfinite(self.tolerance):
            raise ValueError("tolerance must be finite and nonnegative")
        effective = _aware(self.effective_at, "effective_at")
        if self.resolution is ProviderConflictResolution.UNRESOLVED_CONFLICT and (
            self.quality_status is not DataQualityStatus.BLOCKED_WITH_EVIDENCE
        ):
            raise ValueError("unresolved conflict must propagate BLOCKED_WITH_EVIDENCE")
        if self.resolved_provider is not None and self.resolved_provider not in {
            self.provider_a,
            self.provider_b,
        }:
            raise ValueError("resolved_provider must be one of the compared providers")
        object.__setattr__(self, "effective_at", effective)


@dataclass(frozen=True, slots=True)
class ImmutableRawFetchEvidence:
    """A content-addressed fetch receipt; it does not store redundant payloads."""

    fetch_id: str
    provider_id: str
    domain: DataDomain
    logical_endpoint: str
    parameters: Mapping[str, object]
    requested_at: datetime
    received_at: datetime
    content_hash: str
    schema_version: str
    normalization_version: str
    source_timestamp: datetime | None
    snapshot_identity: str
    storage_reference: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "fetch_id",
            "provider_id",
            "logical_endpoint",
            "content_hash",
            "schema_version",
            "normalization_version",
            "snapshot_identity",
        ):
            _nonblank(str(getattr(self, field_name)), field_name)
        requested = _aware(self.requested_at, "requested_at")
        received = _aware(self.received_at, "received_at")
        source_timestamp = (
            _aware(self.source_timestamp, "source_timestamp")
            if self.source_timestamp is not None
            else None
        )
        if received < requested:
            raise ValueError("received_at cannot precede requested_at")
        object.__setattr__(self, "requested_at", requested)
        object.__setattr__(self, "received_at", received)
        object.__setattr__(self, "source_timestamp", source_timestamp)
        object.__setattr__(self, "parameters", dict(self.parameters))

    @property
    def immutable_identity(self) -> str:
        return _hash(
            {
                "provider_id": self.provider_id,
                "domain": self.domain.value,
                "logical_endpoint": self.logical_endpoint,
                "parameters": self.parameters,
                "content_hash": self.content_hash,
                "schema_version": self.schema_version,
                "normalization_version": self.normalization_version,
                "snapshot_identity": self.snapshot_identity,
            }
        )


@dataclass(frozen=True, slots=True)
class ResearchDatasetSnapshot:
    """Immutable identity for an import/replay dataset, not a mutable cache key."""

    snapshot_id: str
    created_at: datetime
    data_cutoff: datetime
    provider_versions: Mapping[str, str]
    raw_hashes: Mapping[str, str]
    normalized_dataset_hashes: Mapping[str, str]
    security_master_hash: str
    corporate_action_hash: str
    benchmark_hash: str
    fundamental_hash: str
    universe_hash: str
    schema_version: str
    normalization_version: str
    git_sha: str
    manifest_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "security_master_hash",
            "corporate_action_hash",
            "benchmark_hash",
            "fundamental_hash",
            "universe_hash",
            "schema_version",
            "normalization_version",
            "git_sha",
        ):
            _nonblank(str(getattr(self, field_name)), field_name)
        created = _aware(self.created_at, "created_at")
        cutoff = _aware(self.data_cutoff, "data_cutoff")
        if cutoff > created:
            raise ValueError("dataset data_cutoff cannot be after snapshot creation")
        if not self.provider_versions or not self.raw_hashes or not self.normalized_dataset_hashes:
            raise ValueError("dataset snapshot requires provider, raw, and normalized hashes")
        expected = dataset_snapshot_hash(self)
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("dataset snapshot manifest hash is invalid")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "data_cutoff", cutoff)
        object.__setattr__(self, "provider_versions", dict(self.provider_versions))
        object.__setattr__(self, "raw_hashes", dict(self.raw_hashes))
        object.__setattr__(self, "normalized_dataset_hashes", dict(self.normalized_dataset_hashes))

    def document(self) -> dict[str, object]:
        document = asdict(self)
        document["created_at"] = self.created_at.isoformat()
        document["data_cutoff"] = self.data_cutoff.isoformat()
        return document


def dataset_snapshot_hash(snapshot: ResearchDatasetSnapshot) -> str:
    """Hash stable content while avoiding recursive inclusion of manifest_hash."""

    return _hash(
        {
            "snapshot_id": snapshot.snapshot_id,
            "created_at": snapshot.created_at,
            "data_cutoff": snapshot.data_cutoff,
            "provider_versions": snapshot.provider_versions,
            "raw_hashes": snapshot.raw_hashes,
            "normalized_dataset_hashes": snapshot.normalized_dataset_hashes,
            "security_master_hash": snapshot.security_master_hash,
            "corporate_action_hash": snapshot.corporate_action_hash,
            "benchmark_hash": snapshot.benchmark_hash,
            "fundamental_hash": snapshot.fundamental_hash,
            "universe_hash": snapshot.universe_hash,
            "schema_version": snapshot.schema_version,
            "normalization_version": snapshot.normalization_version,
            "git_sha": snapshot.git_sha,
        }
    )


def create_dataset_snapshot(
    *,
    created_at: datetime,
    data_cutoff: datetime,
    provider_versions: Mapping[str, str],
    raw_hashes: Mapping[str, str],
    normalized_dataset_hashes: Mapping[str, str],
    security_master_hash: str,
    corporate_action_hash: str,
    benchmark_hash: str,
    fundamental_hash: str,
    universe_hash: str,
    schema_version: str,
    normalization_version: str,
    git_sha: str,
) -> ResearchDatasetSnapshot:
    identity = _hash(
        {
            "data_cutoff": _aware(data_cutoff, "data_cutoff"),
            "provider_versions": dict(provider_versions),
            "raw_hashes": dict(raw_hashes),
            "normalized_dataset_hashes": dict(normalized_dataset_hashes),
            "security_master_hash": security_master_hash,
            "corporate_action_hash": corporate_action_hash,
            "benchmark_hash": benchmark_hash,
            "fundamental_hash": fundamental_hash,
            "universe_hash": universe_hash,
            "schema_version": schema_version,
            "normalization_version": normalization_version,
            "git_sha": git_sha,
        }
    )
    base = ResearchDatasetSnapshot(
        snapshot_id=f"ROUND80-{identity}",
        created_at=created_at,
        data_cutoff=data_cutoff,
        provider_versions=provider_versions,
        raw_hashes=raw_hashes,
        normalized_dataset_hashes=normalized_dataset_hashes,
        security_master_hash=security_master_hash,
        corporate_action_hash=corporate_action_hash,
        benchmark_hash=benchmark_hash,
        fundamental_hash=fundamental_hash,
        universe_hash=universe_hash,
        schema_version=schema_version,
        normalization_version=normalization_version,
        git_sha=git_sha,
        manifest_hash="",
    )
    return ResearchDatasetSnapshot(
        snapshot_id=base.snapshot_id,
        created_at=base.created_at,
        data_cutoff=base.data_cutoff,
        provider_versions=base.provider_versions,
        raw_hashes=base.raw_hashes,
        normalized_dataset_hashes=base.normalized_dataset_hashes,
        security_master_hash=base.security_master_hash,
        corporate_action_hash=base.corporate_action_hash,
        benchmark_hash=base.benchmark_hash,
        fundamental_hash=base.fundamental_hash,
        universe_hash=base.universe_hash,
        schema_version=base.schema_version,
        normalization_version=base.normalization_version,
        git_sha=base.git_sha,
        manifest_hash=dataset_snapshot_hash(base),
    )


def persist_dataset_snapshot(path: Path, snapshot: ResearchDatasetSnapshot) -> None:
    """Write a snapshot manifest once; history is never overwritten in place."""

    if not snapshot.manifest_hash or snapshot.manifest_hash != dataset_snapshot_hash(snapshot):
        raise ValueError("dataset snapshot must have a valid manifest hash")
    if path.exists():
        raise FileExistsError(f"dataset snapshot already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class DomainDataQualityAudit:
    domain: DataDomain
    coverage_start: date | None
    coverage_end: date | None
    entity_count: int
    observation_count: int
    missing_rate: float | None
    duplicate_rate: float | None
    conflict_rate: float | None
    pit_status: DataQualityStatus
    survivorship_status: HistoricalUniverseQualityStatus | None
    authority_status: DataQualityStatus
    last_refresh: datetime | None
    provider_mix: tuple[str, ...]
    ticker_history_coverage: float | None = None
    listing_coverage: float | None = None
    delisting_coverage: float | None = None
    corporate_action_coverage: float | None = None
    unresolved_identity_count: int | None = None

    def __post_init__(self) -> None:
        if self.coverage_start is not None and self.coverage_end is not None:
            if self.coverage_start > self.coverage_end:
                raise ValueError("coverage_start cannot follow coverage_end")
        if self.entity_count < 0 or self.observation_count < 0:
            raise ValueError("audit counts cannot be negative")
        if self.unresolved_identity_count is not None and self.unresolved_identity_count < 0:
            raise ValueError("unresolved_identity_count cannot be negative")
        for field_name in (
            "missing_rate",
            "duplicate_rate",
            "conflict_rate",
            "ticker_history_coverage",
            "listing_coverage",
            "delisting_coverage",
            "corporate_action_coverage",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{field_name} must be between zero and one")
        if self.last_refresh is not None:
            object.__setattr__(self, "last_refresh", _aware(self.last_refresh, "last_refresh"))
        if tuple(sorted(set(self.provider_mix))) != self.provider_mix:
            raise ValueError("provider_mix must be sorted and unique")

    def document(self) -> dict[str, object]:
        return {
            "domain": self.domain.value,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "entity_count": self.entity_count,
            "observation_count": self.observation_count,
            "missing_rate": self.missing_rate,
            "duplicate_rate": self.duplicate_rate,
            "conflict_rate": self.conflict_rate,
            "pit_status": self.pit_status.value,
            "survivorship_status": (
                self.survivorship_status.value if self.survivorship_status else None
            ),
            "authority_status": self.authority_status.value,
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "provider_mix": list(self.provider_mix),
            "ticker_history_coverage": self.ticker_history_coverage,
            "listing_coverage": self.listing_coverage,
            "delisting_coverage": self.delisting_coverage,
            "corporate_action_coverage": self.corporate_action_coverage,
            "unresolved_identity_count": self.unresolved_identity_count,
        }


def declared_domain_audits(
    providers: Sequence[ProviderMetadata],
) -> tuple[DomainDataQualityAudit, ...]:
    """Report declared source posture honestly until an imported package is audited."""

    audits: list[DomainDataQualityAudit] = []
    for domain in DataDomain:
        matching = tuple(
            sorted(item.provider_id for item in providers if domain in item.data_domains)
        )
        enabled = tuple(
            item
            for item in providers
            if domain in item.data_domains and item.enabled
        )
        authority = (
            DataQualityStatus.PARTIAL
            if enabled
            else DataQualityStatus.BLOCKED_WITH_EVIDENCE
        )
        pit = (
            DataQualityStatus.RESEARCH_GRADE
            if any(item.pit_capable for item in enabled)
            else DataQualityStatus.BLOCKED_WITH_EVIDENCE
        )
        audits.append(
            DomainDataQualityAudit(
                domain=domain,
                coverage_start=None,
                coverage_end=None,
                entity_count=0,
                observation_count=0,
                missing_rate=None,
                duplicate_rate=None,
                conflict_rate=None,
                pit_status=pit,
                survivorship_status=(
                    HistoricalUniverseQualityStatus.BLOCKED
                    if domain in {DataDomain.UNIVERSE_MEMBERSHIP, DataDomain.SECURITY_LIFECYCLE}
                    else None
                ),
                authority_status=authority,
                last_refresh=None,
                provider_mix=matching,
                ticker_history_coverage=(0.0 if domain is DataDomain.SECURITY_IDENTITY else None),
                listing_coverage=(0.0 if domain is DataDomain.SECURITY_LIFECYCLE else None),
                delisting_coverage=(0.0 if domain is DataDomain.SECURITY_LIFECYCLE else None),
                corporate_action_coverage=(
                    0.0 if domain is DataDomain.CORPORATE_ACTIONS else None
                ),
                unresolved_identity_count=(0 if domain is DataDomain.SECURITY_IDENTITY else None),
            )
        )
    return tuple(audits)


def declared_provider_health(
    providers: Sequence[ProviderMetadata],
) -> tuple[ProviderOperationalHealth, ...]:
    """Safe local posture: no CLI status command performs a provider probe."""

    health: list[ProviderOperationalHealth] = []
    for provider in sorted(providers, key=lambda item: item.provider_id):
        if not provider.enabled:
            status = (
                ProviderOperationalStatus.AUTH_REQUIRED
                if provider.credential_required
                else ProviderOperationalStatus.DISABLED
            )
            reason = "configured adapter is disabled; no network call was attempted"
        else:
            status = ProviderOperationalStatus.DEGRADED
            reason = (
                "declared local adapter only; live availability and PIT coverage are "
                "unverified in this status command"
            )
        health.append(ProviderOperationalHealth(provider.provider_id, status, reason))
    return tuple(health)


@dataclass(frozen=True, slots=True)
class ProductionAuthorityGate:
    provider_id: str
    domain: DataDomain
    status: DataQualityStatus
    blockers: tuple[str, ...]
    promotion_allowed: bool


def evaluate_production_authority_gate(
    *,
    provider: ProviderMetadata,
    audit: DomainDataQualityAudit,
    reconciliation: TotalReturnReconciliation | None = None,
) -> ProductionAuthorityGate:
    """A working adapter remains research-only until every evidence gate passes."""

    blockers: list[str] = []
    if audit.domain not in provider.data_domains:
        blockers.append("PROVIDER_DOMAIN_MISMATCH")
    if not provider.enabled:
        blockers.append("PROVIDER_DISABLED")
    if not provider.pit_capable:
        blockers.append("PROVIDER_NOT_PIT_CAPABLE")
    if audit.authority_status not in {DataQualityStatus.PASS, DataQualityStatus.PASS_WITH_WARNINGS}:
        blockers.append("AUTHORITY_AUDIT_NOT_CERTIFIED")
    if audit.pit_status not in {DataQualityStatus.PASS, DataQualityStatus.PASS_WITH_WARNINGS}:
        blockers.append("PIT_AUDIT_NOT_CERTIFIED")
    if audit.domain in {DataDomain.UNIVERSE_MEMBERSHIP, DataDomain.SECURITY_LIFECYCLE} and (
        audit.survivorship_status is not HistoricalUniverseQualityStatus.CERTIFIED
    ):
        blockers.append("SURVIVORSHIP_AUDIT_NOT_CERTIFIED")
    if reconciliation is not None and (
        reconciliation.status is TotalReturnReconciliationStatus.MATERIAL_CONFLICT
    ):
        blockers.append("UNRESOLVED_CROSS_PROVIDER_CONFLICT")
    return ProductionAuthorityGate(
        provider.provider_id,
        audit.domain,
        DataQualityStatus.PASS if not blockers else DataQualityStatus.BLOCKED_WITH_EVIDENCE,
        tuple(blockers),
        not blockers,
    )
