"""Immutable, provider-independent evidence contracts for data authority.

The contracts keep retrieval time separate from decision-time availability.
They are intentionally independent of SQLAlchemy and provider SDKs so the
terminal fast-start path never imports remote clients or historical datasets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol


class DataDomain(StrEnum):
    """Evidence domains that may have different authoritative providers."""

    MARKET_PRICES = "MARKET_PRICES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    TOTAL_RETURN = "TOTAL_RETURN"
    ISSUER_IDENTITY = "ISSUER_IDENTITY"
    SECURITY_IDENTITY = "SECURITY_IDENTITY"
    SECURITY_LIFECYCLE = "SECURITY_LIFECYCLE"
    UNIVERSE_MEMBERSHIP = "UNIVERSE_MEMBERSHIP"
    BENCHMARK = "BENCHMARK"
    FUNDAMENTALS = "FUNDAMENTALS"
    FILINGS = "FILINGS"
    NEWS_EVENTS = "NEWS_EVENTS"
    EXECUTABLE_OPENS = "EXECUTABLE_OPENS"
    MACRO_RISK_FREE = "MACRO_RISK_FREE"


class AuthorityTier(StrEnum):
    """Strength of a source's authority, not a certification verdict."""

    OFFICIAL = "OFFICIAL"
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CROSS_CHECK = "CROSS_CHECK"
    OPTIONAL = "OPTIONAL"


class ProviderRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CROSS_CHECK = "CROSS_CHECK"
    OPTIONAL = "OPTIONAL"


class DataQualityStatus(StrEnum):
    """Truthful data-quality states; no state implies alpha evidence."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    RESEARCH_GRADE = "RESEARCH_GRADE"
    PARTIAL = "PARTIAL"
    NOT_MATURE = "NOT_MATURE"
    BLOCKED_WITH_EVIDENCE = "BLOCKED_WITH_EVIDENCE"
    FAIL_BLOCKING = "FAIL_BLOCKING"


class ConflictStatus(StrEnum):
    NO_CONFLICT = "NO_CONFLICT"
    CONFLICT_REQUIRES_REVIEW = "CONFLICT_REQUIRES_REVIEW"
    DUPLICATE_IMMUTABLE_RECORD = "DUPLICATE_IMMUTABLE_RECORD"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Declared provider capability and authority, independent of SDK details."""

    provider_id: str
    data_domains: frozenset[DataDomain]
    authority_tier: AuthorityTier
    pit_capable: bool
    timestamp_semantics: str
    adjustment_semantics: str
    credential_required: bool
    coverage_notes: str
    fallback_role: ProviderRole
    enabled: bool

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.data_domains:
            raise ValueError("provider must declare at least one data domain")
        if not self.timestamp_semantics.strip() or not self.adjustment_semantics.strip():
            raise ValueError("provider timestamp and adjustment semantics are required")
        if not self.coverage_notes.strip():
            raise ValueError("provider coverage_notes are required")


