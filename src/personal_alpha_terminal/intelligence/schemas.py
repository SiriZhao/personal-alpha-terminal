from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IntelligenceStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    BLOCKED = "BLOCKED"
    AI_PARSE_FAILED = "AI_PARSE_FAILED"
    AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"


class BacktestSafety(StrEnum):
    BACKTEST_SAFE = "BACKTEST_SAFE"
    NOT_BACKTEST_SAFE = "NOT_BACKTEST_SAFE"
    NOT_VALIDATED = "NOT_VALIDATED"


class EventDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    EARNINGS = "EARNINGS"
    REVENUE = "REVENUE"
    GUIDANCE = "GUIDANCE"
    MARGIN = "MARGIN"
    CAPEX = "CAPEX"
    BUYBACK = "BUYBACK"
    DIVIDEND = "DIVIDEND"
    MANAGEMENT = "MANAGEMENT"
    MERGER_ACQUISITION = "MERGER_ACQUISITION"
    PARTNERSHIP = "PARTNERSHIP"
    PRODUCT = "PRODUCT"
    PRODUCT_DELAY = "PRODUCT_DELAY"
    CUSTOMER_WIN = "CUSTOMER_WIN"
    CUSTOMER_LOSS = "CUSTOMER_LOSS"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    PRICING = "PRICING"
    REGULATION = "REGULATION"
    LITIGATION = "LITIGATION"
    CYBERSECURITY = "CYBERSECURITY"
    ACCOUNTING_CONCERN = "ACCOUNTING_CONCERN"
    ANALYST_ACTION = "ANALYST_ACTION"
    FINANCING = "FINANCING"
    INSIDER = "INSIDER"
    CPI = "CPI"
    PCE = "PCE"
    NFP = "NFP"
    GDP = "GDP"
    FED = "FED"
    YIELD = "YIELD"
    DOLLAR = "DOLLAR"
    OIL = "OIL"
    TARIFF = "TARIFF"
    EXPORT_RESTRICTION = "EXPORT_RESTRICTION"
    AI_DEMAND = "AI_DEMAND"
    SANCTIONS = "SANCTIONS"
    GEOPOLITICS = "GEOPOLITICS"
    LIQUIDITY = "LIQUIDITY"
    INDUSTRY = "INDUSTRY"
    OTHER = "OTHER"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class RawInformation(StrictModel):
    raw_id: str
    source: str
    source_identifier: str
    title: str
    body: str
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    source_url: str | None = None
    source_hash: str | None = None
    data_cutoff: datetime
    filed_at: datetime | None = None
    accepted_at: datetime | None = None
    event_time: datetime | None = None
    provider_received_at: datetime | None = None
    available_at: datetime | None = None
    processed_at: datetime | None = None
    revision_id: str | None = None

    @field_validator("raw_id", "source", "source_identifier", "title")
    @classmethod
    def required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required text cannot be empty")
        return normalized

    @field_validator("published_at", "observed_at", "ingested_at", "data_cutoff")
    @classmethod
    def aware_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "filed_at",
        "accepted_at",
        "event_time",
        "provider_received_at",
        "available_at",
        "processed_at",
    )
    @classmethod
    def optional_aware_timestamps(cls, value: datetime | None, info: Any) -> datetime | None:
        return _aware(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def validate_temporal_lineage(self) -> RawInformation:
        if self.observed_at < self.published_at:
            raise ValueError("information cannot be observed before publication")
        if self.ingested_at < self.observed_at:
            raise ValueError("information cannot be ingested before observation")
        if self.data_cutoff < self.observed_at or self.data_cutoff > self.ingested_at:
            raise ValueError("data_cutoff must lie between observed_at and ingested_at")
        available = self.available_at or self.observed_at
        received = self.provider_received_at or self.observed_at
        processed = self.processed_at or self.ingested_at
        if received < self.published_at:
            raise ValueError("provider_received_at cannot precede publication")
        required_times = tuple(
            item
            for item in (self.published_at, self.filed_at, self.accepted_at, received)
            if item is not None
        )
        if available < max(required_times):
            raise ValueError("available_at precedes an information availability boundary")
        if available > self.data_cutoff or processed < self.data_cutoff:
            raise ValueError("document availability/processing violates the PIT cutoff")
        expected_hash = sha256(
            f"{self.source}|{self.source_identifier}|{self.title}|{self.body}".encode()
        ).hexdigest()
        if self.source_hash is not None and self.source_hash != expected_hash:
            raise ValueError("source_hash does not match immutable raw content")
        object.__setattr__(self, "source_hash", expected_hash)
        object.__setattr__(self, "provider_received_at", received)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "processed_at", processed)
        return self

    def visible_at(self, decision_as_of: datetime) -> bool:
        _aware(decision_as_of, "decision_as_of")
        return bool(self.available_at is not None and self.available_at <= decision_as_of)


