"""Structured, auditable LLM decision fusion contracts.

This module is deliberately additive.  It gives the LLM a rich, typed decision
surface and records how that surface was (or was not) allowed to influence the
deterministic quant path.  Hard risk, data-quality, tradability, optimizer, and
manual-execution boundaries remain outside the LLM authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DecisionInfluenceLevel(StrEnum):
    L0_COMMENTARY = "L0_COMMENTARY"
    L1_SHADOW_SCORING = "L1_SHADOW_SCORING"
    L2_RANKING = "L2_RANKING"
    L3_BOUNDED_FORMAL = "L3_BOUNDED_FORMAL"
    L4_ADAPTIVE_EVIDENCE = "L4_ADAPTIVE_EVIDENCE"


class EvidenceState(StrEnum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    UNKNOWN_UNVERIFIED = "UNKNOWN_UNVERIFIED"
    CONFLICTING = "CONFLICTING"


class DisagreementCategory(StrEnum):
    STRONG_AGREEMENT = "STRONG_AGREEMENT"
    WEAK_AGREEMENT = "WEAK_AGREEMENT"
    LLM_MORE_BULLISH = "LLM_MORE_BULLISH"
    LLM_MORE_BEARISH = "LLM_MORE_BEARISH"
    EVENT_CONFLICT = "EVENT_CONFLICT"
    FUNDAMENTAL_CONFLICT = "FUNDAMENTAL_CONFLICT"
    DATA_UNCERTAIN = "DATA_UNCERTAIN"


class LLMDecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class EvidenceProvenance(LLMDecisionModel):
    source_id: str
    source_type: str
    observed_at: datetime
    available_at: datetime
    freshness: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    state: EvidenceState
    evidence_ids: tuple[str, ...] = ()

    @field_validator("observed_at", "available_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("source_id", "source_type")
    @classmethod
    def text_is_required(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return value.strip()

    @model_validator(mode="after")
    def validate_availability(self) -> EvidenceProvenance:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self


class LLMMarketDecision(LLMDecisionModel):
    market_regime_view: str
    regime_confidence: float = Field(ge=0, le=1)
    risk_budget_adjustment: float = Field(ge=-1, le=1)
    exposure_adjustment: float = Field(ge=-1, le=1)
    macro_risk: tuple[str, ...] = ()
    event_risk: tuple[str, ...] = ()
    breadth_trend_interpretation: str
    uncertainty: float = Field(ge=0, le=1)
    evidence: tuple[EvidenceProvenance, ...] = ()


class LLMCandidateDecision(LLMDecisionModel):
    symbol: str
    company_summary: str
    business_quality_view: str
    recent_developments: tuple[str, ...] = ()
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    event_risk: tuple[str, ...] = ()
    conviction: float = Field(ge=-1, le=1)
    quant_disagreement: float = Field(ge=-1, le=1)
    ranking_adjustment: float = Field(ge=-1, le=1)
    position_conviction_adjustment: float = Field(ge=-1, le=1)
    action_urgency: float = Field(ge=0, le=1)
    veto_or_warning: str | None = None
    reasoning: str
    evidence: tuple[EvidenceProvenance, ...] = ()

    @field_validator("symbol")
    @classmethod
    def symbol_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("symbol cannot be empty")
        return value.strip().upper()


class LLMPortfolioDecision(LLMDecisionModel):
    portfolio_view: str
    risk_budget_adjustment: float = Field(ge=-1, le=1)
    target_exposure_adjustment: float = Field(ge=-1, le=1)
    concentration_warning: str | None = None
    major_risks: tuple[str, ...] = ()
    rebalance_urgency: float = Field(ge=0, le=1)
    reasoning: str
    evidence: tuple[EvidenceProvenance, ...] = ()


class StructuredLLMDecision(LLMDecisionModel):
    schema_version: str = "llm-decision-fusion-v1"
    decision_timestamp: datetime
    information_cutoff: datetime
    market: LLMMarketDecision
    candidates: tuple[LLMCandidateDecision, ...]
    portfolio: LLMPortfolioDecision
    overall_confidence: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    evidence_summary: str = ""

    @field_validator("decision_timestamp", "information_cutoff")
    @classmethod
    def decision_times_are_aware(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_cutoff_and_identities(self) -> StructuredLLMDecision:
        if self.information_cutoff > self.decision_timestamp:
            raise ValueError("information_cutoff cannot follow decision_timestamp")
        symbols = [item.symbol for item in self.candidates]
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("candidate symbols must be non-empty and unique")
        all_evidence = tuple(self.market.evidence) + tuple(self.portfolio.evidence)
        for candidate in self.candidates:
            all_evidence += tuple(candidate.evidence)
        if any(item.available_at > self.information_cutoff for item in all_evidence):
            raise ValueError("LLM evidence cannot be newer than information_cutoff")
        return self


class DisagreementRecord(LLMDecisionModel):
    symbol: str
    quant_view: float
    llm_view: float
    category: DisagreementCategory
    reason: str
    fusion_result: str
    evidence_state: EvidenceState


class DecisionAudit(LLMDecisionModel):
    schema_version: str = "llm-decision-audit-v1"
    influence_level: DecisionInfluenceLevel
    requested_influence_level: DecisionInfluenceLevel
    formal_influence: float = Field(ge=0, le=1)
    hard_constraints_passed: bool
    optimizer_final_authority: bool = True
    manual_confirmation_required: bool = True
    auto_execution: str = "DISABLED"
    provenance: tuple[EvidenceProvenance, ...] = ()
    disagreements: tuple[DisagreementRecord, ...] = ()
    degraded_ai: bool = False
    failure_reason: str | None = None
    deterministic_fallback: bool = False
    model_version: str = ""

    @model_validator(mode="after")
    def enforce_safety_boundary(self) -> DecisionAudit:
        if not self.optimizer_final_authority:
            raise ValueError("LLM audit requires optimizer final authority")
        if not self.manual_confirmation_required or self.auto_execution != "DISABLED":
            raise ValueError("LLM audit must remain manual-only")
        if self.formal_influence > 0 and self.influence_level in {
            DecisionInfluenceLevel.L0_COMMENTARY,
            DecisionInfluenceLevel.L1_SHADOW_SCORING,
        }:
            raise ValueError("formal influence requires a formal influence level")
        return self


class ParseOutcome(LLMDecisionModel):
    decision: StructuredLLMDecision | None = None
    error: str | None = None
    degraded: bool = False


class FusionOutcome(LLMDecisionModel):
    fused_scores: dict[str, float]
    applied_influence: float = Field(ge=0, le=1)
    hard_risk_overridden: bool = False
    reason: str


def parse_structured_decision(
    payload: object,
    *,
    allowed_symbols: frozenset[str],
    information_cutoff: datetime,
) -> ParseOutcome:
    """Parse rich LLM output and fail closed on malformed/future evidence."""

    try:
        cutoff = _aware(information_cutoff, "information_cutoff")
        decision = StructuredLLMDecision.model_validate(payload)
        if {item.symbol for item in decision.candidates} != set(allowed_symbols):
            raise ValueError("LLM candidates must exactly match the quant candidate set")
        if decision.information_cutoff > cutoff:
            raise ValueError("LLM information cutoff is newer than the quant cutoff")
        return ParseOutcome(decision=decision)
    except Exception as error:  # validation boundary intentionally fail-soft
        return ParseOutcome(error=f"{type(error).__name__}:{error}", degraded=True)


def resolve_influence_level(
    requested: DecisionInfluenceLevel,
    *,
    promotion_passed: bool,
    evidence_verified: bool,
    production_enabled: bool,
) -> DecisionInfluenceLevel:
    """Resolve the evidence-based ladder without silently promoting production."""

    if not production_enabled or not promotion_passed or not evidence_verified:
        return (
            DecisionInfluenceLevel.L1_SHADOW_SCORING
            if requested is not DecisionInfluenceLevel.L0_COMMENTARY
            else DecisionInfluenceLevel.L0_COMMENTARY
        )
    return requested


def classify_disagreement(
    *,
    symbol: str,
    quant_view: float,
    llm_view: float,
    evidence_state: EvidenceState,
    reason: str = "",
) -> DisagreementRecord:
    delta = llm_view - quant_view
    if evidence_state is EvidenceState.UNKNOWN_UNVERIFIED or evidence_state is EvidenceState.STALE:
        category = DisagreementCategory.DATA_UNCERTAIN
    elif evidence_state is EvidenceState.CONFLICTING:
        category = DisagreementCategory.EVENT_CONFLICT
    elif abs(delta) < 0.10:
        category = (
            DisagreementCategory.STRONG_AGREEMENT
            if abs(delta) < 0.03
            else DisagreementCategory.WEAK_AGREEMENT
        )
    elif delta > 0:
        category = DisagreementCategory.LLM_MORE_BULLISH
    else:
        category = DisagreementCategory.LLM_MORE_BEARISH
    fusion = "QUANT_ONLY" if category is DisagreementCategory.DATA_UNCERTAIN else "BOUNDED_REVIEW"
    return DisagreementRecord(
        symbol=symbol,
        quant_view=quant_view,
        llm_view=llm_view,
        category=category,
        reason=reason or category.value,
        fusion_result=fusion,
        evidence_state=evidence_state,
    )


def bounded_fusion(
    quant_scores: dict[str, float],
    llm_adjustments: dict[str, float],
    *,
    influence: float,
    max_adjustment: float,
    hard_constraints_ok: bool,
) -> FusionOutcome:
    """Apply only finite, bounded score adjustments after a hard-risk check."""

    if not hard_constraints_ok:
        return FusionOutcome(
            fused_scores=dict(quant_scores),
            applied_influence=0.0,
            hard_risk_overridden=True,
            reason="HARD_RISK_OVERRIDE_QUANT_ONLY",
        )
    if not isfinite(influence) or not 0 <= influence <= 1:
        raise ValueError("influence must be finite and in [0,1]")
    if not isfinite(max_adjustment) or max_adjustment < 0:
        raise ValueError("max_adjustment must be finite and non-negative")
    fused: dict[str, float] = {}
    for symbol, quant in quant_scores.items():
        if not isfinite(quant):
            raise ValueError("quant scores must be finite")
        raw = llm_adjustments.get(symbol, 0.0)
        if not isfinite(raw):
            raise ValueError("LLM adjustments must be finite")
        bounded = max(-max_adjustment, min(max_adjustment, raw))
        fused[symbol] = quant + influence * bounded
    return FusionOutcome(
        fused_scores=fused,
        applied_influence=influence,
        reason="BOUNDED_LLM_ADJUSTMENT",
    )


def evidence_state_for_events(
    events: tuple[Any, ...],
    *,
    decision_timestamp: datetime,
    freshness_window: timedelta = timedelta(days=7),
) -> EvidenceState:
    """Derive a conservative state from PIT event records without inventing facts."""

    if not events:
        return EvidenceState.UNKNOWN_UNVERIFIED
    cutoff = _aware(decision_timestamp, "decision_timestamp")
    available = [getattr(event, "available_at", None) for event in events]
    if any(item is None for item in available):
        return EvidenceState.UNKNOWN_UNVERIFIED
    if any(item > cutoff for item in available if item is not None):
        return EvidenceState.UNKNOWN_UNVERIFIED
    if all(cutoff - item > freshness_window for item in available if item is not None):
        return EvidenceState.STALE
    return EvidenceState.VERIFIED


def audit_from_agentic_output(
    packet: Any,
    output: Any,
    *,
    requested_level: DecisionInfluenceLevel,
    mode_allows_influence: bool,
    promotion_passed: bool,
    production_enabled: bool,
    formal_influence: float,
    model_version: str,
) -> DecisionAudit:
    """Build a compact audit record from the existing Agentic packet/output."""

    provenances: list[EvidenceProvenance] = []
    disagreements: list[DisagreementRecord] = []
    for candidate, stock in zip(packet.candidates, output.stocks, strict=True):
        state = evidence_state_for_events(
            candidate.events,
            decision_timestamp=packet.decision_timestamp,
        )
        for event in candidate.events:
            provenances.append(
                EvidenceProvenance(
                    source_id=event.source_id,
                    source_type=event.source_type,
                    observed_at=event.published_at,
                    available_at=event.available_at,
                    freshness=candidate.news_freshness,
                    confidence=stock.confidence,
                    state=state,
                    evidence_ids=(event.event_id,),
                )
            )
        disagreements.append(
            classify_disagreement(
                symbol=candidate.security.symbol,
                quant_view=candidate.quant.expected_alpha,
                llm_view=candidate.quant.expected_alpha + stock.recommended_alpha_adjustment,
                evidence_state=state,
                reason=(
                    "LLM event/fundamental interpretation conflicts with quant"
                    if stock.quant_disagreement >= 0.5
                    else "structured LLM comparison"
                ),
            )
        )
    evidence_verified = bool(provenances) and all(
        item.state is EvidenceState.VERIFIED for item in provenances
    )
    level = resolve_influence_level(
        requested_level,
        promotion_passed=promotion_passed and mode_allows_influence,
        evidence_verified=evidence_verified,
        production_enabled=production_enabled,
    )
    return DecisionAudit(
        influence_level=level,
        requested_influence_level=requested_level,
        formal_influence=formal_influence,
        hard_constraints_passed=bool(packet.risk_state.get("hard_constraints_valid", False)),
        provenance=tuple(provenances),
        disagreements=tuple(disagreements),
        degraded_ai=False,
        model_version=model_version,
    )


def fail_soft_audit(
    *,
    requested_level: DecisionInfluenceLevel,
    reason: str,
    model_version: str,
    hard_constraints_passed: bool = False,
) -> DecisionAudit:
    return DecisionAudit(
        influence_level=DecisionInfluenceLevel.L0_COMMENTARY,
        requested_influence_level=requested_level,
        formal_influence=0.0,
        hard_constraints_passed=hard_constraints_passed,
        degraded_ai=True,
        failure_reason=reason,
        deterministic_fallback=True,
        model_version=model_version,
    )
