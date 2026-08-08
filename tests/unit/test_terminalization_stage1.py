from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.daily_result import (
    DecisionReadiness,
    StageStatus,
)
from personal_alpha_terminal.application.quant_daily_service import (
    TodayRecommendation,
    TodayResult,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import Portfolio
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    PipelineStage,
)
from personal_alpha_terminal.quant_engine.risk.budget import PortfolioRiskState
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyFactorSnapshot,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _authorization():
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 7),
        NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "fixture-adapter",
        ("source-a", "source-b"),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _actual_quant_output():
    rng = np.random.default_rng(11)
    market = rng.normal(0.0003, 0.009, 180)
    returns = pd.DataFrame(
        {
            symbol: 0.75 * market + rng.normal(0.0003, 0.006, 180)
            for symbol in SYMBOLS
        },
        index=pd.bdate_range("2025-11-24", periods=180),
    )
    benchmark = pd.Series(market, index=returns.index)
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            50_000_000 + index * 5_000_000,
            0.0,
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    signals = tuple(
        AlphaSignal(
            symbol,
            NOW - timedelta(hours=1),
            "medium_term_momentum",
            0.01 + index * 0.001,
            20,
            1.0,
            0.8,
            0.8,
            True,
            200,
            0.8,
            0.7,
            40.0,
            NOW + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    constraints = PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.60,
        maximum_cluster_weight=0.70,
        maximum_hhi=0.35,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=0.30,
        maximum_beta=1.2,
        maximum_turnover=0.90,
        maximum_size_exposure=0.80,
        no_trade_band=0.002,
        minimum_rebalance_weight=0.003,
        minimum_trade_value=50,
        risk_aversion=2.0,
        turnover_penalty=0.001,
        model_validation_id="locked-oos-fixture",
    )
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(constraints)
    )
    return pipeline.run(
        DailyQuantInput(
            _authorization(),
            NOW,
            signals,
            returns,
            benchmark,
            metadata,
            {},
            1_000_000,
            PortfolioRiskState(-0.01, 0.12, 0.0, 0.0, 0.25, 0.25),
            None,
            True,
            "universe-v1",
            "CERTIFIED",
        )
    )


