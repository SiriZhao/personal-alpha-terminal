from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.intelligence.agentic_decision_engine import (
    AgenticCandidatePacket,
    AgenticCounterfactualLedger,
    AgenticCounterfactualTargetRecord,
    AgenticDecisionEngine,
    AgenticDecisionMode,
    AgenticDecisionPacket,
    AgenticDecisionStatus,
    AgenticMarketLayer,
    AgenticPortfolioLayer,
    AgenticStockLayer,
    AgenticStructuredOutput,
)
from personal_alpha_terminal.intelligence.agentic_models import (
    EventRecord,
    EventType,
    LLMInfluenceLevel,
    LLMInfluencePolicy,
    PromotionEvaluation,
    PromotionStatus,
    QuantThesis,
    SecurityIdentity,
    Stance,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(minutes=30)


class _Provider:
    name = "test-provider"
    model = "test-agentic-v1"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            latency_ms=7,
        )


class _FailingProvider(_Provider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        raise LLMProviderError("sanitized outage", category="PROVIDER_UNAVAILABLE")


def _identity(symbol: str) -> SecurityIdentity:
    return SecurityIdentity(
        permanent_security_id=f"US:XNAS:{symbol}",
        company_id=f"COMPANY:{symbol}",
        symbol=symbol,
        symbol_as_of_time=CUTOFF - timedelta(days=30),
    )


def _event(symbol: str, *, suffix: str = "1", available_at: datetime | None = None) -> EventRecord:
    identity = _identity(symbol)
    available = available_at or CUTOFF - timedelta(hours=2)
    return EventRecord(
        event_id=f"EVENT:{symbol}:{suffix}",
        symbol=symbol,
        company_id=identity.company_id,
        security=identity,
        event_type=EventType.PRODUCT,
        source_id=f"SOURCE:{symbol}:{suffix}",
        source_name="Unit Test Wire",
        source_type="STRUCTURED_NEWS",
        source_reliability_class="TEST",
        title=f"{symbol} launches product",
        summary="Known test event available before the decision cutoff.",
        published_at=available - timedelta(minutes=20),
        first_seen_at=available - timedelta(minutes=10),
        ingested_at=available,
        available_at=available,
        content_hash=f"content-{symbol}-{suffix}",
        source_hash=f"source-{symbol}-{suffix}",
    )


def _candidate(
    symbol: str,
    *,
    events: tuple[EventRecord, ...] | None = None,
) -> AgenticCandidatePacket:
    identity = _identity(symbol)
    expected = 0.02 if symbol == "AAA" else 0.01
    return AgenticCandidatePacket(
        security=identity,
        company_name=f"{symbol} Corp",
        business_description="A test-only US equity business description.",
        quant=QuantThesis(
            symbol=symbol,
            security=identity,
            quant_rank=1.0 if symbol == "AAA" else 2.0,
            expected_alpha=expected,
            factor_contributions={"momentum": expected * 0.6, "trend": expected * 0.4},
            uncertainty=0.10,
        ),
        probability_view=0.65 if symbol == "AAA" else 0.55,
        current_weight=0.05,
        events=events if events is not None else (_event(symbol),),
        news_freshness=0.90 if events != () else 0.0,
        uncertainty=0.10,
    )


def _packet(*, second_events: tuple[EventRecord, ...] | None = None) -> AgenticDecisionPacket:
    return AgenticDecisionPacket(
        decision_timestamp=NOW,
        information_cutoff=CUTOFF,
        universe_identity="ROUND63-UNIT-UNIVERSE",
        data_version="round63-unit-data",
        quant_model_version="alpha-engine3:research-only",
        probability_model_version="probability:research-only",
        market_state={"breadth": 0.62, "trend": "positive", "volatility": 0.18},
        benchmark_state={"symbol": "SPY", "beta_reference": 1.0},
        portfolio_state={"gross": 0.65, "cash": 0.35, "manual_only": True},
        risk_state={"allow_new_risk": True, "hard_constraints_valid": True},
        recent_model_behavior={"rank_ic": 0.05, "uncertainty": 0.20},
        quant_factor_mixture={"momentum": 0.5, "trend": 0.3, "low_volatility": 0.2},
        candidates=(
            _candidate("AAA"),
            _candidate("BBB", events=second_events),
        ),
        quant_only_target={"AAA": 0.08, "BBB": 0.06},
        quant_probability_target={"AAA": 0.09, "BBB": 0.05},
        hard_constraints_hash="hard-risk-v1",
    )


def _output(
    packet: AgenticDecisionPacket,
    *,
    unsupported_event: bool = False,
) -> AgenticStructuredOutput:
    stocks = []
    for candidate in packet.candidates:
        event_ids = tuple(item.event_id for item in candidate.events)
        if unsupported_event and candidate.security.symbol == "AAA":
            event_ids = ("INVENTED-EVENT",)
        has_news = bool(candidate.events)
        stocks.append(
            AgenticStockLayer(
                symbol=candidate.security.symbol,
                security=candidate.security,
                company_name=candidate.company_name,
                business_description=candidate.business_description,
                directional_view=Stance.BULLISH if has_news else Stance.NEUTRAL,
                event_catalyst_score=0.60 if has_news else 0.0,
                company_news_interpretation=(
                    "Supplied event supports the quantified catalyst."
                    if has_news
                    else "No current event evidence was supplied."
                ),
                expected_horizon_sessions=21,
                confidence=0.85 if has_news else 0.30,
                positive_catalysts=("Product catalyst",) if has_news else (),
                negative_catalysts=("Execution risk",),
                invalidation_conditions=("Catalyst does not appear in reported operations",),
                news_freshness=0.90 if has_news else 0.0,
                quant_disagreement=0.10,
                recommended_alpha_adjustment=0.03 if has_news else 0.0,
                evidence_event_ids=event_ids,
                known_facts=("Quant alpha is positive",),
                inferred_conclusions=("Catalyst may persist",) if has_news else (),
                unsupported_claims=(),
                missing_information=() if has_news else ("No current news evidence",),
            )
        )
    return AgenticStructuredOutput(
        market=AgenticMarketLayer(
            regime_probabilities={"RISK_ON": 0.65, "NEUTRAL": 0.25, "RISK_OFF": 0.10},
            risk_on_assessment=0.70,
            risk_off_assessment=0.15,
            breadth_interpretation="Breadth is constructive but not universal.",
            trend_persistence=0.72,
            reversal_risk=0.28,
            volatility_regime="NORMAL",
            liquidity_regime="NORMAL",
            macro_event_risk=0.25,
            recommended_market_participation=0.80,
            confidence=0.90,
            known_facts=("Supplied breadth is 0.62",),
            inferred_conclusions=("Risk-on evidence dominates",),
        ),
        stocks=tuple(stocks),
        portfolio=AgenticPortfolioLayer(
            preferred_factor_mixture={"momentum": 0.55, "trend": 0.30, "low_volatility": 0.15},
            concentration_concern="LOW",
            sector_concern="MODERATE",
            diversification_interpretation="Retain both candidates for optimizer review.",
            preferred_gross=0.82,
            preferred_beta=0.90,
            preferred_cash=0.18,
            major_portfolio_risks=("Event execution",),
            suggested_adds=("AAA",),
            suggested_reductions=("BBB",),
            target_preference_vector={"AAA": 0.65, "BBB": 0.35},
            explicit_rationale="Favor the stronger event-backed quant candidate.",
        ),
        overall_confidence=0.90,
        known_facts=("All candidates came from the quant packet",),
        inferred_conclusions=("AAA has stronger combined evidence",),
    )


def _promotion(status: PromotionStatus = PromotionStatus.PROMOTION_PASS) -> PromotionEvaluation:
    return PromotionEvaluation(
        status=status,
        observations=200,
        sample_n=200,
        paired_sample_n=200,
        unique_sessions=80,
        unique_symbols=50,
        unique_events=40,
        incremental_net_alpha=0.01 if status is PromotionStatus.PROMOTION_PASS else None,
    )


def _policy(level: LLMInfluenceLevel) -> LLMInfluencePolicy:
    return LLMInfluencePolicy(
        level=level,
        enabled=True,
        lambda_value=1.0,
        max_rank_shift=1.0,
        max_semantic_alpha_contribution=0.05,
        max_relative_alpha_adjustment=1.0,
        max_absolute_alpha_adjustment=0.05,
    )


def _engine(provider: _Provider) -> AgenticDecisionEngine:
    ticks = iter((NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
    return AgenticDecisionEngine(
        provider,
        model_version="round63-agentic-v1",
        prompt_version="round63-prompt-v1",
        clock=lambda: next(ticks),
    )


def test_shadow_mode_is_structured_auditable_and_has_zero_formal_influence() -> None:
    packet = _packet()
    provider = _Provider(json.dumps(_output(packet).model_dump(mode="json")))
    result = _engine(provider).decide(
        packet,
        mode=AgenticDecisionMode.SHADOW,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE),
        promotion=_promotion(),
    )
    assert result.status is AgenticDecisionStatus.STRUCTURED
    assert result.formal_influence_active is False
    assert result.calibrated_influence == 0.0
    assert all(item.mu_final == item.mu_quant for item in result.alpha_attribution)
    assert result.prompt_hash and result.input_hash and result.output_hash
    assert result.auto_execution == "DISABLED"
    assert result.manual_confirmation == "ENABLED"
    assert provider.requests[0].as_of == CUTOFF
    assert "future outcomes" in provider.requests[0].system_prompt


def test_identical_packet_and_provider_output_replay_identically() -> None:
    packet = _packet()
    content = json.dumps(_output(packet).model_dump(mode="json"))
    first = _engine(_Provider(content)).decide(
        packet,
        mode=AgenticDecisionMode.SHADOW,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE),
        promotion=_promotion(),
    )
    second = _engine(_Provider(content)).decide(
        packet,
        mode=AgenticDecisionMode.SHADOW,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE),
        promotion=_promotion(),
    )
    assert first.input_hash == second.input_hash
    assert first.prompt_hash == second.prompt_hash
    assert first.output_hash == second.output_hash
    assert first.alpha_attribution == second.alpha_attribution


