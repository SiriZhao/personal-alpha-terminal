"""ROUND 12.1 live decision, portfolio, probability, and runtime semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

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


def test_production_constraints_have_no_fixed_holdings_cap() -> None:
    constraints = PortfolioConstraints()
    assert not hasattr(constraints, "maximum_holdings")


def test_candidate_compression_is_alpha_pool_not_top10_truncation() -> None:
    signals = tuple(_signal(f"S{i:03d}", 0.1 - i * 0.001) for i in range(25))
    result = compress_candidates(signals, candidate_min_alpha=0.0)
    assert len(result.candidate_symbols) == 25
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


def test_canonical_config_has_no_fixed_candidate_or_holdings_cap() -> None:
    config = EffectiveRuntimeConfig()
    assert not hasattr(config.broad_universe, "candidate_max")
    assert not hasattr(config.portfolio_constraints, "maximum_holdings")


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
                "maximum_allowed_holdings": None,
                "optimized_target_holdings": 15,
                "final_decision_holdings": 15,
                "pre_optimizer_top10_truncation": False,
                "optimizer_received_alpha_top10": False,
            },
        },
    )
    rendered = capture_daily_quant_result(result, locale="en-US")
    assert "Optimizer input 100" in rendered
    assert "Fixed holdings cap NONE" in rendered
    assert "Pre-optimizer fixed Top-N NONE" in rendered
    assert "Optimizer cardinality cap NONE" in rendered


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


def test_zh_renderer_required_localization_labels_survive() -> None:
    rendered = capture_daily_quant_result(
        replace(_result_with_decision(0.8), decision_traces={"AAPL": {"target_weight": 0.05}}),
        locale="zh-CN",
        width=160,
    )
    labels = (
        "\u6267\u884c\u8ba1\u5212",
        "\u5238\u5546\u6267\u884c",
        "\u6267\u884c\u65b9\u5f0f",
        "\u672a\u6267\u884c",
        "\u4ec5\u624b\u52a8",
        "\u5238\u5546",
        "\u88ab\u62d2\u7edd\u4fe1\u53f7 / \u95e8\u7981\u539f\u56e0",
        "\u6700\u7ec8\u6709\u6548\u51b3\u7b56 "
        "\u00b7 \u4ec5\u663e\u793a\u6b63\u5f0f\u4e70\u5356\u533a",
        "\u51b3\u7b56\u5f62\u6210\u8fc7\u7a0b",
        "\u6761\u4ef6\u6982\u7387\u8bc4\u4f30",
        "\u751f\u4ea7\u6743\u91cd",
        "SIZE_TILT_DIAGNOSTIC \u00b7 \u89c4\u6a21\u503e\u659c\u8bca\u65ad",
        "\u5019\u9009\u6c60",
        "\u4f18\u5316\u5668\u8f93\u5165",
        "\u56fa\u5b9a\u6301\u4ed3\u6570\u91cf\u4e0a\u9650",
        "\u4f18\u5316\u540e\u76ee\u6807\u6301\u4ed3",
    )
    for label in labels:
        assert label in rendered


def test_zh_renderer_blocked_execution_keeps_status_codes() -> None:
    base = _result_with_decision(0.8)
    blocked = replace(
        base,
        final_decisions=(),
        execution_plan=replace(
            base.execution_plan,
            status="BLOCKED",
            execution_plan_generated=False,
            legs=(),
        ),
    )
    rendered = capture_daily_quant_result(blocked, locale="zh-CN", width=160)
    assert "\u6267\u884c\u8ba1\u5212\uff1aBLOCKED" in rendered
    assert "\u5238\u5546\u6267\u884c\uff1a\u672a\u6267\u884c NOT_EXECUTED" in rendered
    assert "\u6267\u884c\u65b9\u5f0f\uff1a\u4ec5\u624b\u52a8 MANUAL_ONLY" in rendered


def test_zh_renderer_probability_fallback_and_size_unavailable_labels() -> None:
    rendered = capture_daily_quant_result(_result_with_decision(None), locale="zh-CN", width=160)
    assert "\u6761\u4ef6\u6982\u7387\u8bc4\u4f30" in rendered
    assert "\u751f\u4ea7\u6743\u91cd: 0%" in rendered
    assert "SIZE_TILT_DIAGNOSTIC \u00b7 \u89c4\u6a21\u503e\u659c\u8bca\u65ad" in rendered


def test_zh_renderer_llm_shadow_regression() -> None:
    base = _result_with_decision(0.8)
    stages = list(base.stages)
    llm = stages[3]
    stages[3] = llm.__class__(
        llm.name,
        llm.status,
        llm.duration_seconds,
        llm.message,
        {
            "advisory_status": "SHADOW",
            "llm_calls": 3,
            "processed_documents": 2,
        },
    )
    result = replace(base, stages=tuple(stages))
    rendered = capture_daily_quant_result(result, locale="zh-CN", width=160)
    assert "SHADOW" in rendered
    assert "LLM \u8c03\u7528" in rendered
    assert "\u5df2\u5904\u7406\u6587\u6863" in rendered


def test_utf8_redirected_stdout_smoke() -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = (
        "import sys\n"
        "sys.path.insert(0, " + repr(str(root)) + ")\n"
        "from tests.unit.application.test_round12_1_live_semantics import _result_with_decision\n"
        "from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result\n"
        "print(capture_daily_quant_result(_result_with_decision(0.8), locale='zh-CN', width=160))\n"
    )
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "\u6267\u884c\u8ba1\u5212\uff1aPASS" in completed.stdout
    assert "\u6761\u4ef6\u6982\u7387\u8bc4\u4f30" in completed.stdout
    assert "\u672a\u6267\u884c" in completed.stdout
    assert "\u4ec5\u624b\u52a8" in completed.stdout


def test_legacy_windows_stdout_smoke() -> None:
    import codecs
    import os
    import subprocess
    import sys
    from pathlib import Path

    try:
        codecs.lookup("gbk")
    except LookupError:
        pytest.skip("GBK codec unavailable; CMD-compatible smoke skipped")
    root = Path(__file__).resolve().parents[3]
    script = (
        "import sys\n"
        "sys.path.insert(0, " + repr(str(root)) + ")\n"
        "from tests.unit.application.test_round12_1_live_semantics import _result_with_decision\n"
        "from personal_alpha_terminal.terminal.daily_renderer import capture_daily_quant_result\n"
        "print(capture_daily_quant_result(_result_with_decision(0.8), locale='zh-CN', width=160))\n"
    )
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "gbk"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="gbk",
        env=env,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "\u88ab\u62d2\u7edd\u4fe1\u53f7 / \u95e8\u7981\u539f\u56e0" in completed.stdout
    assert "\u6700\u7ec8\u6709\u6548\u51b3\u7b56" in completed.stdout


def test_zh_renderer_today_overview_is_before_actions() -> None:
    rendered = capture_daily_quant_result(_result_with_decision(0.8), locale="zh-CN", width=160)
    assert "\u3010\u4eca\u65e5\u603b\u89c8\u3011" in rendered
    assert "\u3010\u4eca\u65e5\u64cd\u4f5c\u6e05\u5355\u3011" in rendered
    overview = "\u3010\u4eca\u65e5\u603b\u89c8\u3011"
    actions = "\u3010\u4eca\u65e5\u64cd\u4f5c\u6e05\u5355\u3011"
    assert rendered.index(overview) < rendered.index(actions)


def test_zh_renderer_overview_answers_key_fields() -> None:
    rendered = capture_daily_quant_result(_result_with_decision(0.8), locale="zh-CN", width=160)
    labels = (
        "\u4eca\u65e5\u72b6\u6001",
        "\u64cd\u4f5c",
        "\u9884\u8ba1\u91d1\u989d",
        "\u6700\u65e9\u6267\u884c",
        "LLM \u53c2\u4e0e",
        "Probability \u53c2\u4e0e",
        "\u95e8\u7981",
    )
    for label in labels:
        assert label in rendered