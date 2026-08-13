"""ROUND 13.1 immutable SEC intelligence contracts (SHADOW only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import Field, model_validator

from personal_alpha_terminal.intelligence.schemas import RawInformation, StrictModel

PROMPT_VERSION = "sec-pit-event-extraction-v1"
SCHEMA_VERSION = "sec-intelligence-events-v1"
FEATURE_TRANSFORM_VERSION = "llm-shadow-features-v1"
PRODUCTION_INFLUENCE = 0.0


class SecEventType(StrEnum):
    EARNINGS = "EARNINGS"
    REVENUE_CHANGE = "REVENUE_CHANGE"
    MARGIN_CHANGE = "MARGIN_CHANGE"
    GUIDANCE_RAISE = "GUIDANCE_RAISE"
    GUIDANCE_CUT = "GUIDANCE_CUT"
    GUIDANCE_WITHDRAWN = "GUIDANCE_WITHDRAWN"
    CAPEX_INCREASE = "CAPEX_INCREASE"
    CAPEX_DECREASE = "CAPEX_DECREASE"
    DEBT_INCREASE = "DEBT_INCREASE"
    DEBT_REDUCTION = "DEBT_REDUCTION"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"
    SHARE_ISSUANCE = "SHARE_ISSUANCE"
    SHARE_DILUTION = "SHARE_DILUTION"
    BUYBACK = "BUYBACK"
    DIVIDEND_CHANGE = "DIVIDEND_CHANGE"
    INSIDER_BUY = "INSIDER_BUY"
    INSIDER_SELL = "INSIDER_SELL"
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
    AUDITOR_CHANGE = "AUDITOR_CHANGE"
    ACCOUNTING_WARNING = "ACCOUNTING_WARNING"
    RESTATEMENT = "RESTATEMENT"
    GOING_CONCERN = "GOING_CONCERN"
    MATERIAL_CONTRACT = "MATERIAL_CONTRACT"
    MERGER_ACQUISITION = "M&A"
    ASSET_SALE = "ASSET_SALE"
    RESTRUCTURING = "RESTRUCTURING"
    LAYOFF = "LAYOFF"
    LITIGATION = "LITIGATION"
    REGULATORY = "REGULATORY"
    CYBERSECURITY = "CYBERSECURITY"
    PRODUCT_EVENT = "PRODUCT_EVENT"
    OTHER_MATERIAL = "OTHER_MATERIAL"


class Direction(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"


class Materiality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Novelty(StrEnum):
    REITERATED = "REITERATED"
    UPDATED = "UPDATED"
    NEW = "NEW"


class Horizon(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"


class EvidenceStatus(StrEnum):
    ACCEPTED = "accepted"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    LOW_CONFIDENCE = "low_confidence"
    HALLUCINATION_SUSPECTED = "hallucination_suspected"


class ExtractedSecEvent(StrictModel):
    issuer_id: str
    ticker_asof: str | None = None
    event_type: SecEventType
    direction: Direction
    magnitude: float | None = Field(default=None, ge=-10, le=10)
    materiality: Materiality
    novelty: Novelty
    horizon: Horizon
    extraction_confidence: float = Field(ge=0, le=1)
    source_section: str
    source_span: str = Field(min_length=12, max_length=4000)
    event_timestamp: datetime
    available_at: datetime
    summary: str = Field(min_length=1, max_length=1000)
    model: str
    prompt_version: str

    @model_validator(mode="after")
    def temporal_contract(self) -> ExtractedSecEvent:
        if self.event_timestamp.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        if self.event_timestamp > self.available_at:
            raise ValueError("event_timestamp cannot exceed available_at")
        return self


class SecDocumentExtraction(StrictModel):
    document_summary: str = Field(min_length=1, max_length=2000)
    events: tuple[ExtractedSecEvent, ...] = Field(max_length=50)


@dataclass(frozen=True, slots=True)
class AcceptedSecEvent:
    event_id: str
    raw_id: str
    issuer_id: str
    ticker_asof: str | None
    event_type: str
    direction: str
    magnitude: float | None
    materiality: str
    novelty: str
    horizon: str
    extraction_confidence: float
    source_section: str
    source_span: str
    summary: str
    evidence_hash: str
    event_timestamp: datetime
    available_at: datetime
    model_provider: str
    model_name: str
    response_hash: str
    prompt_version: str
    claimed_ticker_asof: str | None = None
    security_mapping_status: str = "SECURITY_MAPPED"
    evidence_status: str = EvidenceStatus.ACCEPTED
    production_influence: float = PRODUCTION_INFLUENCE


def validate_evidence(
    event: ExtractedSecEvent,
    raw: RawInformation,
    *,
    evidence_text: str | None = None,
    expected_model: str | None = None,
) -> str | None:
    if raw.accepted_at is None or raw.available_at is None:
        return "ACQUIRED_NOT_PIT_CERTIFIED"
    if event.issuer_id != raw.issuer_id:
        return "ISSUER_IDENTITY_MISMATCH"
    if raw.ticker_as_of and event.ticker_asof != raw.ticker_as_of:
        return "TICKER_ASOF_MISMATCH"
    if event.available_at != raw.available_at:
        return "AVAILABLE_AT_MISMATCH"
    if event.prompt_version != PROMPT_VERSION:
        return EvidenceStatus.HALLUCINATION_SUSPECTED
    if expected_model is not None and event.model != expected_model:
        return EvidenceStatus.HALLUCINATION_SUSPECTED
    corpus = raw.body if evidence_text is None else evidence_text
    matches = corpus.count(event.source_span)
    if matches == 0:
        return EvidenceStatus.UNSUPPORTED_CLAIM
    if event.extraction_confidence < 0.5:
        return EvidenceStatus.LOW_CONFIDENCE
    return None


@dataclass(frozen=True, slots=True)
class LLMShadowFeature:
    feature_id: str
    issuer_id: str
    ticker_asof: str | None
    feature_name: str
    as_of: datetime
    value: float
    event_ids: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    event_ages_days: tuple[float, ...]
    decay_weights: tuple[float, ...]
    missing_semantics: str = "zero means no accepted PIT-visible mapped event"
    normalization_policy: str = "deterministic raw aggregation; research normalization deferred"
    transform_version: str = FEATURE_TRANSFORM_VERSION
    production_influence: float = PRODUCTION_INFLUENCE


_FEATURES = (
    "fundamental_revision_score",
    "guidance_revision_score",
    "earnings_quality_score",
    "margin_acceleration_score",
    "capital_allocation_score",
    "balance_sheet_stress_score",
    "dilution_risk_score",
    "management_change_score",
    "accounting_risk_score",
    "litigation_risk_score",
    "material_event_intensity",
    "insider_activity_score",
    "event_novelty_score",
    "event_materiality_score",
    "llm_event_momentum",
)

_MAPPING = {
    "GUIDANCE_RAISE": ("guidance_revision_score", 1.0),
    "GUIDANCE_CUT": ("guidance_revision_score", -1.0),
    "GUIDANCE_WITHDRAWN": ("guidance_revision_score", -1.0),
    "REVENUE_CHANGE": ("fundamental_revision_score", 1.0),
    "EARNINGS": ("earnings_quality_score", 1.0),
    "MARGIN_CHANGE": ("margin_acceleration_score", 1.0),
    "BUYBACK": ("capital_allocation_score", 1.0),
    "DEBT_INCREASE": ("balance_sheet_stress_score", 1.0),
    "LIQUIDITY_STRESS": ("balance_sheet_stress_score", 1.0),
    "SHARE_DILUTION": ("dilution_risk_score", 1.0),
    "MANAGEMENT_CHANGE": ("management_change_score", 1.0),
    "ACCOUNTING_WARNING": ("accounting_risk_score", 1.0),
    "RESTATEMENT": ("accounting_risk_score", 1.0),
    "LITIGATION": ("litigation_risk_score", 1.0),
    "INSIDER_BUY": ("insider_activity_score", 1.0),
    "INSIDER_SELL": ("insider_activity_score", -1.0),
}


def build_shadow_features(
    events: tuple[AcceptedSecEvent, ...], *, as_of: datetime
) -> tuple[LLMShadowFeature, ...]:
    if as_of.tzinfo is None:
        raise ValueError("feature cutoff must be timezone-aware")
    grouped: dict[tuple[str, str | None], list[AcceptedSecEvent]] = {}
    for event in events:
        if event.available_at <= as_of and event.ticker_asof is not None:
            grouped.setdefault((event.issuer_id, event.ticker_asof), []).append(event)
    output: list[LLMShadowFeature] = []
    for (issuer, ticker), items in sorted(grouped.items()):
        values = {name: 0.0 for name in _FEATURES}
        ages: list[float] = []
        decays: list[float] = []
        for item in items:
            age = max(0.0, (as_of - item.available_at).total_seconds() / 86400)
            half_life = {"IMMEDIATE": 3, "SHORT": 10, "MEDIUM": 30, "LONG": 90}[item.horizon]
            decay = math.exp(-math.log(2) * age / half_life)
            ages.append(age)
            decays.append(decay)
            direction = {"POSITIVE": 1.0, "NEGATIVE": -1.0, "MIXED": 0.0, "NEUTRAL": 0.0}[
                item.direction
            ]
            materiality = {"LOW": 0.25, "MEDIUM": 0.6, "HIGH": 1.0}[item.materiality]
            novelty = {"REITERATED": 0.2, "UPDATED": 0.6, "NEW": 1.0}[item.novelty]
            signed = direction * materiality * novelty * decay
            mapped = _MAPPING.get(item.event_type)
            if mapped:
                values[mapped[0]] += mapped[1] * (
                    signed if direction else materiality * novelty * decay
                )
            values["material_event_intensity"] += materiality * decay
            values["event_novelty_score"] += novelty * decay
            values["event_materiality_score"] += materiality * decay
            values["llm_event_momentum"] += signed
        event_ids = tuple(sorted(item.event_id for item in items))
        evidence = tuple(sorted(item.evidence_hash for item in items))
        for name, value in values.items():
            feature_id = sha256(
                f"{issuer}|{ticker}|{name}|{as_of.isoformat()}|{value:.12g}|{FEATURE_TRANSFORM_VERSION}|{'|'.join(event_ids)}".encode()
            ).hexdigest()
            output.append(
                LLMShadowFeature(
                    feature_id,
                    issuer,
                    ticker,
                    name,
                    as_of,
                    value,
                    event_ids,
                    evidence,
                    tuple(ages),
                    tuple(decays),
                )
            )
    return tuple(output)