def test_alpha_overlay_can_be_material_only_after_promotion_and_calibration() -> None:
    packet = _packet()
    provider = _Provider(json.dumps(_output(packet).model_dump(mode="json")))
    promoted = _engine(provider).decide(
        packet,
        mode=AgenticDecisionMode.ALPHA_OVERLAY,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY),
        promotion=_promotion(),
    )
    aaa = next(item for item in promoted.alpha_attribution if item.symbol == "AAA")
    assert promoted.formal_influence_active
    assert promoted.calibrated_influence > 0.30
    assert aaa.mu_final - aaa.mu_quant > 0.005

    blocked = _engine(_Provider(provider.content)).decide(
        packet,
        mode=AgenticDecisionMode.ALPHA_OVERLAY,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY),
        promotion=_promotion(PromotionStatus.PROMOTION_BLOCKED_SAMPLE),
    )
    assert blocked.formal_influence_active is False
    assert all(item.mu_final == item.mu_quant for item in blocked.alpha_attribution)


def test_factor_regime_and_full_modes_return_preferences_not_orders() -> None:
    packet = _packet()
    content = json.dumps(_output(packet).model_dump(mode="json"))
    policy = _policy(LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE)
    promotion = _promotion()

    factor = _engine(_Provider(content)).decide(
        packet,
        mode=AgenticDecisionMode.FACTOR_META_CONTROLLER,
        influence_policy=policy,
        promotion=promotion,
    )
    assert factor.factor_mixture["momentum"] == pytest.approx(0.55)
    assert factor.participation_preferences == {}

    regime = _engine(_Provider(content)).decide(
        packet,
        mode=AgenticDecisionMode.REGIME_CONTROLLER,
        influence_policy=policy,
        promotion=promotion,
    )
    assert regime.participation_preferences == {
        "gross": 0.82,
        "beta": 0.90,
        "cash": 0.18,
        "market_participation": 0.80,
    }

    full = _engine(_Provider(content)).decide(
        packet,
        mode=AgenticDecisionMode.FULL_AGENTIC_CHALLENGER,
        influence_policy=policy,
        promotion=promotion,
    )
    assert full.target_preference_vector == {"AAA": 0.65, "BBB": 0.35}
    assert "orders" not in full.model_dump(mode="json")
    assert full.optimizer_final_authority


