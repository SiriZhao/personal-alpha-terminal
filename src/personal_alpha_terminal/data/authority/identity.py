"""Durable issuer/security identity and lifecycle contracts.

Ticker strings are time-bounded display attributes.  The registry below never
joins two records solely because their ticker text matches and deliberately
returns an explicit ambiguity when a ticker was reused or source evidence
overlaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class IdentityResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNAVAILABLE = "UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


class LifecycleEventType(StrEnum):
    LISTING = "LISTING"
    DELISTING = "DELISTING"
    SUSPENSION = "SUSPENSION"
    TICKER_CHANGE = "TICKER_CHANGE"
    NAME_CHANGE = "NAME_CHANGE"
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    SPINOFF = "SPINOFF"
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    EXCHANGE_CHANGE = "EXCHANGE_CHANGE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class SecurityIdentityVintage:
    """Time-bounded, source-backed security mapping.

    ``issuer_id`` and ``security_id`` are immutable internal IDs. ``cik`` is
    an issuer anchor, not a replacement for a share-class level security ID.
    A source may leave FIGI absent; the missing value must not be invented.
    """

    issuer_id: str
    security_id: str
    ticker: str
    company_name: str
    exchange: str
    security_type: str
    valid_from: date
    known_at: datetime
    source: str
    source_timestamp: datetime
    ingested_at: datetime
    confidence: float
    valid_to: date | None = None
    cik: int | None = None
    figi: str | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    delisting_reason: str | None = None
    source_record_id: str | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.issuer_id,
                self.security_id,
                self.ticker,
                self.company_name,
                self.exchange,
                self.security_type,
                self.source,
            )
        ):
            raise ValueError("identity vintage requires immutable ids, attributes, and source")
        if self.cik is not None and self.cik <= 0:
            raise ValueError("CIK must be positive when supplied")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("identity valid_to cannot be before valid_from")
        if self.listing_date is not None and self.delisting_date is not None:
            if self.delisting_date < self.listing_date:
                raise ValueError("delisting_date cannot be before listing_date")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("identity confidence must be in [0, 1]")
        known = _aware_utc(self.known_at, "known_at")
        source_timestamp = _aware_utc(self.source_timestamp, "source_timestamp")
        ingested = _aware_utc(self.ingested_at, "ingested_at")
        if source_timestamp > known:
            raise ValueError("source_timestamp cannot be after known_at")
        if known > ingested:
            raise ValueError("known_at cannot be after ingested_at")
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "source_timestamp", source_timestamp)
        object.__setattr__(self, "ingested_at", ingested)

    def is_valid_at(self, as_of: datetime) -> bool:
        cutoff = _aware_utc(as_of, "as_of")
        session = cutoff.date()
        return (
            self.known_at <= cutoff
            and self.valid_from <= session
            and (self.valid_to is None or session <= self.valid_to)
            and (self.listing_date is None or self.listing_date <= session)
            and (self.delisting_date is None or session <= self.delisting_date)
        )


@dataclass(frozen=True, slots=True)
class SecurityLifecycleEvent:
    """Canonical public lifecycle evidence; all ambiguous predecessor links remain explicit."""

    security_id: str
    event_type: LifecycleEventType
    effective_date: date
    known_at: datetime
    source: str
    source_record_id: str
    fetched_at: datetime
    confidence: float
    event_id: str
    old_ticker: str | None = None
    new_ticker: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    announcement_timestamp: datetime | None = None
    exchange: str | None = None
    reason: str | None = None
    predecessor_security_id: str | None = None
    successor_security_id: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.security_id,
                self.source,
                self.source_record_id,
                self.event_id,
            )
        ):
            raise ValueError("lifecycle event identity and source fields are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("lifecycle confidence must be in [0, 1]")
        known = _aware_utc(self.known_at, "known_at")
        fetched = _aware_utc(self.fetched_at, "fetched_at")
        announcement = (
            _aware_utc(self.announcement_timestamp, "announcement_timestamp")
            if self.announcement_timestamp is not None
            else None
        )
        if announcement is not None and announcement > known:
            raise ValueError("announcement_timestamp cannot be after known_at")
        if known > fetched:
            raise ValueError("known_at cannot be after fetched_at")
        if self.event_type is LifecycleEventType.TICKER_CHANGE:
            if not self.old_ticker or not self.new_ticker:
                raise ValueError("ticker change requires old_ticker and new_ticker")
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "fetched_at", fetched)
        object.__setattr__(self, "announcement_timestamp", announcement)


@dataclass(frozen=True, slots=True)
class PITIdentityResolution:
    status: IdentityResolutionStatus
    security: SecurityIdentityVintage | None
    candidates: tuple[SecurityIdentityVintage, ...]
    blockers: tuple[str, ...]


class PITSecurityMaster:
    """In-memory PIT identity resolver suitable for an imported authority package."""

    def __init__(
        self,
        identities: tuple[SecurityIdentityVintage, ...],
        lifecycle_events: tuple[SecurityLifecycleEvent, ...] = (),
    ) -> None:
        self._identities = tuple(
            sorted(
                identities,
                key=lambda item: (
                    item.security_id,
                    item.valid_from,
                    item.known_at,
                    item.ticker,
                ),
            )
        )
        self._events = tuple(
            sorted(
                lifecycle_events,
                key=lambda item: (
                    item.security_id,
                    item.effective_date,
                    item.known_at,
                    item.event_id,
                ),
            )
        )

    def resolve_ticker(
        self,
        *,
        ticker: str,
        exchange: str,
        as_of: datetime,
    ) -> PITIdentityResolution:
        cutoff = _aware_utc(as_of, "as_of")
        normalized_ticker = ticker.strip().upper()
        normalized_exchange = exchange.strip().upper()
        if not normalized_ticker or not normalized_exchange:
            raise ValueError("ticker and exchange are required")
        candidates = tuple(
            item
            for item in self._identities
            if item.ticker.upper() == normalized_ticker
            and item.exchange.upper() == normalized_exchange
            and item.is_valid_at(cutoff)
        )
        unique = {item.security_id for item in candidates}
        if len(unique) == 1:
            candidate = max(candidates, key=lambda item: (item.known_at, item.valid_from))
            return PITIdentityResolution(
                IdentityResolutionStatus.RESOLVED,
                candidate,
                candidates,
                (),
            )
        if len(unique) > 1:
            return PITIdentityResolution(
                IdentityResolutionStatus.AMBIGUOUS,
                None,
                candidates,
                ("AMBIGUOUS_TICKER_OR_TICKER_REUSE",),
            )
        return PITIdentityResolution(
            IdentityResolutionStatus.UNAVAILABLE,
            None,
            (),
            ("NO_PIT_IDENTITY_MAPPING",),
        )

    def resolve_cik(self, *, cik: int, as_of: datetime) -> PITIdentityResolution:
        if cik <= 0:
            raise ValueError("CIK must be positive")
        cutoff = _aware_utc(as_of, "as_of")
        candidates = tuple(
            item
            for item in self._identities
            if item.cik == cik and item.is_valid_at(cutoff)
        )
        unique = {item.security_id for item in candidates}
        if len(unique) == 1:
            candidate = max(candidates, key=lambda item: (item.known_at, item.valid_from))
            return PITIdentityResolution(
                IdentityResolutionStatus.RESOLVED,
                candidate,
                candidates,
                (),
            )
        if len(unique) > 1:
            return PITIdentityResolution(
                IdentityResolutionStatus.AMBIGUOUS,
                None,
                candidates,
                ("CIK_HAS_MULTIPLE_ACTIVE_SECURITY_CLASSES",),
            )
        return PITIdentityResolution(
            IdentityResolutionStatus.UNAVAILABLE,
            None,
            (),
            ("NO_PIT_CIK_SECURITY_MAPPING",),
        )

    def lifecycle_for(
        self, *, security_id: str, as_of: datetime
    ) -> tuple[SecurityLifecycleEvent, ...]:
        cutoff = _aware_utc(as_of, "as_of")
        return tuple(
            item
            for item in self._events
            if item.security_id == security_id
            and item.effective_date <= cutoff.date()
            and item.known_at <= cutoff
        )
