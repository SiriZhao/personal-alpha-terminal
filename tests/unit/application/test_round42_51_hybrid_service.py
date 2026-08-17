from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from personal_alpha_terminal.application.daily_result import (
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.application.hybrid_intelligence_service import (
    build_shadow_hybrid_document,
)


def test_shadow_hybrid_document_retains_all_eligible_securities() -> None:
    factors = (
        SimpleNamespace(
            symbol="AAA",
            rank=1,
            expected_alpha=0.03,
            components={"momentum": 0.2},
            evidence_coverage=0.9,
        ),
        SimpleNamespace(
            symbol="BBB",
            rank=2,
            expected_alpha=0.02,
            components={"quality": 0.1},
            evidence_coverage=0.8,
        ),
    )
    workflow = SimpleNamespace(
        factors=factors,
        target=SimpleNamespace(target_weights={"AAA": 0.05, "BBB": 0.04}),
        current_weights={"AAA": 0.02},
        recommendations=(
            SimpleNamespace(symbol="AAA", action="BUY"),
            SimpleNamespace(symbol="BBB", action="BUY"),
        ),
        probability_counterfactual={},
        decision_time=datetime(2026, 8, 17, 12, tzinfo=UTC),
        risk_regime="QUANT_NEUTRAL",
        data_freshness="CURRENT",
    )
    document = build_shadow_hybrid_document(
        workflow=workflow,
        llm_stage=StageResult(
            name="LLM_INTELLIGENCE",
            status=StageStatus.PASS_DEGRADED,
            duration_seconds=0.0,
            message="fixture",
            metadata={
                "provider": "fixture",
                "model": "fixture-v1",
                "connectivity": "AVAILABLE",
                "accepted_events": 0,
            },
        ),
    )
    securities = document["securities"]
    assert isinstance(securities, list)
    assert {item["symbol"] for item in securities} == {"AAA", "BBB"}
    assert all(item["applied_llm_adjustment"] == 0.0 for item in securities)
    status = document["status"]
    assert isinstance(status, dict)
    assert status["formal_economic_influence"] == 0.0
    invariants = document["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["pre_optimizer_top_n"] is None
    assert invariants["fixed_holdings_cap"] is None
    assert invariants["all_eligible_securities_retained"] is True