def test_malformed_provider_outage_and_hallucinated_evidence_fail_soft() -> None:
    packet = _packet()
    malformed = _engine(_Provider("not-json")).decide(
        packet,
        mode=AgenticDecisionMode.FULL_AGENTIC_CHALLENGER,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_5_DYNAMIC_CONTEXTUAL_INFLUENCE),
        promotion=_promotion(),
    )
    assert malformed.status is AgenticDecisionStatus.FAIL_SOFT_QUANT_ONLY
    assert malformed.fallback_reason == "STRUCTURED_OUTPUT_INVALID:JSONDecodeError"
    assert malformed.target_preference_vector == {}

    outage = _engine(_FailingProvider("")).decide(
        packet,
        mode=AgenticDecisionMode.ALPHA_OVERLAY,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY),
        promotion=_promotion(),
    )
    assert outage.fallback_reason == "PROVIDER:PROVIDER_UNAVAILABLE"
    assert not outage.formal_influence_active

    hallucinated = _output(packet, unsupported_event=True)
    rejected = _engine(_Provider(json.dumps(hallucinated.model_dump(mode="json")))).decide(
        packet,
        mode=AgenticDecisionMode.ALPHA_OVERLAY,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY),
        promotion=_promotion(),
    )
    assert rejected.status is AgenticDecisionStatus.FAIL_SOFT_QUANT_ONLY
    assert rejected.fallback_reason == "STRUCTURED_OUTPUT_INVALID:ValueError"


