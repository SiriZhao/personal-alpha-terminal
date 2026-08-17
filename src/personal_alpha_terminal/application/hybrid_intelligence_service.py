"""Build the daily hybrid-intelligence artifact without changing decisions."""

from __future__ import annotations

from personal_alpha_terminal.application.daily_result import StageResult
from personal_alpha_terminal.application.quant_daily_service import TodayResult
from personal_alpha_terminal.intelligence.agentic_engine import (
    build_hybrid_security_view,
    portfolio_semantic_risk,
)
from personal_alpha_terminal.intelligence.agentic_models import (
    AlphaAttribution,
    DebateDecision,
    HybridActionView,
    HybridIntelligenceStatus,
    LLMInfluenceLevel,
    LLMQuantDebate,
    MarketIntelligenceSnapshot,
    QuantThesis,
)


def build_shadow_hybrid_document(
    *,
    workflow: TodayResult,
    llm_stage: StageResult | None,
) -> dict[str, object]:
    """Materialize all optimizer-eligible symbols with zero formal LLM alpha.

    ROUND42-51 engineering exists before promotion evidence exists.  This
    builder therefore records the complete quant counterfactual and SHADOW LLM
    state, while making the hybrid target equal to the already-computed formal
    target.  It never calls an LLM and never recomputes an optimizer target.
    """

    metadata = llm_stage.metadata if llm_stage is not None else {}
    provider = str(metadata.get("provider", "UNAVAILABLE"))
    model = str(metadata.get("model", "UNAVAILABLE"))
    connectivity = str(metadata.get("connectivity", "NOT_TESTED"))
    event_status = (
        "AVAILABLE"
        if int(str(metadata.get("accepted_events", 0)) or 0) > 0
        else "DEGRADED"
    )
    target_weights = workflow.target.target_weights if workflow.target is not None else {}
    current_weights = workflow.current_weights or {}
    probability = workflow.probability_counterfactual
    factors = tuple(sorted(workflow.factors, key=lambda item: (item.rank, item.symbol)))
    securities = []
    for factor in factors:
        trace = probability.get(factor.symbol, {})
        probability_contribution = trace.get("probability_weight_impact")
        quant = QuantThesis(
            symbol=factor.symbol,
            quant_rank=float(factor.rank),
            expected_alpha=float(factor.expected_alpha),
            factor_contributions={
                name: float(value) for name, value in factor.components.items()
            },
            risk_flags=(),
            uncertainty=max(0.0, min(1.0, 1.0 - float(factor.evidence_coverage))),
        )
        debate = LLMQuantDebate(
            symbol=factor.symbol,
            decision=DebateDecision.INSUFFICIENT_INFORMATION,
            agreement_strength=0.0,
            semantic_adjustment_direction=0.0,
            confidence=0.0,
            reason_codes=("SHADOW_NO_GROUNDED_COMPANY_THESIS",),
        )
        attribution = AlphaAttribution(
            symbol=factor.symbol,
            mu_quant=float(factor.expected_alpha),
            delta_mu_semantic_raw=0.0,
            lambda_applied=0.0,
            delta_mu_semantic_applied=0.0,
            mu_final=float(factor.expected_alpha),
            production_influence=0.0,
        )
        securities.append(
            build_hybrid_security_view(
                quant=quant,
                thesis=None,
                debate=debate,
                attribution=attribution,
                company_name="UNAVAILABLE",
                business_summary="PIT company profile unavailable for this run.",
                latest_event=None,
                probability_contribution=(
                    float(probability_contribution)
                    if isinstance(probability_contribution, (int, float))
                    else None
                ),
                influence_level=LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA,
            )
        )
    action_by_symbol = {
        item.symbol: item.action for item in workflow.recommendations
    }
    actions: list[HybridActionView] = []
    for symbol in sorted(set(current_weights) | set(target_weights)):
        trace = probability.get(symbol, {})
        raw_quant_target = trace.get(
            "target_with_probability", target_weights.get(symbol, 0.0)
        )
        quant_target = (
            float(raw_quant_target)
            if isinstance(raw_quant_target, (int, float))
            else float(target_weights.get(symbol, 0.0))
        )
        actions.append(
            HybridActionView(
                symbol=symbol,
                current_weight=float(current_weights.get(symbol, 0.0)),
                quant_only_target=quant_target,
                hybrid_target=float(target_weights.get(symbol, 0.0)),
                final_risk_adjusted_target=float(target_weights.get(symbol, 0.0)),
                action=action_by_symbol.get(symbol, "HOLD"),
            )
        )
    market = MarketIntelligenceSnapshot(
        as_of=workflow.decision_time,
        quant_regime=workflow.risk_regime,
        llm_interpreted_regime="INSUFFICIENT_INFORMATION",
        risk_on_score=0.0,
        risk_off_score=0.0,
        macro_uncertainty=0.0,
        market_event_score=0.0,
        regime_commentary=(
            "No grounded promoted market interpretation; Quant regime remains authoritative."
        ),
    )
    semantic_risk = portfolio_semantic_risk(
        tuple(sorted(set(current_weights) | set(target_weights))),
        {},
        {},
        {},
    )
    status = HybridIntelligenceStatus(
        provider=provider,
        model=model,
        data_freshness=workflow.data_freshness,
        event_intelligence=event_status,
        company_intelligence="DEGRADED",
        market_intelligence=(
            "DEGRADED" if connectivity != "AVAILABLE" else "AVAILABLE"
        ),
        semantic_alpha="SHADOW",
        promotion_gate="PROMOTION_BLOCKED_SAMPLE",
        formal_economic_influence=0.0,
    )
    return {
        "schema_version": "hybrid-intelligence-artifact-v1",
        "status": status.model_dump(mode="json"),
        "securities": [item.model_dump(mode="json") for item in securities],
        "actions": [item.model_dump(mode="json") for item in actions],
        "market": market.model_dump(mode="json"),
        "portfolio_semantic_risk": semantic_risk.model_dump(mode="json"),
        "decision_attribution": {
            "quant_only": "persisted deterministic quant target",
            "hybrid": "identical while semantic alpha is SHADOW",
            "llm_formal_influence": 0.0,
            "optimizer_final_authority": True,
        },
        "invariants": {
            "long_only": True,
            "auto_execution": False,
            "manual_confirmation": True,
            "llm_cannot_bypass_risk": True,
            "pre_optimizer_top_n": None,
            "fixed_holdings_cap": None,
            "all_eligible_securities_retained": len(securities) == len(factors),
        },
    }