@dataclass(frozen=True, slots=True)
class DataProvenance:
    """Source lineage required for an observation to become decision evidence."""

    provider_id: str
    source: str
    source_identifier: str
    content_hash: str
    vintage: str
    revision_identity: str
    adjustment_semantics: str
    observed_at: datetime
    available_at: datetime
    ingested_at: datetime
    fetched_at: datetime
    published_at: datetime | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.provider_id,
                self.source,
                self.source_identifier,
                self.content_hash,
                self.vintage,
                self.revision_identity,
                self.adjustment_semantics,
            )
        ):
            raise ValueError("provenance identity and semantics are required")
        observed = _require_aware(self.observed_at, "observed_at")
        available = _require_aware(self.available_at, "available_at")
        ingested = _require_aware(self.ingested_at, "ingested_at")
        fetched = _require_aware(self.fetched_at, "fetched_at")
        published = (
            _require_aware(self.published_at, "published_at")
            if self.published_at is not None
            else None
        )
        if observed > available:
            raise ValueError("observed_at cannot be after available_at")
        if published is not None and published > available:
            raise ValueError("published_at cannot be after available_at")
        if available > ingested:
            raise ValueError("available_at cannot be after ingested_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "ingested_at", ingested)
        object.__setattr__(self, "fetched_at", fetched)
        object.__setattr__(self, "published_at", published)

    @property
    def known_at(self) -> datetime:
        """The earliest time a decision is allowed to see this evidence."""

        return self.available_at


@dataclass(frozen=True, slots=True)
class RawObservation:
    """An immutable provider observation before canonical normalization."""

    observation_id: str
    domain: DataDomain
    effective_at: datetime
    provenance: DataProvenance
    payload: Mapping[str, object]
    permanent_security_id: str | None = None
    symbol_at_time: str | None = None

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id is required")
        effective = _require_aware(self.effective_at, "effective_at")
        if self.permanent_security_id is not None and not self.permanent_security_id.strip():
            raise ValueError("permanent_security_id cannot be blank")
        if self.symbol_at_time is not None and not self.symbol_at_time.strip():
            raise ValueError("symbol_at_time cannot be blank")
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "payload", dict(self.payload))

    @property
    def immutable_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.domain.value,
            self.permanent_security_id or "UNMAPPED",
            self.provenance.source_identifier,
            self.provenance.vintage,
            self.provenance.revision_identity,
        )


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    """A normalized record retaining the complete raw lineage."""

    canonical_id: str
    raw_observation_id: str
    domain: DataDomain
    effective_at: datetime
    known_at: datetime
    provenance: DataProvenance
    values: Mapping[str, object]
    permanent_security_id: str | None = None
    symbol_at_time: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical_id.strip() or not self.raw_observation_id.strip():
            raise ValueError("canonical and raw observation ids are required")
        effective = _require_aware(self.effective_at, "effective_at")
        known = _require_aware(self.known_at, "known_at")
        if known != self.provenance.known_at:
            raise ValueError("canonical known_at must equal immutable provenance known_at")
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "values", dict(self.values))

    @classmethod
    def from_raw(
        cls, raw: RawObservation, *, values: Mapping[str, object]
    ) -> CanonicalObservation:
        digest = sha256(
            "|".join(
                (
                    raw.domain.value,
                    raw.observation_id,
                    raw.provenance.content_hash,
                    raw.provenance.revision_identity,
                )
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            canonical_id=digest,
            raw_observation_id=raw.observation_id,
            domain=raw.domain,
            effective_at=raw.effective_at,
            known_at=raw.provenance.known_at,
            provenance=raw.provenance,
            values=values,
            permanent_security_id=raw.permanent_security_id,
            symbol_at_time=raw.symbol_at_time,
        )


@dataclass(frozen=True, slots=True)
class DataConflict:
    """A durable conflict record; callers must not silently pick a provider."""

    domain: DataDomain
    conflict_key: str
    observations: tuple[CanonicalObservation, ...]
    status: ConflictStatus
    reason: str

    def __post_init__(self) -> None:
        if not self.conflict_key.strip() or not self.reason.strip():
            raise ValueError("conflict key and reason are required")
        if len(self.observations) < 2:
            raise ValueError("a conflict requires at least two observations")
        if any(item.domain is not self.domain for item in self.observations):
            raise ValueError("conflict observations must share a domain")


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Provider coverage result, distinct from a certified historical package."""

    domain: DataDomain
    provider_id: str
    coverage_start: datetime | None
    coverage_end: datetime | None
    record_count: int
    quality_status: DataQualityStatus
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_contract_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or self.record_count < 0:
            raise ValueError("coverage requires provider_id and a nonnegative record_count")
        start = (
            _require_aware(self.coverage_start, "coverage_start")
            if self.coverage_start is not None
            else None
        )
        end = (
            _require_aware(self.coverage_end, "coverage_end")
            if self.coverage_end is not None
            else None
        )
        if start is not None and end is not None and start > end:
            raise ValueError("coverage_start cannot be after coverage_end")
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)


@dataclass(frozen=True, slots=True)
class PITQuery:
    """Decision-time cutoff for provider-independent evidence reads."""

    decision_timestamp: datetime
    domain: DataDomain
    permanent_security_id: str | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None

    def __post_init__(self) -> None:
        decision = _require_aware(self.decision_timestamp, "decision_timestamp")
        start = (
            _require_aware(self.effective_start, "effective_start")
            if self.effective_start is not None
            else None
        )
        end = (
            _require_aware(self.effective_end, "effective_end")
            if self.effective_end is not None
            else None
        )
        if start is not None and end is not None and start > end:
            raise ValueError("effective_start cannot be after effective_end")
        if self.permanent_security_id is not None and not self.permanent_security_id.strip():
            raise ValueError("permanent_security_id cannot be blank")
        object.__setattr__(self, "decision_timestamp", decision)
        object.__setattr__(self, "effective_start", start)
        object.__setattr__(self, "effective_end", end)


class ProviderAdapter(Protocol):
    """Provider port. Strategy code depends on this metadata-first boundary."""

    @property
    def metadata(self) -> ProviderMetadata: ...

    def fetch_raw(self, query: PITQuery) -> tuple[RawObservation, ...]: ...


def observations_visible_at(
    observations: tuple[CanonicalObservation, ...], query: PITQuery
) -> tuple[CanonicalObservation, ...]:
    """Return only evidence legally visible by a historical decision cutoff."""

    visible: list[CanonicalObservation] = []
    for observation in observations:
        if observation.domain is not query.domain:
            continue
        if observation.known_at > query.decision_timestamp:
            continue
        if (
            query.permanent_security_id is not None
            and observation.permanent_security_id != query.permanent_security_id
        ):
            continue
        if query.effective_start is not None and observation.effective_at < query.effective_start:
            continue
        if query.effective_end is not None and observation.effective_at > query.effective_end:
            continue
        visible.append(observation)
    return tuple(
        sorted(
            visible,
            key=lambda item: (
                item.effective_at,
                item.known_at,
                item.provenance.provider_id,
                item.canonical_id,
            ),
        )
    )


def latest_visible_by_lineage(
    observations: tuple[CanonicalObservation, ...], query: PITQuery
) -> tuple[CanonicalObservation, ...]:
    """Select the latest visible revision without ever reading a future revision."""

    selected: dict[tuple[str, str, datetime, str], CanonicalObservation] = {}
    for observation in observations_visible_at(observations, query):
        key = (
            observation.domain.value,
            observation.permanent_security_id or "UNMAPPED",
            observation.effective_at,
            observation.provenance.source_identifier,
        )
        current = selected.get(key)
        if current is None or (
            observation.known_at,
            observation.provenance.ingested_at,
            observation.canonical_id,
        ) > (
            current.known_at,
            current.provenance.ingested_at,
            current.canonical_id,
        ):
            selected[key] = observation
    return tuple(sorted(selected.values(), key=lambda item: (item.effective_at, item.canonical_id)))


def detect_conflicts(
    observations: tuple[CanonicalObservation, ...],
) -> tuple[DataConflict, ...]:
    """Return cross-provider disagreements without applying an authority override.

    Identical immutable content is recorded as a duplicate, while distinct
    payload hashes sharing an economic observation key require review. The
    strategy path never calls this helper to silently choose a winner.
    """

    grouped: dict[tuple[DataDomain, str, datetime], list[CanonicalObservation]] = {}
    for observation in observations:
        key = (
            observation.domain,
            observation.permanent_security_id or "UNMAPPED",
            observation.effective_at,
        )
        grouped.setdefault(key, []).append(observation)
    conflicts: list[DataConflict] = []
    for (domain, security_id, effective_at), group in sorted(
        grouped.items(), key=lambda item: (item[0][0].value, item[0][1], item[0][2])
    ):
        providers = {item.provenance.provider_id for item in group}
        if len(group) < 2 or len(providers) < 2:
            continue
        hashes = {item.provenance.content_hash for item in group}
        status = (
            ConflictStatus.DUPLICATE_IMMUTABLE_RECORD
            if len(hashes) == 1
            else ConflictStatus.CONFLICT_REQUIRES_REVIEW
        )
        conflicts.append(
            DataConflict(
                domain=domain,
                conflict_key=f"{domain.value}:{security_id}:{effective_at.isoformat()}",
                observations=tuple(sorted(group, key=lambda item: item.canonical_id)),
                status=status,
                reason=(
                    "same immutable content reported by multiple providers"
                    if status is ConflictStatus.DUPLICATE_IMMUTABLE_RECORD
                    else "provider content hashes disagree for the same economic observation"
                ),
            )
        )
    return tuple(conflicts)