def _workflow_result() -> TodayResult:
    output = _actual_quant_output()
    assert output.target is not None
    execution = NOW + timedelta(days=2)
    recommendations = tuple(
        TodayRecommendation(
            f"rec-{item.ticker}",
            item.ticker,
            "ADD" if item.action.value == "INCREASE" else item.action.value,
            item.current_weight,
            item.target_weight,
            item.delta_weight,
            100,
            item.estimated_cost,
            item.expected_alpha,
            item.confidence,
            "; ".join(item.counter_evidence),
            item.model_version,
            item.data_version,
            execution,
            execution + timedelta(days=7),
            item.estimated_trade_value,
            item.risk_contribution,
            item.reason,
            item.data_quality,
        )
        for item in output.trades
    )
    factors = tuple(
        StrategyFactorSnapshot(
            symbol,
            {"momentum": 0.8 - index * 0.1, "trend": 0.6},
            0.7 - index * 0.05,
            index + 1,
            0.01 + index * 0.001,
            0.8,
            "VALID",
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    return TodayResult(
        17,
        NOW,
        "POST_CLOSE_DECISION",
        "CERTIFIED_AS_OF_DECISION",
        "GENERATED",
        "APPROVED",
        "APPROVED",
        "TARGET_COMPUTED",
        "SCORE_UNAVAILABLE",
        sum(output.target.target_weights.values()),
        output.target.cash_weight,
        recommendations,
        None,
        (),
        (),
        "data-v1",
        "alpha-v1",
        "config-v1",
        output.stages,
        factors,
        output.risk,
        output.target,
        output.trades,
        1_000_000,
        {},
        NOW,
        len(SYMBOLS),
        ("source-a", "source-b"),
        ("quality",),
        "SPY",
        180,
        0.12,
        0.18,
    )


class _SafeDataService:
    def __init__(self, *_args, **_kwargs) -> None:
        self.manifest = SimpleNamespace(
            end_date=date(2026, 8, 7),
            missingness_summary={"overall": 0.0},
            provider_name="fixture-primary+fixture-secondary",
        )

    def get_data_readiness(self, **_kwargs):
        return SimpleNamespace(code="CERTIFIED", technical_reason="fixture certified")

    def latest_manifest(self):
        return self.manifest


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        runtime_profile="TEST",
        database_url="sqlite://",
        daily_pipeline_report_path=tmp_path / "daily.md",
        llm_provider="disabled",
    )


def test_actual_quant_pipeline_flows_to_terminal_without_recalculation(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    workflow = _workflow_result()
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: workflow,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    ).run(decision_time=NOW, refresh=False)

    assert result.decision_readiness is DecisionReadiness.READY
    assert result.llm_status == "OPTIONAL/OFFLINE"
    assert [(item.symbol, item.action) for item in result.final_decisions] == [
        (item.symbol, item.action) for item in workflow.recommendations
    ]
    execution_symbols = {leg.symbol for leg in result.execution_plan.legs}
    assert all(
        item.symbol in execution_symbols
        for item in result.final_decisions
        if item.action != "HOLD"
    )
    rendered = capture_daily_quant_result(result, width=120)
    narrow = capture_daily_quant_result(result, width=80)
    assert "FINAL VALIDATED DECISIONS" in rendered
    assert "CANDIDATE ≠ TRADE" in rendered
    for decision in result.final_decisions:
        assert decision.symbol in rendered
        assert decision.action in rendered
    assert "MANUAL EXECUTION REQUIRED" in rendered
    assert "TODAY SUMMARY" in narrow
    assert list((tmp_path / "runs").glob("*.json"))


def test_missing_portfolio_and_stale_data_fail_closed(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    missing = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "missing",
    ).run(decision_time=NOW, refresh=False)
    assert missing.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert not missing.final_decisions
    assert any("PORTFOLIO NOT INITIALIZED" in item for item in missing.blockers)
    assert missing.execution_plan.status == "BLOCKED"

    class _Stale(_SafeDataService):
        def get_data_readiness(self, **_kwargs):
            return SimpleNamespace(code="STALE", technical_reason="latest bar is stale")

    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService", _Stale
    )
    stale = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "stale",
    ).run(decision_time=NOW, refresh=False)
    assert stale.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert not stale.final_decisions
    assert next(item for item in stale.stages if item.name == "DATA").status is StageStatus.FAIL


def test_pit_or_risk_failure_never_reaches_execution_plan(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch
) -> None:
    with session_factory.begin() as session:
        session.add(Portfolio(name="Real Ledger", cash_balance=1_000_000))
    base = _workflow_result()
    blocked = replace(
        base,
        status="BLOCKED",
        recommendations=(),
        blockers=("PIT validation failed before risk model",),
        pipeline_stages=(
            PipelineStage("Data Quality Gate", "VALID", "CERTIFIED"),
            PipelineStage(
                "PIT Universe", "BLOCKED", "PIT validation failed before risk model"
            ),
        ),
        risk=None,
        target=None,
        trades=(),
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.DataService",
        _SafeDataService,
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.application.daily_orchestrator.ProductionDailyWorkflow.run",
        lambda _self, **_kwargs: blocked,
    )
    result = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "blocked",
    ).run(decision_time=NOW, refresh=False)

    assert result.decision_readiness is DecisionReadiness.NOT_ACTIONABLE
    assert result.final_decisions == ()
    assert result.execution_plan.legs == ()
    assert result.execution_plan.status == "BLOCKED"


def test_calendar_resolves_weekend_and_dst_without_llm_dependency(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    orchestrator = DailyQuantOrchestrator(
        session_factory,
        _settings(tmp_path),
        snapshot_root=tmp_path / "runs",
    )
    saturday = datetime(2026, 8, 8, 12, tzinfo=UTC)
    winter = datetime(2026, 1, 15, 15, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 14, tzinfo=UTC)
    saturday_state = orchestrator._calendar.classify(saturday)
    winter_state = orchestrator._calendar.classify(winter)
    summer_state = orchestrator._calendar.classify(summer)

    assert saturday_state.trade_date == date(2026, 8, 10)
    assert winter_state.timestamp_et.utcoffset() != summer_state.timestamp_et.utcoffset()
    assert _settings(tmp_path).llm_provider == "disabled"
