from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import cast

from rich.console import Console

from personal_alpha_terminal.application.agentic_shadow_service import (
    _round66_production_closure,
)
from personal_alpha_terminal.application.daily_result import DailyQuantResult
from personal_alpha_terminal.application.quant_daily_service import TodayResult
from personal_alpha_terminal.intelligence.agentic_models import (
    DebateDecision,
    HybridActionView,
    HybridIntelligenceStatus,
    HybridSecurityView,
)
from personal_alpha_terminal.terminal.daily_renderer import _hybrid_intelligence
from personal_alpha_terminal.terminal.hybrid_intelligence import (
    render_hybrid_intelligence,
)


def _security() -> HybridSecurityView:
    return HybridSecurityView(
        symbol="AAA",
        company_name="AAA Corporation",
        business_summary="Industrial software and services.",
        quant_rank=1.0,
        base_expected_alpha=0.02,
        probability_contribution=0.0,
        semantic_event_alpha=0.001,
        applied_llm_adjustment=0.0002,
        final_expected_alpha=0.0202,
        debate=DebateDecision.AGREE,
        confidence=0.80,
        expected_horizon_sessions=21,
        latest_event="Quarterly filing available at cutoff",
        bull_case="Demand remains resilient.",
        bear_case="Guidance can weaken.",
        catalysts=("New contract",),
        invalidation=("Margin deterioration",),
    )


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        current_weights={"AAA": 0.10},
        probability_counterfactual={
            "AAA": {
                "target_without_probability": 0.08,
                "target_with_probability": 0.09,
            }
        },
        probability_overlay_active=False,
        risk_state=None,
        target=None,
    )


def test_round66_closure_keeps_formal_influence_zero_and_hashes_counterfactuals() -> None:
    actions = [
        HybridActionView(
            symbol="AAA",
            current_weight=0.10,
            quant_only_target=0.08,
            hybrid_target=0.08,
            final_risk_adjusted_target=0.08,
            action="SELL",
        ).model_dump(mode="json")
    ]
    closure = _round66_production_closure(
        cast(TodayResult, _workflow()),
        target_weights={"AAA": 0.08},
        shadow_targets={"AAA": 0.07},
        securities=[_security()],
        actions=actions,
    )

    formal = closure["formal_influence"]
    ledger = closure["counterfactual_ledger"]
    rows = closure["decision_attribution"]
    assert isinstance(formal, dict)
    assert formal["quant"] == 1.0
    assert formal["probability"] == 0.0
    assert formal["llm"] == 0.0
    assert isinstance(ledger, dict)
    assert len({str(item["target_hash"]) for item in ledger.values()}) == 3
    assert isinstance(rows, list) and rows[0]["symbol"] == "AAA"
    assert rows[0]["risk_adjustment"] == 0.0


def test_round66_terminal_exposes_market_and_decision_attribution() -> None:
    stream = StringIO()
    console = Console(file=stream, width=140, color_system=None, force_terminal=False)
    status = HybridIntelligenceStatus(
        provider="disabled",
        model="none",
        data_freshness="PIT",
        event_intelligence="AVAILABLE",
        company_intelligence="AVAILABLE",
        market_intelligence="AVAILABLE",
        semantic_alpha="SHADOW_ACTIVE",
        promotion_gate="NO_FORWARD_EVIDENCE",
        formal_economic_influence=0.0,
    )
    closure = _round66_production_closure(
        cast(TodayResult, _workflow()),
        target_weights={"AAA": 0.08},
        shadow_targets={"AAA": 0.07},
        securities=[_security()],
        actions=[],
    )
    render_hybrid_intelligence(
        console,
        status=status,
        securities=(_security(),),
        production_closure=closure,
    )

    output = stream.getvalue()
    assert "ROUND66" in output
    assert "市场参与" in output
    assert "Decision Attribution" in output
    assert "Probability influence" in output
    assert "AAA Corporation" in output


def test_daily_renderer_wires_existing_hybrid_artifact_into_the_terminal() -> None:
    stream = StringIO()
    console = Console(file=stream, width=140, color_system=None, force_terminal=False)
    status = HybridIntelligenceStatus(
        provider="disabled",
        model="none",
        data_freshness="PIT",
        event_intelligence="DEGRADED",
        company_intelligence="DEGRADED",
        market_intelligence="DEGRADED",
        semantic_alpha="SHADOW_DEGRADED",
        promotion_gate="NO_FORWARD_EVIDENCE",
        formal_economic_influence=0.0,
    )
    document = {
        "status": status.model_dump(mode="json"),
        "securities": [_security().model_dump(mode="json")],
        "actions": [],
        "production_closure": _round66_production_closure(
            cast(TodayResult, _workflow()),
            target_weights={"AAA": 0.08},
            shadow_targets={"AAA": 0.07},
            securities=[_security()],
            actions=[],
        ),
    }

    _hybrid_intelligence(
        cast(DailyQuantResult, SimpleNamespace(hybrid_intelligence=document)),
        console,
    )

    assert "ROUND66" in stream.getvalue()
    assert "AAA Corporation" in stream.getvalue()
