"""Typed contracts for the Agentic Quant Intelligence layer.

These contracts are additive.  They describe event and LLM evidence without
changing the deterministic quant, optimizer, portfolio, or risk semantics.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgenticStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


class EventType(StrEnum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    M_AND_A = "m_and_a"
    CAPITAL_RAISE = "capital_raise"
    BUYBACK = "buyback"
    DIVIDEND = "dividend"
    MANAGEMENT = "management"
    PRODUCT = "product"
    CONTRACT = "contract"
    REGULATORY = "regulatory"
    LITIGATION = "litigation"
    SEC_FILING = "sec_filing"
    ANALYST = "analyst"
    MACRO = "macro"
    SECTOR = "sector"
    GEOPOLITICAL = "geopolitical"
    OTHER = "other"


class LLMInfluenceLevel(StrEnum):
    LEVEL_0_EXPLANATION = "LEVEL_0_EXPLANATION"
    LEVEL_1_SHADOW_ALPHA = "LEVEL_1_SHADOW_ALPHA"
    LEVEL_2_DECISION_RANKING = "LEVEL_2_DECISION_RANKING"
    LEVEL_3_BOUNDED_ALPHA_OVERLAY = "LEVEL_3_BOUNDED_ALPHA_OVERLAY"
    LEVEL_4_PORTFOLIO_CONTRIBUTION = "LEVEL_4_PORTFOLIO_CONTRIBUTION"
    LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE = "LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE"


class Stance(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    AVOID = "AVOID"
    EXIT_EXISTING = "EXIT_EXISTING"


class DebateDecision(StrEnum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class SemanticAlphaStatus(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    SHADOW = "SHADOW"
    CALIBRATING = "CALIBRATING"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    INVALID_FIT = "INVALID_FIT"
    FAILED_CALIBRATION = "FAILED_CALIBRATION"
    PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
    REJECTED = "REJECTED"


class HistoricalLLMReplayStatus(StrEnum):
    NOT_HISTORICAL = "NOT_HISTORICAL"
    ENGINEERING_ONLY = "ENGINEERING_ONLY"


class PromotionStatus(StrEnum):
    PROMOTION_PASS = "PROMOTION_PASS"
    PROMOTION_BLOCKED_SAMPLE = "PROMOTION_BLOCKED_SAMPLE"
    PROMOTION_BLOCKED_PERFORMANCE = "PROMOTION_BLOCKED_PERFORMANCE"
    PROMOTION_BLOCKED_STABILITY = "PROMOTION_BLOCKED_STABILITY"
    PROMOTION_BLOCKED_LEAKAGE = "PROMOTION_BLOCKED_LEAKAGE"
    PROMOTION_BLOCKED_CALIBRATION = "PROMOTION_BLOCKED_CALIBRATION"


class SecurityIdentity(AgenticStrictModel):
    """Canonical identity; symbol is display metadata valid at a stated time."""

    permanent_security_id: str
    company_id: str
    symbol: str
    symbol_as_of_time: datetime

    @field_validator("permanent_security_id", "company_id", "symbol")
    @classmethod
    def security_identity_required(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("symbol_as_of_time")
    @classmethod
    def symbol_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "symbol_as_of_time")


class EventRecord(AgenticStrictModel):
    schema_version: str = "event-record-v1"
    event_id: str
    symbol: str | None = None
    company_id: str | None = None
    security: SecurityIdentity | None = None
    event_type: EventType
    source_id: str
    source_name: str
    source_type: str
    source_reliability_class: str
    title: str
    summary: str
    published_at: datetime
    first_seen_at: datetime
    ingested_at: datetime
    effective_from: datetime | None = None
    decision_cutoff: datetime | None = None
    available_at: datetime
    content_hash: str
    source_hash: str
    is_revision: bool = False
    parent_event_id: str | None = None
    event_language: str = "en"
    raw_payload_reference: str | None = None
    outcome_text: str | None = None

    @field_validator(
        "event_id",
        "schema_version",
        "source_id",
        "source_name",
        "source_type",
        "source_reliability_class",
        "title",
        "summary",
        "content_hash",
        "source_hash",
    )
    @classmethod
    def required_text(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator(
        "published_at",
        "first_seen_at",
        "ingested_at",
        "effective_from",
        "decision_cutoff",
        "available_at",
    )
    @classmethod
    def aware_timestamps(cls, value: datetime | None, info: Any) -> datetime | None:
        return _aware(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def validate_lineage(self) -> EventRecord:
        if self.first_seen_at < self.published_at:
            raise ValueError("first_seen_at cannot precede published_at")
        if self.ingested_at < self.first_seen_at:
            raise ValueError("ingested_at cannot precede first_seen_at")
        if self.available_at < self.first_seen_at:
            raise ValueError("available_at cannot precede first_seen_at")
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot follow ingested_at")
        if self.is_revision and not self.parent_event_id:
            raise ValueError("revisions require parent_event_id")
        if not self.is_revision and self.parent_event_id is not None:
            raise ValueError("non-revision events cannot have parent_event_id")
        if self.decision_cutoff is not None and self.available_at > self.decision_cutoff:
            raise ValueError("decision_cutoff cannot precede event availability")
        if self.outcome_text and any(
            token in self.outcome_text.casefold()
            for token in ("t+1", "t+5", "t+20", "forward return", "future price")
        ):
            raise ValueError("future outcome text cannot be stored in an event record")
        company_specific = self.event_type not in {
            EventType.MACRO,
            EventType.SECTOR,
            EventType.GEOPOLITICAL,
        }
        if company_specific and self.security is None:
            raise ValueError("company event requires canonical security identity")
        if self.security is not None:
            if self.symbol != self.security.symbol:
                raise ValueError("event symbol does not match canonical security identity")
            if self.company_id != self.security.company_id:
                raise ValueError("event company_id does not match canonical security identity")
            if self.security.symbol_as_of_time > self.available_at:
                raise ValueError("event symbol identity is newer than event availability")
        return self

    def visible_at(self, decision_time: datetime) -> bool:
        return self.available_at <= _aware(decision_time, "decision_time")


class EventIntelligenceFeatures(AgenticStrictModel):
    schema_version: str = "event-features-v1"
    direction: float = Field(ge=-1, le=1)
    magnitude: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    company_relevance: float = Field(ge=0, le=1)
    market_surprise: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    time_decay: float = Field(ge=0, le=1)
    expected_horizon_sessions: int = Field(ge=1, le=252)
    risk_flags: tuple[str, ...] = ()
    evidence_event_ids: tuple[str, ...] = ()


class EventSnapshot(AgenticStrictModel):
    schema_version: str = "event-snapshot-v1"
    decision_timestamp: datetime
    event_ids: tuple[str, ...]
    snapshot_hash: str

    @field_validator("decision_timestamp")
    @classmethod
    def snapshot_time(cls, value: datetime) -> datetime:
        return _aware(value, "decision_timestamp")


class LLMInferenceRecord(AgenticStrictModel):
    schema_version: str = "llm-inference-v1"
    inference_id: str
    provider: str
    model: str
    model_version: str | None = None
    prompt_version: str
    schema_version_used: str
    request_timestamp: datetime
    response_timestamp: datetime
    input_hash: str
    output_hash: str | None = None
    temperature: float = Field(ge=0, le=2)
    seed: int | None = None
    latency_ms: int = Field(ge=0)
    token_usage: dict[str, int] | None = None
    status: str
    error_code: str | None = None
    event_ids: tuple[str, ...] = ()
    parsed_output: dict[str, Any] | None = None
    concise_rationale: str | None = None
    evidence_references: tuple[str, ...] = ()

    @field_validator("request_timestamp", "response_timestamp")
    @classmethod
    def inference_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_response_order(self) -> LLMInferenceRecord:
        if self.response_timestamp < self.request_timestamp:
            raise ValueError("response_timestamp cannot precede request_timestamp")
        return self


class LLMCompanyThesis(AgenticStrictModel):
    schema_version: str = "company-thesis-v1"
    symbol: str
    security: SecurityIdentity
    stance: Stance
    confidence: float = Field(ge=0, le=1)
    event_direction: float = Field(ge=-1, le=1)
    event_magnitude: float = Field(ge=0, le=1)
    market_surprise: float = Field(ge=-1, le=1)
    novelty: float = Field(ge=0, le=1)
    company_relevance: float = Field(ge=0, le=1)
    expected_horizon_sessions: int = Field(ge=1, le=252)
    bull_case: str
    bear_case: str
    key_catalysts: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    evidence_event_ids: tuple[str, ...] = ()
    concise_rationale: str
    unsupported_claims: tuple[str, ...] = ()
    source_conflict: bool = False

    @model_validator(mode="after")
    def validate_thesis_security(self) -> LLMCompanyThesis:
        if self.symbol != self.security.symbol:
            raise ValueError("thesis symbol does not match canonical security identity")
        return self


class CompanyProfileSnapshot(AgenticStrictModel):
    schema_version: str = "company-profile-v1"
    symbol: str
    security: SecurityIdentity
    company_name: str
    business_description: str
    revenue_sources: tuple[str, ...] = ()
    industry: str
    as_of: datetime
    pit_status: str

    @field_validator("as_of")
    @classmethod
    def profile_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "as_of")

    @model_validator(mode="after")
    def validate_profile_security(self) -> CompanyProfileSnapshot:
        if self.symbol != self.security.symbol:
            raise ValueError("profile symbol does not match canonical security identity")
        if self.security.symbol_as_of_time > self.as_of:
            raise ValueError("profile symbol identity is newer than profile snapshot")
        return self


class QuantThesis(AgenticStrictModel):
    schema_version: str = "quant-thesis-v1"
    symbol: str
    security: SecurityIdentity | None = None
    quant_rank: float
    expected_alpha: float
    factor_contributions: dict[str, float] = {}
    momentum: float | None = None
    trend: float | None = None
    quality: float | None = None
    volatility: float | None = None
    probability_evidence: float | None = None
    liquidity: float | None = None
    risk_flags: tuple[str, ...] = ()
    uncertainty: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_quant_security(self) -> QuantThesis:
        if self.security is not None and self.symbol != self.security.symbol:
            raise ValueError("quant symbol does not match canonical security identity")
        return self


class LLMQuantDebate(AgenticStrictModel):
    schema_version: str = "quant-llm-debate-v1"
    symbol: str
    security: SecurityIdentity | None = None
    decision: DebateDecision
    agreement_strength: float = Field(ge=0, le=1)
    supporting_event_ids: tuple[str, ...] = ()
    contradicting_event_ids: tuple[str, ...] = ()
    semantic_adjustment_direction: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_debate_security(self) -> LLMQuantDebate:
        if self.security is not None and self.symbol != self.security.symbol:
            raise ValueError("debate symbol does not match canonical security identity")
        return self


class MarketIntelligenceSnapshot(AgenticStrictModel):
    schema_version: str = "market-intelligence-v1"
    as_of: datetime
    quant_regime: str
    llm_interpreted_regime: str
    risk_on_score: float = Field(ge=0, le=1)
    risk_off_score: float = Field(ge=0, le=1)
    macro_uncertainty: float = Field(ge=0, le=1)
    market_event_score: float = Field(ge=0, le=1)
    sector_context: tuple[str, ...] = ()
    regime_commentary: str = ""
    event_ids: tuple[str, ...] = ()

    @field_validator("as_of")
    @classmethod
    def market_time(cls, value: datetime) -> datetime:
        return _aware(value, "as_of")


class CompanyInformationPack(AgenticStrictModel):
    schema_version: str = "company-information-pack-v1"
    symbol: str
    security: SecurityIdentity
    decision_time: datetime
    company_profile: CompanyProfileSnapshot | None = None
    quant_evidence: QuantThesis
    recent_pit_events: tuple[EventRecord, ...] = ()
    current_holding_weight: float = Field(ge=0, le=1)
    sector_data: dict[str, Any] = {}
    market_context: MarketIntelligenceSnapshot | None = None

    @field_validator("decision_time")
    @classmethod
    def information_pack_time(cls, value: datetime) -> datetime:
        return _aware(value, "decision_time")

    @model_validator(mode="after")
    def validate_no_future_information(self) -> CompanyInformationPack:
        if self.symbol != self.security.symbol:
            raise ValueError("information pack symbol does not match security identity")
        if self.security.symbol_as_of_time > self.decision_time:
            raise ValueError("information pack security identity is newer than decision time")
        if self.quant_evidence.security != self.security:
            raise ValueError("quant evidence security identity mismatch")
        if (
            self.company_profile is not None
            and self.company_profile.security != self.security
        ):
            raise ValueError("company profile security identity mismatch")
        if any(event.security != self.security for event in self.recent_pit_events):
            raise ValueError("event security identity mismatch")
        if self.company_profile is not None and self.company_profile.as_of > self.decision_time:
            raise ValueError("company profile is newer than the decision cutoff")
        if any(not event.visible_at(self.decision_time) for event in self.recent_pit_events):
            raise ValueError("information pack contains a future event")
        if (
            self.market_context is not None
            and self.market_context.as_of > self.decision_time
        ):
            raise ValueError("market context is newer than the decision cutoff")
        forbidden = {
            "future_return",
            "forward_return",
            "t+1_return",
            "t+5_return",
            "t+20_return",
            "t+60_return",
            "future_price",
            "recommendation_outcome",
        }
        if any(str(key).casefold() in forbidden for key in self.sector_data):
            raise ValueError("information pack contains future outcome data")
        return self


class ForwardPrediction(AgenticStrictModel):
    schema_version: str = "forward-prediction-v1"
    prediction_id: str
    symbol: str
    security: SecurityIdentity
    prediction_time: datetime
    information_cutoff: datetime | None = None
    universe_identity: str | None = None
    evaluation_horizon: str | None = None
    execution_assumptions_hash: str | None = None
    transaction_cost_model: str | None = None
    slippage_model: str | None = None
    benchmark_convention: str | None = None
    data_version: str | None = None
    raw_event_score: float
    delta_mu_event: float
    status: SemanticAlphaStatus
    event_ids: tuple[str, ...] = ()
    event_cluster_ids: tuple[str, ...] = ()
    historical_llm_replay: bool = False
    historical_replay_status: HistoricalLLMReplayStatus = (
        HistoricalLLMReplayStatus.NOT_HISTORICAL
    )
    confidence: float = Field(default=0.0, ge=0, le=1)

    @field_validator("prediction_time")
    @classmethod
    def prediction_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "prediction_time")

    @field_validator("information_cutoff")
    @classmethod
    def information_cutoff_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value, "information_cutoff") if value is not None else None

    @field_validator(
        "universe_identity",
        "evaluation_horizon",
        "execution_assumptions_hash",
        "transaction_cost_model",
        "slippage_model",
        "benchmark_convention",
        "data_version",
    )
    @classmethod
    def optional_pairing_identity_required(
        cls,
        value: str | None,
        info: Any,
    ) -> str | None:
        return _required(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def bind_historical_replay_status(self) -> ForwardPrediction:
        if self.symbol != self.security.symbol:
            raise ValueError("prediction symbol does not match canonical security identity")
        if self.security.symbol_as_of_time > self.prediction_time:
            raise ValueError("prediction security identity is newer than prediction time")
        expected = (
            HistoricalLLMReplayStatus.ENGINEERING_ONLY
            if self.historical_llm_replay
            else HistoricalLLMReplayStatus.NOT_HISTORICAL
        )
        if self.historical_replay_status is not expected:
            object.__setattr__(self, "historical_replay_status", expected)
        if (
            self.information_cutoff is not None
            and self.information_cutoff > self.prediction_time
        ):
            raise ValueError("information_cutoff cannot follow prediction_time")
        return self


class ForwardOutcome(AgenticStrictModel):
    schema_version: str = "forward-outcome-v1"
    prediction_id: str
    security: SecurityIdentity
    outcome_time: datetime
    horizons: dict[str, float]
    excess_returns: dict[str, float] = {}
    transaction_cost_aware_returns: dict[str, float] = {}
    event_cluster_id: str | None = None

    @field_validator("outcome_time")
    @classmethod
    def outcome_time_aware(cls, value: datetime) -> datetime:
        return _aware(value, "outcome_time")


class CounterfactualPortfolioSnapshot(AgenticStrictModel):
    schema_version: str = "counterfactual-portfolio-v1"
    session: datetime
    information_cutoff: datetime
    universe_identity: str
    evaluation_horizon: str
    execution_assumptions_hash: str
    transaction_cost_model: str
    slippage_model: str
    benchmark_convention: str
    data_version: str
    security_ids: tuple[str, ...]
    regime: str
    cluster_id: str | None = None
    quant_gross_return: float
    quant_net_return: float
    quant_cost: float = Field(ge=0)
    quant_turnover: float = Field(ge=0)
    quant_drawdown: float = Field(ge=0)
    hybrid_gross_return: float
    hybrid_net_return: float
    hybrid_cost: float = Field(ge=0)
    hybrid_turnover: float = Field(ge=0)
    hybrid_drawdown: float = Field(ge=0)
    benchmark_return: float
    quant_exposures: dict[str, float] = {}
    hybrid_exposures: dict[str, float] = {}

    @field_validator("session", "information_cutoff")
    @classmethod
    def counterfactual_times_aware(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "universe_identity",
        "evaluation_horizon",
        "execution_assumptions_hash",
        "transaction_cost_model",
        "slippage_model",
        "benchmark_convention",
        "data_version",
        "regime",
    )
    @classmethod
    def counterfactual_identity_required(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator(
        "quant_gross_return",
        "quant_net_return",
        "quant_cost",
        "quant_turnover",
        "quant_drawdown",
        "hybrid_gross_return",
        "hybrid_net_return",
        "hybrid_cost",
        "hybrid_turnover",
        "hybrid_drawdown",
        "benchmark_return",
    )
    @classmethod
    def counterfactual_values_finite(cls, value: float, info: Any) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @model_validator(mode="after")
    def validate_counterfactual_pairing(self) -> CounterfactualPortfolioSnapshot:
        if self.information_cutoff > self.session:
            raise ValueError("information_cutoff cannot follow decision session")
        if not self.security_ids:
            raise ValueError("counterfactual security_ids cannot be empty")
        if len(set(self.security_ids)) != len(self.security_ids):
            raise ValueError("counterfactual security_ids must be unique")
        if any(not value.strip() for value in self.security_ids):
            raise ValueError("counterfactual security_ids cannot contain empty values")
        return self


class PromotionEvaluation(AgenticStrictModel):
    schema_version: str = "promotion-evaluation-v1"
    status: PromotionStatus
    observations: int
    sample_n: int = 0
    paired_sample_n: int = 0
    unique_sessions: int
    unique_symbols: int
    unique_events: int
    incremental_net_alpha: float | None = None
    median_incremental_net_alpha: float | None = None
    bootstrap_ci_low: float | None = None
    bootstrap_ci_high: float | None = None
    incremental_hit_rate: float | None = None
    benchmark_adjusted_alpha: float | None = None
    incremental_turnover: float | None = None
    incremental_cost: float | None = None
    hybrid_drawdown_increase: float | None = None
    regime_stability: bool | None = None
    directional_accuracy: float | None = None
    confidence_calibration_error: float | None = None
    reasons: tuple[str, ...] = ()


class LLMPromotionPolicy(AgenticStrictModel):
    schema_version: str = "llm-promotion-policy-v1"
    minimum_forward_observations: int = Field(default=120, ge=1)
    minimum_unique_symbols: int = Field(default=30, ge=1)
    minimum_unique_sessions: int = Field(default=40, ge=1)
    minimum_unique_events: int = Field(default=10, ge=1)
    minimum_incremental_net_alpha: float = 0.0
    minimum_confidence_bound: float = 0.0
    require_ci_low_non_negative: bool = True
    require_monotonicity: bool = True
    require_subperiod_stability: bool = True
    maximum_incremental_turnover: float = Field(default=0.05, ge=0)
    maximum_hybrid_drawdown_increase: float = Field(default=0.02, ge=0)
    minimum_directional_accuracy: float = Field(default=0.5, ge=0, le=1)
    maximum_confidence_calibration_error: float = Field(default=0.2, ge=0, le=1)


class LLMInfluencePolicy(AgenticStrictModel):
    schema_version: str = "llm-influence-policy-v1"
    level: LLMInfluenceLevel = LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA
    enabled: bool = False
    lambda_value: float = Field(default=0.0, ge=0, le=1)
    max_rank_shift: float = Field(default=0.0, ge=0)
    max_semantic_alpha_contribution: float = Field(default=0.0, ge=0)
    max_relative_alpha_adjustment: float = Field(default=0.0, ge=0)
    max_absolute_alpha_adjustment: float = Field(default=0.0, ge=0)

    def formal_lambda(self, promotion: PromotionEvaluation) -> float:
        if not self.enabled or promotion.status is not PromotionStatus.PROMOTION_PASS:
            return 0.0
        if self.level not in {
            LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY,
            LLMInfluenceLevel.LEVEL_4_PORTFOLIO_CONTRIBUTION,
            LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE,
        }:
            return 0.0
        return self.lambda_value


class AlphaAttribution(AgenticStrictModel):
    schema_version: str = "alpha-attribution-v1"
    symbol: str
    mu_quant: float
    delta_mu_semantic_raw: float
    lambda_applied: float
    delta_mu_semantic_applied: float
    mu_final: float
    production_influence: float
    weight_quant_counterfactual: float | None = None
    weight_hybrid: float | None = None
    recommendation_quant: str | None = None
    recommendation_hybrid: str | None = None


class DecisionAttribution(AgenticStrictModel):
    schema_version: str = "decision-attribution-v1"
    symbol: str
    quant_rank: float
    hybrid_rank: float
    shift: float
    why_shifted: str
    event_ids: tuple[str, ...] = ()
    influence_level: LLMInfluenceLevel = LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA


class PortfolioSemanticRiskReport(AgenticStrictModel):
    schema_version: str = "portfolio-semantic-risk-v1"
    common_theme_clusters: dict[str, tuple[str, ...]] = {}
    dependency_clusters: dict[str, tuple[str, ...]] = {}
    shared_catalysts: dict[str, tuple[str, ...]] = {}
    shared_risks: dict[str, tuple[str, ...]] = {}
    semantic_concentration_score: float = Field(ge=0, le=1)
    portfolio_narrative: str
    confidence: float = Field(ge=0, le=1)
    evidence_event_ids: tuple[str, ...] = ()


class HybridSecurityView(AgenticStrictModel):
    schema_version: str = "hybrid-security-view-v1"
    symbol: str
    company_name: str
    business_summary: str
    quant_rank: float
    base_expected_alpha: float
    probability_contribution: float | None
    semantic_event_alpha: float
    applied_llm_adjustment: float
    final_expected_alpha: float
    debate: DebateDecision
    confidence: float
    expected_horizon_sessions: int | None
    latest_event: str | None
    bull_case: str | None
    bear_case: str | None
    catalysts: tuple[str, ...] = ()
    invalidation: tuple[str, ...] = ()
    semantic_risk: str | None = None
    influence_level: LLMInfluenceLevel = LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA
    production_influence: float = 0.0


class HybridActionView(AgenticStrictModel):
    schema_version: str = "hybrid-action-view-v1"
    symbol: str
    current_weight: float
    quant_only_target: float
    hybrid_target: float
    final_risk_adjusted_target: float
    action: str
    optimizer_is_final_authority: bool = True

    @model_validator(mode="after")
    def enforce_optimizer_authority(self) -> HybridActionView:
        if not self.optimizer_is_final_authority:
            raise ValueError("optimizer must remain the final position-weight authority")
        return self


class HybridIntelligenceStatus(AgenticStrictModel):
    schema_version: str = "hybrid-intelligence-status-v1"
    provider: str
    model: str
    data_freshness: str
    event_intelligence: str
    company_intelligence: str
    market_intelligence: str
    semantic_alpha: str
    promotion_gate: str
    formal_economic_influence: float = Field(ge=0)
    auto_execution: str = "DISABLED"
    manual_confirmation: str = "ENABLED"
    pre_optimizer_top_n: None = None
    fixed_holdings_cap: None = None

    @model_validator(mode="after")
    def enforce_permanent_safety_boundary(self) -> HybridIntelligenceStatus:
        if self.auto_execution != "DISABLED":
            raise ValueError("auto execution must remain disabled")
        if self.manual_confirmation != "ENABLED":
            raise ValueError("manual confirmation must remain enabled")
        return self
