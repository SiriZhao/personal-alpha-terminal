from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

import pytest
from rich.console import Console

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
    MarketIntelligenceSnapshot,
    QuantThesis,
)
from personal_alpha_terminal.terminal.hybrid_intelligence import (
    render_hybrid_intelligence,
)

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def test_hybrid_status_enforces_manual_only_boundary() -> None:
    with pytest.raises(ValueError, match="auto execution"):
        HybridIntelligenceStatus(
            provider="fixture",
            model="fixture-v1",
            data_freshness="CURRENT",
            event_intelligence="AVAILABLE",
            company_intelligence="AVAILABLE",
            market_intelligence="AVAILABLE",
            semantic_alpha="SHADOW",
            promotion_gate="PROMOTION_BLOCKED_SAMPLE",
            formal_economic_influence=0.0,
            auto_execution="ENABLED",
        )


def test_round51_renderer_shows_counterfactual_and_risk_wall() -> None:
    quant = QuantThesis(
        symbol="AAA",
        quant_rank=0.9,
        expected_alpha=0.028,
        uncertainty=0.2,
    )
    security = build_hybrid_security_view(
        quant=quant,
        thesis=None,
        debate=None,
        attribution=AlphaAttribution(
            symbol="AAA",
            mu_quant=0.028,
            delta_mu_semantic_raw=0.003,
            lambda_applied=0.0,
            delta_mu_semantic_applied=0.0,
            mu_final=0.028,
            production_influence=0.0,
        ),
        company_name="AAA Corporation",
        business_summary="Enterprise fixture business.",
        latest_event="No production-grounded event overlay.",
        influence_level=LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA,
    )
    assert security.debate is DebateDecision.INSUFFICIENT_INFORMATION
    action = HybridActionView(
        symbol="AAA",
        current_weight=0.02,
        quant_only_target=0.039,
        hybrid_target=0.039,
        final_risk_adjusted_target=0.035,
        action="BUY",
    )
    market = MarketIntelligenceSnapshot(
        as_of=NOW,
        quant_regime="QUANT_NEUTRAL",
        llm_interpreted_regime="MIXED",
        risk_on_score=0.4,
        risk_off_score=0.4,
        macro_uncertainty=0.5,
        market_event_score=0.3,
        regime_commentary="Context only.",
    )
    risk = portfolio_semantic_risk(
        ("AAA",),
        {"AAA": ("SINGLE_THEME",)},
        {},
        {"AAA": ("e1",)},
    )
    stream = StringIO()
    console = Console(file=stream, width=160, color_system=None)
    render_hybrid_intelligence(
        console,
        status=HybridIntelligenceStatus(
            provider="fixture",
            model="fixture-v1",
            data_freshness="CURRENT",
            event_intelligence="AVAILABLE",
            company_intelligence="AVAILABLE",
            market_intelligence="AVAILABLE",
            semantic_alpha="SHADOW",
            promotion_gate="PROMOTION_BLOCKED_SAMPLE",
            formal_economic_influence=0.0,
        ),
        securities=(security,),
        actions=(action,),
        market=market,
        portfolio_risk=risk,
    )
    output = stream.getvalue()
    assert "Formal Economic Influence" in output
    assert "0.00%" in output
    assert "Quant-only" in output
    assert "Final Risk-adjusted" in output
    assert "Optimizer + Risk Engine" in output
    assert "Pre-optimizer Top-N" in output
    assert "null" in output
    assert "组合语义风险" in output