def test_missing_news_reduces_influence_without_inventing_evidence() -> None:
    packet = _packet(second_events=())
    output = _output(packet)
    provider = _Provider(json.dumps(output.model_dump(mode="json")))
    result = _engine(provider).decide(
        packet,
        mode=AgenticDecisionMode.ALPHA_OVERLAY,
        influence_policy=_policy(LLMInfluenceLevel.LEVEL_3_BOUNDED_ALPHA_OVERLAY),
        promotion=_promotion(),
    )
    bbb = next(item for item in result.structured_output.stocks if item.symbol == "BBB")
    assert bbb.evidence_event_ids == ()
    assert bbb.missing_information == ("No current news evidence",)
    assert result.calibrated_influence < 0.30


def test_temporal_sensitive_and_future_outcome_fields_fail_closed() -> None:
    with pytest.raises(ValueError, match="future event evidence"):
        AgenticDecisionPacket(
            **{
                **_packet().model_dump(),
                "candidates": (
                    _candidate(
                        "AAA",
                        events=(
                            _event(
                                "AAA",
                                suffix="future",
                                available_at=CUTOFF + timedelta(seconds=1),
                            ),
                        ),
                    ),
                    _candidate("BBB"),
                ),
            }
        )
    with pytest.raises(ValueError, match="future outcome field"):
        AgenticDecisionPacket(
            **{
                **_packet().model_dump(),
                "market_state": {"future_return": 0.10},
            }
        )
    with pytest.raises(ValueError, match="sensitive field"):
        AgenticDecisionPacket(
            **{
                **_packet().model_dump(),
                "portfolio_state": {"api_key": "must-never-enter-prompt"},
            }
        )


def test_four_way_counterfactual_ledger_is_manual_long_only_and_immutable() -> None:
    record = AgenticCounterfactualTargetRecord(
        decision_timestamp=NOW,
        information_cutoff=CUTOFF,
        universe_identity="ROUND63-UNIT-UNIVERSE",
        quant_only_target={"AAA": 0.08, "BBB": 0.06},
        quant_probability_target={"AAA": 0.09, "BBB": 0.05},
        quant_llm_target={"AAA": 0.10, "BBB": 0.04},
        quant_probability_llm_target={"AAA": 0.11, "BBB": 0.03},
        full_agentic_target={"AAA": 0.12, "BBB": 0.02},
        final_validator_status="ALL_TARGETS_VALIDATED",
    )
    ledger = AgenticCounterfactualLedger()
    ledger.append(record)
    ledger.append(record)
    assert ledger.records() == (record,)
    conflicting = record.model_copy(
        update={"quant_llm_target": {"AAA": 0.12, "BBB": 0.04}}
    )
    with pytest.raises(ValueError, match="conflicting"):
        ledger.append(conflicting)
    with pytest.raises(ValueError, match="long-only"):
        AgenticCounterfactualTargetRecord(
            **{
                **record.model_dump(),
                "quant_llm_target": {"AAA": -0.01},
            }
        )
    with pytest.raises(ValueError, match="manual-only"):
        AgenticCounterfactualTargetRecord(
            **{**record.model_dump(), "manual_only": False}
        )
