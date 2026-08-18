"""ROUND63 auditable agentic decision-engine facade.

The engine produces structured preferences and alpha adjustments. It never
creates orders or bypasses the canonical optimizer and hard-risk validators.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Any

from pydantic import Field, ValidationError, field_validator, model_validator

from personal_alpha_terminal.agents.llm.providers import LLMProvider, LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest
from personal_alpha_terminal.core.fingerprints import canonical_json, fingerprint
from personal_alpha_terminal.intelligence.agentic_engine import fuse_alpha
from personal_alpha_terminal.intelligence.agentic_models import (
    AgenticStrictModel,
    AlphaAttribution,
    EventRecord,
    LLMInfluenceLevel,
    LLMInfluencePolicy,
    PromotionEvaluation,
    PromotionStatus,
    QuantThesis,
    SecurityIdentity,
    Stance,
)


class AgenticDecisionMode(StrEnum):
    SHADOW = "SHADOW"
    ALPHA_OVERLAY = "ALPHA_OVERLAY"
    FACTOR_META_CONTROLLER = "FACTOR_META_CONTROLLER"
    REGIME_CONTROLLER = "REGIME_CONTROLLER"
    FULL_AGENTIC_CHALLENGER = "FULL_AGENTIC_CHALLENGER"


class AgenticDecisionStatus(StrEnum):
    STRUCTURED = "STRUCTURED"
    FAIL_SOFT_QUANT_ONLY = "FAIL_SOFT_QUANT_ONLY"


class AgenticCandidatePacket(AgenticStrictModel):
    security: SecurityIdentity
    company_name: str
    business_description: str
    quant: QuantThesis
    probability_view: float | None = Field(default=None, ge=0, le=1)
    current_weight: float = Field(ge=0, le=1)
    events: tuple[EventRecord, ...] = ()
    news_freshness: float = Field(default=0.0, ge=0, le=1)
    uncertainty: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_candidate_lineage(self) -> AgenticCandidatePacket:
        if self.quant.security != self.security:
            raise ValueError("agentic candidate quant security identity mismatch")
        if any(event.security != self.security for event in self.events):
            raise ValueError("agentic candidate event security identity mismatch")
        return self


class AgenticDecisionPacket(AgenticStrictModel):
    schema_version: str = "agentic-decision-packet-v1"
    decision_timestamp: datetime
    information_cutoff: datetime
    universe_identity: str
    data_version: str
    quant_model_version: str
    probability_model_version: str | None = None
    market_state: dict[str, Any] = Field(default_factory=dict)
    benchmark_state: dict[str, Any] = Field(default_factory=dict)
    portfolio_state: dict[str, Any] = Field(default_factory=dict)
    risk_state: dict[str, Any] = Field(default_factory=dict)
    recent_model_behavior: dict[str, Any] = Field(default_factory=dict)
    quant_factor_mixture: dict[str, float] = Field(default_factory=dict)
    candidates: tuple[AgenticCandidatePacket, ...]
    quant_only_target: dict[str, float] = Field(default_factory=dict)
    quant_probability_target: dict[str, float] = Field(default_factory=dict)
    hard_constraints_hash: str

    @field_validator("decision_timestamp", "information_cutoff")
    @classmethod
    def validate_packet_times(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_temporal_and_information_boundary(self) -> AgenticDecisionPacket:
        if self.information_cutoff > self.decision_timestamp:
            raise ValueError("information cutoff cannot follow decision timestamp")
        if not self.candidates:
            raise ValueError("agentic decision packet requires candidates")
        security_ids = tuple(item.security.permanent_security_id for item in self.candidates)
        symbols = tuple(item.security.symbol for item in self.candidates)
        if len(set(security_ids)) != len(security_ids) or len(set(symbols)) != len(symbols):
            raise ValueError("agentic decision packet candidate identities must be unique")
        for candidate in self.candidates:
            if candidate.security.symbol_as_of_time > self.information_cutoff:
                raise ValueError("candidate identity is newer than information cutoff")
            if any(event.available_at > self.information_cutoff for event in candidate.events):
                raise ValueError("agentic decision packet contains future event evidence")
        allowed_symbols = set(symbols)
        for target in (self.quant_only_target, self.quant_probability_target):
            _validate_target(target, allowed_symbols, "agentic packet counterfactual target")
        for mixture_name, value in self.quant_factor_mixture.items():
            if not mixture_name.strip() or not isfinite(value) or value < 0:
                raise ValueError("quant factor mixture must be named, finite, and non-negative")
        _reject_forbidden_information(self.model_dump(mode="json"))
        return self


class AgenticMarketLayer(AgenticStrictModel):
    regime_probabilities: dict[str, float]
    risk_on_assessment: float = Field(ge=0, le=1)
    risk_off_assessment: float = Field(ge=0, le=1)
    breadth_interpretation: str
    trend_persistence: float = Field(ge=0, le=1)
    reversal_risk: float = Field(ge=0, le=1)
    volatility_regime: str
    liquidity_regime: str
    macro_event_risk: float = Field(ge=0, le=1)
    recommended_market_participation: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    known_facts: tuple[str, ...] = ()
    inferred_conclusions: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_regime_probabilities(self) -> AgenticMarketLayer:
        if not self.regime_probabilities:
            raise ValueError("market layer requires regime probabilities")
        if any(
            not name.strip() or not isfinite(value) or not 0 <= value <= 1
            for name, value in self.regime_probabilities.items()
        ):
            raise ValueError("regime probabilities must be named finite probabilities")
        if abs(sum(self.regime_probabilities.values()) - 1.0) > 1e-6:
            raise ValueError("regime probabilities must sum to one")
        return self


class AgenticStockLayer(AgenticStrictModel):
    symbol: str
    security: SecurityIdentity
    company_name: str
    business_description: str
    directional_view: Stance
    event_catalyst_score: float = Field(ge=-1, le=1)
    company_news_interpretation: str
    expected_horizon_sessions: int = Field(ge=1, le=252)
    confidence: float = Field(ge=0, le=1)
    positive_catalysts: tuple[str, ...] = ()
    negative_catalysts: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    news_freshness: float = Field(ge=0, le=1)
    quant_disagreement: float = Field(ge=0, le=1)
    recommended_alpha_adjustment: float
    evidence_event_ids: tuple[str, ...] = ()
    known_facts: tuple[str, ...] = ()
    inferred_conclusions: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()

    @field_validator("recommended_alpha_adjustment")
    @classmethod
    def alpha_adjustment_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("recommended alpha adjustment must be finite")
        return value

    @model_validator(mode="after")
    def validate_stock_identity(self) -> AgenticStockLayer:
        if self.symbol != self.security.symbol:
            raise ValueError("agentic stock output identity mismatch")
        return self


class AgenticPortfolioLayer(AgenticStrictModel):
    preferred_factor_mixture: dict[str, float] = Field(default_factory=dict)
    concentration_concern: str
    sector_concern: str
    diversification_interpretation: str
    preferred_gross: float = Field(ge=0, le=1)
    preferred_beta: float = Field(ge=0, le=2)
    preferred_cash: float = Field(ge=0, le=1)
    major_portfolio_risks: tuple[str, ...] = ()
    suggested_adds: tuple[str, ...] = ()
    suggested_reductions: tuple[str, ...] = ()
    target_preference_vector: dict[str, float] = Field(default_factory=dict)
    explicit_rationale: str
    known_facts: tuple[str, ...] = ()
    inferred_conclusions: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_preferences(self) -> AgenticPortfolioLayer:
        for mapping, name in (
            (self.preferred_factor_mixture, "factor mixture"),
            (self.target_preference_vector, "target preference vector"),
        ):
            if any(
                not key.strip() or not isfinite(value) or value < 0
                for key, value in mapping.items()
            ):
                raise ValueError(f"{name} must be named, finite, and non-negative")
        return self


class AgenticStructuredOutput(AgenticStrictModel):
    schema_version: str = "agentic-decision-output-v1"
    market: AgenticMarketLayer
    stocks: tuple[AgenticStockLayer, ...]
    portfolio: AgenticPortfolioLayer
    overall_confidence: float = Field(ge=0, le=1)
    known_facts: tuple[str, ...] = ()
    inferred_conclusions: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()


class AgenticCounterfactualTargetRecord(AgenticStrictModel):
    schema_version: str = "agentic-counterfactual-targets-v1"
    decision_timestamp: datetime
    information_cutoff: datetime
    universe_identity: str
    quant_only_target: dict[str, float]
    quant_probability_target: dict[str, float]
    quant_llm_target: dict[str, float]
    quant_probability_llm_target: dict[str, float]
    full_agentic_target: dict[str, float] | None = None
    final_validator_status: str
    manual_only: bool = True

    @field_validator("decision_timestamp", "information_cutoff")
    @classmethod
    def counterfactual_times(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_counterfactual_targets(self) -> AgenticCounterfactualTargetRecord:
        if self.information_cutoff > self.decision_timestamp:
            raise ValueError("counterfactual cutoff cannot follow decision time")
        if not self.manual_only:
            raise ValueError("agentic counterfactual targets must remain manual-only")
        symbols = set().union(
            self.quant_only_target,
            self.quant_probability_target,
            self.quant_llm_target,
            self.quant_probability_llm_target,
            self.full_agentic_target or {},
        )
        for target in (
            self.quant_only_target,
            self.quant_probability_target,
            self.quant_llm_target,
            self.quant_probability_llm_target,
            self.full_agentic_target,
        ):
            if target is None:
                continue
            _validate_target(target, symbols, "agentic counterfactual target")
        return self

    @property
    def record_hash(self) -> str:
        return fingerprint(self.model_dump(mode="json"))


class AgenticCounterfactualLedger:
    def __init__(self) -> None:
        self._records: dict[tuple[datetime, str], AgenticCounterfactualTargetRecord] = {}

    def append(self, record: AgenticCounterfactualTargetRecord) -> None:
        key = (record.decision_timestamp, record.universe_identity)
        existing = self._records.get(key)
        if existing is not None and existing.record_hash != record.record_hash:
            raise ValueError("refusing conflicting agentic counterfactual overwrite")
        self._records[key] = record

    def records(self) -> tuple[AgenticCounterfactualTargetRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


class AgenticDecisionResult(AgenticStrictModel):
    schema_version: str = "agentic-decision-result-v1"
    mode: AgenticDecisionMode
    status: AgenticDecisionStatus
    provider: str
    model: str
    model_version: str
    prompt_version: str
    prompt_hash: str
    decision_timestamp: datetime
    information_cutoff: datetime
    request_timestamp: datetime
    response_timestamp: datetime
    input_hash: str
    output_hash: str | None
    structured_output: AgenticStructuredOutput | None
    alpha_attribution: tuple[AlphaAttribution, ...]
    factor_mixture: dict[str, float]
    participation_preferences: dict[str, float]
    target_preference_vector: dict[str, float]
    calibrated_influence: float = Field(ge=0, le=1)
    formal_influence_active: bool
    fallback_reason: str | None = None
    optimizer_final_authority: bool = True
    auto_execution: str = "DISABLED"
    manual_confirmation: str = "ENABLED"
    counterfactual_targets_required: bool = True

    @model_validator(mode="after")
    def enforce_execution_boundary(self) -> AgenticDecisionResult:
        if not self.optimizer_final_authority:
            raise ValueError("optimizer must remain final authority")
        if self.auto_execution != "DISABLED" or self.manual_confirmation != "ENABLED":
            raise ValueError("agentic decision result must remain manual-only")
        if self.formal_influence_active and self.calibrated_influence <= 0:
            raise ValueError("formal influence requires positive calibrated influence")
        return self


class AgenticDecisionEngine:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        model_version: str,
        prompt_version: str = "agentic-decision-v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.model_version = model_version
        self.prompt_version = prompt_version
        self._clock = clock or (lambda: datetime.now(UTC))

    def decide(
        self,
        packet: AgenticDecisionPacket,
        *,
        mode: AgenticDecisionMode,
        influence_policy: LLMInfluencePolicy,
        promotion: PromotionEvaluation,
    ) -> AgenticDecisionResult:
        request_time = _aware(self._clock(), "request_timestamp")
        input_document = packet.model_dump(mode="json")
        input_hash = fingerprint(input_document)
        system_prompt = _system_prompt()
        prompt_hash = sha256(
            f"{self.prompt_version}|{system_prompt}".encode()
        ).hexdigest()
        request = LLMRequest(
            system_prompt=system_prompt,
            user_prompt=canonical_json(
                {
                    "mode": mode.value,
                    "packet": input_document,
                    "required_schema": AgenticStructuredOutput.model_json_schema(),
                }
            ),
            temperature=0.0,
            prompt_version=self.prompt_version,
            as_of=packet.information_cutoff,
            max_tokens=8192,
            thinking="enabled",
            reasoning_effort="high",
        )
        try:
            response = self.provider.generate(request)
            response_time = _aware(self._clock(), "response_timestamp")
            payload = json.loads(response.content)
            structured = AgenticStructuredOutput.model_validate(payload)
            self._validate_output(packet, structured)
        except LLMProviderError as error:
            return self._fallback(
                packet,
                mode=mode,
                request_time=request_time,
                response_time=_aware(self._clock(), "response_timestamp"),
                input_hash=input_hash,
                prompt_hash=prompt_hash,
                reason=f"PROVIDER:{error.category}",
            )
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as error:
            return self._fallback(
                packet,
                mode=mode,
                request_time=request_time,
                response_time=_aware(self._clock(), "response_timestamp"),
                input_hash=input_hash,
                prompt_hash=prompt_hash,
                reason=f"STRUCTURED_OUTPUT_INVALID:{type(error).__name__}",
            )

        calibrated = _calibrated_influence(
            structured,
            packet,
            mode=mode,
            policy=influence_policy,
            promotion=promotion,
        )
        active = calibrated > 0 and _mode_allowed(mode, influence_policy, promotion)
        effective_policy = influence_policy.model_copy(
            update={"lambda_value": calibrated if active else 0.0}
        )
        stock_by_symbol = {item.symbol: item for item in structured.stocks}
        alpha = tuple(
            fuse_alpha(
                symbol=candidate.security.symbol,
                mu_quant=candidate.quant.expected_alpha,
                delta_mu_event=stock_by_symbol[
                    candidate.security.symbol
                ].recommended_alpha_adjustment,
                policy=effective_policy,
                promotion=promotion,
                weight_quant_counterfactual=packet.quant_only_target.get(
                    candidate.security.symbol
                ),
            )
            for candidate in packet.candidates
        )
        factor_mixture = (
            _normalized_nonnegative(structured.portfolio.preferred_factor_mixture)
            if active and mode is AgenticDecisionMode.FACTOR_META_CONTROLLER
            else _normalized_nonnegative(packet.quant_factor_mixture)
        )
        participation = (
            {
                "gross": structured.portfolio.preferred_gross,
                "beta": structured.portfolio.preferred_beta,
                "cash": structured.portfolio.preferred_cash,
                "market_participation": structured.market.recommended_market_participation,
            }
            if active and mode is AgenticDecisionMode.REGIME_CONTROLLER
            else {}
        )
        preference_vector = (
            _normalized_nonnegative(structured.portfolio.target_preference_vector)
            if active and mode is AgenticDecisionMode.FULL_AGENTIC_CHALLENGER
            else {}
        )
        return AgenticDecisionResult(
            mode=mode,
            status=AgenticDecisionStatus.STRUCTURED,
            provider=response.provider,
            model=response.model,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            prompt_hash=prompt_hash,
            decision_timestamp=packet.decision_timestamp,
            information_cutoff=packet.information_cutoff,
            request_timestamp=request_time,
            response_timestamp=response_time,
            input_hash=input_hash,
            output_hash=sha256(response.content.encode("utf-8")).hexdigest(),
            structured_output=structured,
            alpha_attribution=alpha,
            factor_mixture=factor_mixture,
            participation_preferences=participation,
            target_preference_vector=preference_vector,
            calibrated_influence=calibrated if active else 0.0,
            formal_influence_active=active,
            fallback_reason=response.fallback_reason,
        )

    def _validate_output(
        self,
        packet: AgenticDecisionPacket,
        output: AgenticStructuredOutput,
    ) -> None:
        candidates = {item.security.symbol: item for item in packet.candidates}
        output_symbols = {item.symbol for item in output.stocks}
        if output_symbols != set(candidates):
            raise ValueError("structured LLM output must cover every candidate exactly once")
        known_events = {
            event.event_id
            for candidate in packet.candidates
            for event in candidate.events
        }
        for stock in output.stocks:
            candidate = candidates[stock.symbol]
            if stock.security != candidate.security:
                raise ValueError("structured LLM output security identity mismatch")
            if (
                stock.company_name != candidate.company_name
                or stock.business_description != candidate.business_description
            ):
                raise ValueError("structured LLM output company information mismatch")
            if any(event_id not in known_events for event_id in stock.evidence_event_ids):
                raise ValueError("structured LLM output cites unavailable event evidence")
        allowed_symbols = set(candidates)
        if any(
            symbol not in allowed_symbols
            for symbol in output.portfolio.target_preference_vector
        ):
            raise ValueError("target preference vector contains an unknown candidate")
        if any(symbol not in allowed_symbols for symbol in output.portfolio.suggested_adds):
            raise ValueError("suggested adds contain an unknown candidate")
        if any(symbol not in allowed_symbols for symbol in output.portfolio.suggested_reductions):
            raise ValueError("suggested reductions contain an unknown candidate")
        _reject_forbidden_information(output.model_dump(mode="json"))

    def _fallback(
        self,
        packet: AgenticDecisionPacket,
        *,
        mode: AgenticDecisionMode,
        request_time: datetime,
        response_time: datetime,
        input_hash: str,
        prompt_hash: str,
        reason: str,
    ) -> AgenticDecisionResult:
        return AgenticDecisionResult(
            mode=mode,
            status=AgenticDecisionStatus.FAIL_SOFT_QUANT_ONLY,
            provider=self.provider.name,
            model=self.provider.model,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            prompt_hash=prompt_hash,
            decision_timestamp=packet.decision_timestamp,
            information_cutoff=packet.information_cutoff,
            request_timestamp=request_time,
            response_timestamp=response_time,
            input_hash=input_hash,
            output_hash=None,
            structured_output=None,
            alpha_attribution=tuple(
                AlphaAttribution(
                    symbol=candidate.security.symbol,
                    mu_quant=candidate.quant.expected_alpha,
                    delta_mu_semantic_raw=0.0,
                    lambda_applied=0.0,
                    delta_mu_semantic_applied=0.0,
                    mu_final=candidate.quant.expected_alpha,
                    production_influence=0.0,
                    weight_quant_counterfactual=packet.quant_only_target.get(
                        candidate.security.symbol
                    ),
                )
                for candidate in packet.candidates
            ),
            factor_mixture=_normalized_nonnegative(packet.quant_factor_mixture),
            participation_preferences={},
            target_preference_vector={},
            calibrated_influence=0.0,
            formal_influence_active=False,
            fallback_reason=reason,
        )


def _system_prompt() -> str:
    return (
        "You are a structured decision challenger for a long-only US equity system. "
        "Use only the supplied packet and information cutoff. Separate known facts, "
        "inferences, unsupported claims, and missing information. Never invent facts, "
        "future outcomes, prices, returns, orders, or broker actions. Return one JSON "
        "object matching the supplied schema. Portfolio output is a preference vector "
        "only; the deterministic optimizer and hard-risk validators retain final authority."
    )


def _calibrated_influence(
    output: AgenticStructuredOutput,
    packet: AgenticDecisionPacket,
    *,
    mode: AgenticDecisionMode,
    policy: LLMInfluencePolicy,
    promotion: PromotionEvaluation,
) -> float:
    if not _mode_allowed(mode, policy, promotion):
        return 0.0
    stock_confidence = sum(item.confidence for item in output.stocks) / len(output.stocks)
    freshness = sum(item.news_freshness for item in output.stocks) / len(output.stocks)
    disagreement = sum(item.quant_disagreement for item in output.stocks) / len(output.stocks)
    packet_uncertainty = sum(item.uncertainty for item in packet.candidates) / len(
        packet.candidates
    )
    unsupported = len(output.unsupported_claims) + sum(
        len(item.unsupported_claims) for item in output.stocks
    )
    missing = len(output.missing_information) + sum(
        len(item.missing_information) for item in output.stocks
    )
    evidence_penalty = 1 / (1 + unsupported + 0.25 * missing)
    confidence = (
        output.overall_confidence
        * output.market.confidence
        * stock_confidence
        * max(0.0, 1 - packet_uncertainty)
        * max(0.0, 1 - 0.50 * disagreement)
        * evidence_penalty
    )
    return max(0.0, min(1.0, policy.formal_lambda(promotion) * confidence * freshness))


def _mode_allowed(
    mode: AgenticDecisionMode,
    policy: LLMInfluencePolicy,
    promotion: PromotionEvaluation,
) -> bool:
    if mode is AgenticDecisionMode.SHADOW:
        return False
    if not policy.enabled or promotion.status is not PromotionStatus.PROMOTION_PASS:
        return False
    levels = {
        AgenticDecisionMode.ALPHA_OVERLAY: {
            LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY,
            LLMInfluenceLevel.LEVEL_4_PORTFOLIO_CONTRIBUTION,
            LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE,
        },
        AgenticDecisionMode.FACTOR_META_CONTROLLER: {
            LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE,
        },
        AgenticDecisionMode.REGIME_CONTROLLER: {
            LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE,
        },
        AgenticDecisionMode.FULL_AGENTIC_CHALLENGER: {
            LLMInfluenceLevel.LEVEL_4_PORTFOLIO_CONTRIBUTION,
            LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE,
        },
    }
    return policy.level in levels.get(mode, set())


def _normalized_nonnegative(values: dict[str, float]) -> dict[str, float]:
    positive = {
        name: float(value)
        for name, value in values.items()
        if name.strip() and isfinite(value) and value > 0
    }
    total = sum(positive.values())
    return (
        {name: value / total for name, value in sorted(positive.items())}
        if total > 0
        else {}
    )


def _validate_target(target: dict[str, float], allowed: set[str], label: str) -> None:
    if any(symbol not in allowed for symbol in target):
        raise ValueError(f"{label} contains an unknown symbol")
    if any(not isfinite(value) or value < 0 for value in target.values()):
        raise ValueError(f"{label} must be finite and long-only")
    if sum(target.values()) > 1 + 1e-9:
        raise ValueError(f"{label} gross exposure exceeds one")


def _reject_forbidden_information(value: object, *, path: str = "root") -> None:
    forbidden = {
        "future_return",
        "forward_return",
        "future_price",
        "realized_outcome",
        "recommendation_outcome",
        "post_decision_earnings",
        "later_news",
    }
    sensitive = {
        "api_key",
        "secret",
        "credential",
        "password",
        "broker_account",
        "account_number",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in forbidden:
                raise ValueError(f"future outcome field is forbidden at {path}.{key}")
            if normalized in sensitive:
                raise ValueError(f"sensitive field is forbidden at {path}.{key}")
            _reject_forbidden_information(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_information(item, path=f"{path}[{index}]")


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value