class EventEvidence(StrictModel):
    evidence_id: str
    source: str
    source_identifier: str
    source_hash: str
    published_at: datetime
    observed_at: datetime
    reference: str
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    available_at: datetime | None = None

    @field_validator("published_at", "observed_at", "available_at")
    @classmethod
    def evidence_times_are_aware(cls, value: datetime | None, info: Any) -> datetime | None:
        return _aware(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def validate_observation(self) -> EventEvidence:
        if self.observed_at < self.published_at:
            raise ValueError("evidence observed_at precedes published_at")
        if self.available_at is None:
            object.__setattr__(self, "available_at", self.observed_at)
        elif self.available_at < self.observed_at:
            raise ValueError("evidence available_at precedes provider observation")
        return self


class UnifiedEvent(StrictModel):
    event_id: str
    schema_version: str = "event-schema-v1"
    symbol: str | None = None
    entity: str
    sector: str | None = None
    industry: str | None = None
    event_type: EventType
    event_subtype: str | None = None
    title: str
    summary: str
    published_at: datetime
    observed_at: datetime
    effective_at: datetime
    ingested_at: datetime
    source: str
    source_identifier: str
    source_hash: str
    direction: EventDirection = EventDirection.UNKNOWN
    magnitude: float | None = None
    surprise: float | None = None
    relevance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    expected_horizon: int = Field(ge=1, le=252)
    affected_assets: tuple[str, ...] = ()
    affected_sectors: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    structured_features: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[EventEvidence, ...]
    model_version: str
    prompt_version: str
    data_cutoff: datetime
    created_at: datetime
    backtest_safety: BacktestSafety = BacktestSafety.NOT_VALIDATED
    canonical_cluster_id: str | None = None

    @field_validator(
        "published_at", "observed_at", "effective_at", "ingested_at", "data_cutoff", "created_at"
    )
    @classmethod
    def event_times_are_aware(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "event_id",
        "schema_version",
        "entity",
        "title",
        "summary",
        "source",
        "source_identifier",
        "source_hash",
        "model_version",
        "prompt_version",
    )
    @classmethod
    def event_text_is_present(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event lineage and identity fields are required")
        return normalized

    @model_validator(mode="after")
    def validate_event_lineage(self) -> UnifiedEvent:
        if self.observed_at < self.published_at:
            raise ValueError("event cannot be observed before publication")
        if self.ingested_at < self.observed_at or self.created_at < self.ingested_at:
            raise ValueError("event processing timestamps are out of order")
        if self.data_cutoff < self.observed_at or self.data_cutoff > self.created_at:
            raise ValueError("event data_cutoff is outside the observable processing window")
        if not self.evidence:
            raise ValueError("event must retain at least one evidence reference")
        if min(item.observed_at for item in self.evidence) < self.published_at:
            raise ValueError("event evidence violates publication boundary")
        if self.backtest_safety is BacktestSafety.BACKTEST_SAFE:
            if any(
                (item.available_at or item.observed_at) > self.data_cutoff for item in self.evidence
            ):
                raise ValueError("backtest-safe event contains future evidence")
        return self

    def visible_at(self, cutoff: datetime) -> bool:
        return self.at_cutoff(cutoff) is not None

    def at_cutoff(self, cutoff: datetime) -> UnifiedEvent | None:
        _aware(cutoff, "cutoff")
        visible_evidence = tuple(
            item for item in self.evidence if (item.available_at or item.observed_at) <= cutoff
        )
        if self.observed_at > cutoff or not visible_evidence:
            return None
        distinct_sources = len({item.source for item in visible_evidence})
        evidence_confidence = [
            item.extraction_confidence
            for item in visible_evidence
            if item.extraction_confidence is not None
        ]
        confidence = (
            min(max(evidence_confidence) + 0.02 * (distinct_sources - 1), 1.0)
            if evidence_confidence
            else self.confidence
        )
        return self.model_copy(
            update={
                "evidence": visible_evidence,
                "data_cutoff": max(
                    item.available_at or item.observed_at for item in visible_evidence
                ),
                "confidence": confidence,
            }
        )


class AgentResult(StrictModel):
    agent_type: str
    result: str
    structured_features: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[str, ...]
    observed_at: datetime
    data_cutoff: datetime
    model: str
    version: str
    status: IntelligenceStatus

    @field_validator("observed_at", "data_cutoff")
    @classmethod
    def agent_times_are_aware(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_cutoff(self) -> AgentResult:
        if self.data_cutoff < self.observed_at:
            raise ValueError("agent result data_cutoff precedes observed input")
        return self
