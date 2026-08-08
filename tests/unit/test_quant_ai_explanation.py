from datetime import UTC, date, datetime

from personal_alpha_terminal.agents.llm.providers import MockProvider
from personal_alpha_terminal.quant_engine.ai_agent.explanation_agent import (
    ExplanationAgent,
    QuantDecisionPacket,
)
from personal_alpha_terminal.quant_engine.report.daily_report import DailyQuantReportBuilder


def test_ai_explains_but_cannot_override_deterministic_action() -> None:
    packet = QuantDecisionPacket(
        ticker="TEST",
        deterministic_action="WATCH",
        as_of_date=date(2026, 1, 10),
        factor_score=82,
        risk_score=65,
        regime_score=-20,
        evidence_grade="RESEARCH_ONLY",
        risk_factors=("high volatility",),
        source="certified-quant-db",
        source_ids=("factor:TEST:v1",),
    )
    explanation = ExplanationAgent(MockProvider()).explain(packet)

    assert explanation.deterministic_action == "WATCH"
    assert not explanation.ai_may_override_action
    assert explanation.report.is_mock


def test_blocked_daily_report_cannot_contain_decisions() -> None:
    try:
        DailyQuantReportBuilder().build(
            generated_at=datetime.now(UTC),
            data_gate_status="BLOCKED",
            market_regime_label="Waiting for Data",
            market_regime_is_calibrated=False,
            portfolio_health_score=None,
            decision_count=1,
            blockers=("data unavailable",),
            sources=(),
        )
    except ValueError as error:
        assert "blocked data gate" in str(error)
    else:
        raise AssertionError("blocked reports must fail closed")
