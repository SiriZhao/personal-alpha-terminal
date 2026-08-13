"""ROUND 12.1 live decision, portfolio, probability, and runtime semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np

from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    DecisionReadiness,
    DecisionRow,
    ExecutionPlan,
    PortfolioSummary,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.application.size_diagnostics import build_size_tilt_diagnostic
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.candidates import compress_candidates
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioConstraints
from personal_alpha_terminal.quant_engine.portfolio.trades import (
    TradeAction,
    TradeEvidence,
    TradeProposal,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    RiskModelStatus,
    SizeExposureStatus,
)
from personal_alpha_terminal.terminal.cli import build_parser
from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result

NOW = datetime(2026, 8, 12, 20, 30, tzinfo=UTC)


def _signal(symbol: str, alpha: float) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=NOW,
        signal_type="quality",
        expected_excess_return=alpha,
        horizon=21,
        raw_signal=alpha,
        normalized_signal=alpha,
        confidence=0.7,
        confidence_calibrated=False,
        sample_size=250,
        statistical_strength=0.8,
        economic_strength=0.8,
        decay_half_life=21,
        valid_until=NOW + timedelta(days=7),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED,
        model_version="alpha-v1",
        data_version="data-v1",
    )


def _result_with_decision(confidence: float | None) -> DailyQuantResult:
    stages = tuple(
        StageResult(name, StageStatus.PASS, 0.0, "ok", {})
        for name in (
            "CALENDAR",
            "DATA",
            "PIT",
            "LLM_INTELLIGENCE",
            "FEATURE",
            "FACTOR",
            "SIGNAL",
            "PROBABILITY",
            "PORTFOLIO",
            "RISK",
            "DECISION",
            "EXECUTION",
        )
    )
    decision = DecisionRow(
        recommendation_id="rec-1",
        symbol="AAPL",
        action="BUY",
        current_weight=0.0,
        target_weight=0.05,
        delta_weight=0.05,
        estimated_value=5000.0,
        estimated_quantity=25,
        estimated_cost=1.0,
        expected_alpha=0.03,
        confidence=confidence,
        risk_contribution=0.2,
        reason="validated expected alpha",
        data_quality="VALID",
        model_version="alpha-v1",
        data_version="data-v1",
        earliest_execution_time=NOW + timedelta(days=1),
        expiry=NOW + timedelta(days=8),
        confidence_source="NOT_CALIBRATED",
    )
    execution = ExecutionPlan(
        status="READY",
        manual_execution_required=True,
        broker="Charles Schwab",
        estimated_cash_before=100_000.0,
        estimated_proceeds=0.0,
        estimated_buys=5000.0,
        estimated_cash_after=94_999.0,
        turnover=0.05,
        estimated_cost=1.0,
        legs=(),
        execution_plan_generated=True,
        broker_order_submitted=False,
        broker_api="DISABLED",
        execution_mode="MANUAL_ONLY",
    )
    return DailyQuantResult(
        run_id="run-1",
        version="1",
        started_at=NOW,
        finished_at=NOW,
        analysis_date=NOW.date(),
        trade_date=NOW.date(),
        market_session="REGULAR",
        market_structure="US",
        data_cutoff=NOW,
        decision_readiness=DecisionReadiness.READY,
        llm_status="PASS_DEGRADED/SHADOW",
        stages=stages,
        data_health=(),
        market_regime="NOT_CALIBRATED",
        market_regime_detail="optional",
        factors=(),
        probabilities=(),
        candidates=(),
        portfolio=PortfolioSummary("TARGET_COMPUTED", 100_000, 95_000, 0.95, 0.05, ()),
        risk=RiskSummary("PASS", 0.08, 0.15, None, 0.02, 0.05, 0.05, 0.95, None, 0.05, ()),
        final_decisions=(decision,),
        rejected_signals=(),
        execution_plan=execution,
        benchmarks=(),
        blockers=(),
        warnings=(),
        provenance={"data_hash": "abc", "probability_overlay": {"active": False}},
        config_hash="config",
        model_versions=("alpha-v1",),
    )


def test_maximum_holdings_is_canonical_and_validated() -> None:
    constraints = PortfolioConstraints()
    assert constraints.maximum_holdings == 10
    try:
        PortfolioConstraints(maximum_holdings=0)
    except ValueError as error:
        assert "maximum_holdings" in str(error)
    else:
        raise AssertionError("invalid maximum holdings accepted")


def test_candidate_compression_is_alpha_pool_not_top10_truncation() -> None:
    signals = tuple(_signal(f"S{i:03d}", 0.1 - i * 0.001) for i in range(25))
    result = compress_candidates(signals, candidate_max=15, candidate_min_alpha=0.0)
    assert len(result.candidate_symbols) == 15
    assert result.steps[0].name == "factor_ranked"
    assert result.steps[0].count == 25
    assert result.candidate_symbols[0] == "S000"


def test_null_confidence_is_distinct_from_zero_probability() -> None:
    evidence = TradeEvidence(0.03, None, 21, ("alpha-v1",), ())
    proposal = TradeProposal(
        "AAPL",
        TradeAction.BUY,
        0.0,
        0.05,
        0.05,
        5000.0,
        1.0,
        0.2,
        0.03,
        None,
        21,
        "optimizer",
        ("alpha-v1",),
        (),
        "alpha-v1",
        "data-v1",
        "VALID",
    )
    assert evidence.confidence is None
    assert proposal.confidence is None
    assert evidence.confidence != 0.0
    assert proposal.confidence != 0.0


def test_renderer_uses_na_not_zero_for_unavailable_confidence() -> None:
    rendered = capture_daily_quant_result(_result_with_decision(None), locale="en-US")
    assert "N/A" in rendered
    assert "Source" in rendered
    assert "NOT_CALIBRATED" in rendered


def test_execution_plan_is_not_broker_execution() -> None:
    execution = _result_with_decision(0.8).execution_plan
    assert execution.execution_plan_generated is True
    assert execution.broker_order_submitted is False
    assert execution.broker_api == "DISABLED"
    assert execution.execution_mode == "MANUAL_ONLY"


def test_size_diagnostics_separate_valid_missing_and_future_independent() -> None:
    covariance = np.eye(3)
    valid_risk = RiskModelEstimate(
        symbols=("A", "B", "C"),
        annualized_covariance=covariance,
        correlation=np.eye(3),
        annualized_volatility={"A": 0.2, "B": 0.3, "C": 0.4},
        beta={"A": 1.0, "B": 1.0, "C": 1.0},
        sectors={"A": "TECH", "B": "HEALTH", "C": "FIN"},
        average_daily_dollar_volume={"A": 1e8, "B": 2e8, "C": 3e8},
        size_scores={"A": 1.0, "B": 0.0, "C": -1.0},
        size_exposure_status=SizeExposureStatus.VALID,
        observations=100,
        status=RiskModelStatus.VALID,
        condition_number=2,
        shrinkage=0.2,
        model_version="risk-v1",
        limitations=(),
        market_caps={"A": 1e12, "B": 5e9, "C": 5e8},
    )
    diagnostic = build_size_tilt_diagnostic(
        valid_risk,
        candidate_symbols=("A", "B", "C"),
        target_weights={"A": 0.05, "B": 0.03, "C": 0.02},
        portfolio_value=100_000.0,
        transaction_cost=TransactionCostConfig(),
        expected_transaction_cost=10.0,
    )
    assert diagnostic["status"] == "SIZE_EXPOSURE_VALIDATED"
    assert diagnostic["market_cap_missing_count"] == 0
    assert diagnostic["coverage_ratio"] == 1.0
    missing_risk = RiskModelEstimate(
        symbols=("A", "B", "C"),
        annualized_covariance=covariance,
        correlation=np.eye(3),
        annualized_volatility={"A": 0.2, "B": 0.3, "C": 0.4},
        beta={"A": 1.0, "B": 1.0, "C": 1.0},
        sectors={"A": "TECH", "B": "HEALTH", "C": "FIN"},
        average_daily_dollar_volume={"A": 1e8, "B": 2e8, "C": 3e8},
        size_scores={"A": 1.0},
        size_exposure_status=SizeExposureStatus.NOT_VALIDATED,
        observations=100,
        status=RiskModelStatus.VALID,
        condition_number=2,
        shrinkage=0.2,
        model_version="risk-v1",
        limitations=(),
        market_caps={"A": 1e12},
    )
    missing = build_size_tilt_diagnostic(
        missing_risk,
        candidate_symbols=("A", "B", "C"),
        target_weights={"A": 0.05, "B": 0.03, "C": 0.02},
        portfolio_value=100_000.0,
        transaction_cost=TransactionCostConfig(),
        expected_transaction_cost=10.0,
    )
    assert missing["status"] == "SIZE_EXPOSURE_DEGRADED"
    assert missing["market_cap_missing_count"] == 2


def test_canonical_config_defaults_to_candidate_100_and_holdings_10() -> None:
    config = EffectiveRuntimeConfig()
    assert config.broad_universe.candidate_max == 100
    assert config.portfolio_constraints.maximum_holdings == 10


def test_daily_cardinality_trace_has_optimizer_not_top10_evidence() -> None:
    result = replace(
        _result_with_decision(0.8),
        provenance={
            **_result_with_decision(0.8).provenance,
            "universe_evidence": {
                "candidate_count": 100,
                "optimizer_input": 100,
            },
            "cardinality_trace": {
                "candidate_pool": 100,
                "optimizer_input": 100,
                "risk_engine_securities": 100,
                "maximum_allowed_holdings": 10,
                "optimized_target_holdings": 10,
                "final_decision_holdings": 10,
                "pre_optimizer_top10_truncation": False,
                "optimizer_received_alpha_top10": False,
            },
        },
    )
    rendered = capture_daily_quant_result(result, locale="en-US")
    assert "Optimizer input 100" in rendered
    assert "Maximum allowed holdings 10" in rendered
    assert "Pre-optimizer Top10 False" in rendered
    assert "Optimizer Top10-only False" in rendered


def test_daily_refresh_taxonomy_is_rendered() -> None:
    result = _result_with_decision(0.8)
    stages = list(result.stages)
    data = stages[1]
    stages[1] = data.__class__(
        data.name,
        data.status,
        data.duration_seconds,
        data.message,
        {
            "live_refresh_status": "LIVE_REFRESH_PASS_WITH_QUARANTINE",
            "requested_security_count": 8835,
            "actual_refresh_count": 8745,
            "cache_reuse_count": 88,
            "provider_returned_count": 8745,
            "certified_coverage": 1.0,
            "quarantine_count": 2,
            "provider_incident_count": 0,
            "coverage_collapse": False,
        },
    )
    result = replace(result, stages=tuple(stages))
    rendered = capture_daily_quant_result(result, locale="en-US")
    assert "LIVE_REFRESH_PASS_WITH_QUARANTINE" in rendered
    assert "Requested securities" in rendered
    assert "Quarantine" in rendered
    assert "Coverage collapse" in rendered


def test_daily_execution_separates_plan_and_broker_state() -> None:
    rendered = capture_daily_quant_result(_result_with_decision(0.8), locale="en-US")
    assert "NOT_EXECUTED" in rendered
    assert "execution_plan_generated=true" in rendered
    assert "broker_order_submitted=false" in rendered
    assert "Broker API DISABLED" in rendered
    assert "MANUAL_ONLY" in rendered


def test_doctor_command_is_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"
