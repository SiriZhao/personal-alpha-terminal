"""ROUND 9: advisory service snapshot and terminal AI panel tests."""
from __future__ import annotations

from datetime import UTC, datetime

from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.quant_engine.llm_advisory import (
    AdvisoryIntelligenceService,
    DataAnomalyReport,
)
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _minimal_result(metadata: dict) -> DailyQuantResult:
    from datetime import date

    from personal_alpha_terminal.application.daily_result import (
        DecisionReadiness,
        ExecutionPlan,
        PortfolioSummary,
        RiskSummary,
    )

    return DailyQuantResult(
        run_id="r9-panel-test",
        version="1.1.0",
        started_at=NOW,
        finished_at=NOW,
        analysis_date=date(2026, 8, 12),
        trade_date=date(2026, 8, 13),
        market_session="CLOSED",
        market_structure="LEGACY_US_EQUITY",
        data_cutoff=NOW,
        decision_readiness=DecisionReadiness.READY,
        llm_status="SHADOW",
        stages=(StageResult("LLM_INTELLIGENCE", StageStatus.PASS_DEGRADED, 0.0, "ok", metadata),),
        data_health=(),
        market_regime="NOT_CALIBRATED",
        market_regime_detail="",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=PortfolioSummary("UNCHANGED", None, None, None, None, ()),
        risk=RiskSummary("BLOCKED", None, None, None, None, None, None, None, None, None, ()),
        final_decisions=(),
        rejected_signals=(),
        execution_plan=ExecutionPlan(
            "BLOCKED", True, "Charles Schwab (manual only)",
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, (),
        ),
        benchmarks=(),
        blockers=(),
        warnings=(),
        provenance={},
        config_hash="c",
        model_versions=(),
    )


def test_advisory_snapshot_status_and_quant_impact() -> None:
    service = AdvisoryIntelligenceService()
    service.record(
        DataAnomalyReport(
            classification="UNIVERSE_COLLAPSE",
            confidence=0.8,
            timestamp=NOW,
            source="market-data",
            model="advisory-v1",
            prompt_version="anomaly-v1",
            evidence=[],
            summary="Coverage dropped below threshold",
            anomaly_kind="UNIVERSE_COLLAPSE",
            severity="HIGH",
            affected_symbols=[],
        )
    )
    snapshot = service.snapshot(model="deepseek-chat", pit_documents=3, quant_impact="NONE")
    assert snapshot.status == "ADVISORY"
    assert snapshot.quant_impact == "NONE"
    assert snapshot.fallback == "CLASSICAL_CHAMPION"
    assert len(snapshot.anomalies) == 1
    doc = snapshot.document()
    assert doc["status"] == "ADVISORY"
    assert doc["anomalies"][0]["anomaly_kind"] == "UNIVERSE_COLLAPSE"


def test_advisory_snapshot_rejects_invalid_quant_impact() -> None:
    service = AdvisoryIntelligenceService()
    try:
        service.snapshot(model="m", pit_documents=0, quant_impact="PRODUCTION")
        raise AssertionError("expected invalid quant impact rejection")
    except ValueError:
        pass


def test_ai_panel_shows_advisory_status_quant_impact_and_fallback() -> None:
    metadata = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "processed_documents": 4,
        "detected_events": 6,
        "shadow_factor_observations": 6,
        "factor_status": "SHADOW",
        "production_influence": False,
        "fallback": "CLASSICAL_CHAMPION",
        "advisory_status": "ADVISORY",
        "advisory_quant_impact": "SHADOW",
    }
    result = _minimal_result(metadata)
    rendered = capture_daily_quant_result(result, locale="en-US")
    assert "AI INTELLIGENCE" in rendered
    assert "deepseek" in rendered
    assert "ADVISORY" in rendered
    assert "Quant impact" in rendered
    assert "SHADOW" in rendered
    assert "CLASSICAL_CHAMPION" in rendered
