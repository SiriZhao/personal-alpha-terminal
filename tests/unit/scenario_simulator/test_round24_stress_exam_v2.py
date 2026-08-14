"""ROUND24 Stress Exam 2.0 tests (PHASE D, I, J, N)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from personal_alpha_terminal.scenario_simulator.stress_exam_v2 import (
    MARKET_SCENARIOS,
    ProductionBaseline,
    simulate_market_scenario,
)
from personal_alpha_terminal.scenario_simulator.stress_exam_v2_run import (
    run_stress_exam_v2,
    write_stress_exam_v2_artifacts,
)


def _baseline(*, with_etf: bool = False) -> ProductionBaseline:
    rng = np.random.RandomState(42)
    dates = pd.date_range("2025-08-01", periods=260, freq="B")
    symbols = ["VSTS", "RVMD", "STX"]
    holdings = {"VSTS": 0.07, "RVMD": 0.04, "STX": 0.03}
    if with_etf:
        symbols.append("VOO")
        holdings["VOO"] = 0.05
    data = {symbol: rng.normal(0.0003, 0.015, len(dates)) for symbol in symbols}
    returns = pd.DataFrame(data, index=dates)
    return ProductionBaseline(
        run_id="daily-test",
        analysis_date="2026-08-13",
        holdings=holdings,
        equity_symbols=("VSTS", "RVMD", "STX"),
        etf_symbols=("VOO",) if with_etf else (),
        returns=returns,
        average_dollar_volume={symbol: 100_000_000.0 for symbol in symbols},
        sector_proxy={"VOO": "US_BROAD_MARKET"},
        portfolio_value=100_000.0,
        cash_weight=0.85,
        baseline_volatility=0.12,
        source="test",
    )


def test_market_scenario_names_cover_required_set() -> None:
    names = {spec.name for spec in MARKET_SCENARIOS}
    required = {
        "BROAD_EQUITY_CRASH",
        "FAST_CRASH_GAP",
        "SLOW_BEAR_MARKET",
        "MOMENTUM_CRASH",
        "FACTOR_INVERSION",
        "GROWTH_CRASH",
        "VALUE_CRASH",
        "SMALL_CAP_CRASH",
        "SECTOR_CRASH",
        "CORRELATION_TO_ONE",
        "VOLATILITY_SPIKE",
        "LIQUIDITY_COLLAPSE",
        "VOLUME_COLLAPSE",
        "SPREAD_X5",
        "SPREAD_X10",
        "SINGLE_NAME_MINUS_50",
        "SINGLE_NAME_MINUS_80",
        "ETF_TRACKING_SHOCK",
        "BOND_EQUITY_SIMULTANEOUS_LOSS",
        "RATE_SHOCK",
        "COMMODITY_SHOCK",
        "INTERNATIONAL_RISK_OFF",
    }
    assert required <= names


def test_metrics_computed_for_every_scenario() -> None:
    baseline = _baseline(with_etf=True)
    for spec in MARKET_SCENARIOS:
        metrics = simulate_market_scenario(spec, baseline, seed=7)
        assert metrics.scenario == spec.name
        assert isinstance(metrics.max_drawdown, float)
        assert metrics.cvar_95 >= 0
        assert metrics.annualized_volatility >= 0
        assert metrics.gate_violations is not None


def test_sector_crash_penalizes_sector_proxy() -> None:
    baseline = _baseline()
    sector_spec = next(s for s in MARKET_SCENARIOS if s.name == "SECTOR_CRASH")
    metrics = simulate_market_scenario(sector_spec, baseline, seed=3)
    assert metrics.scenario == "SECTOR_CRASH"
    assert metrics.max_drawdown <= 0


def test_single_name_minus_80_reports_gate_violation() -> None:
    baseline = _baseline()
    spec = next(s for s in MARKET_SCENARIOS if s.name == "SINGLE_NAME_MINUS_80")
    metrics = simulate_market_scenario(spec, baseline, seed=3)
    assert "maximum_single_name_loss" in metrics.gate_violations


def test_spread_shocks_increase_liquidation_cost() -> None:
    baseline = _baseline()
    normal = simulate_market_scenario(
        next(s for s in MARKET_SCENARIOS if s.name == "SPREAD_X5"),
        baseline,
        seed=3,
    )
    severe = simulate_market_scenario(
        next(s for s in MARKET_SCENARIOS if s.name == "SPREAD_X10"),
        baseline,
        seed=3,
    )
    assert severe.transaction_cost > normal.transaction_cost


def test_etf_tracking_shock_hits_etf_holdings() -> None:
    baseline = _baseline(with_etf=True)
    spec = next(s for s in MARKET_SCENARIOS if s.name == "ETF_TRACKING_SHOCK")
    metrics = simulate_market_scenario(spec, baseline, seed=3)
    assert metrics.scenario == "ETF_TRACKING_SHOCK"
    assert metrics.max_drawdown <= 0


def _probe(pass_value: bool, observed: str = "probe observed"):
    return lambda: {"pass": pass_value, "observed": observed}


def test_resilience_scenarios_run_and_score() -> None:
    summary = run_stress_exam_v2(
        baseline=_baseline(),
        resilience_probes={
            "provider_outage": _probe(True, "fail-closed partial status"),
            "partial_provider": _probe(True, "partial response recorded"),
            "bars_quality": lambda kind: {"pass": True, "observed": kind},
            "future_rows": _probe(True, "future rows dropped"),
            "db_fault": lambda kind: {"pass": True, "observed": kind},
            "report_fault": _probe(True, "reporting degraded only"),
            "llm_timeout": _probe(True, "LLM PASS_DEGRADED"),
            "llm_malformed": _probe(True, "AI_BRIEF_QUARANTINED"),
            "probability_unavailable": _probe(True, "fallback classical"),
        },
    )
    assert len(summary.resilience) == 12
    assert summary.scorecard["RESILIENCE"] == 100
    assert summary.classification in {
        "STRESS_EXAM_V2_PASS",
        "STRESS_EXAM_V2_PASS_WITH_WARNINGS",
        "STRESS_EXAM_V2_RESILIENCE_ONLY",
    }


def test_critical_resilience_failure_is_not_masked() -> None:
    summary = run_stress_exam_v2(
        baseline=_baseline(),
        resilience_probes={
            "provider_outage": _probe(False, "silently fabricated bars"),
            "partial_provider": _probe(True),
            "bars_quality": lambda kind: {"pass": True, "observed": kind},
            "future_rows": _probe(True),
            "db_fault": lambda kind: {"pass": True, "observed": kind},
            "report_fault": _probe(True),
            "llm_timeout": _probe(True),
            "llm_malformed": _probe(True),
            "probability_unavailable": _probe(True),
        },
    )
    assert summary.classification == "STRESS_EXAM_V2_FAIL_CRITICAL"
    assert "PROVIDER_OUTAGE" in summary.critical_failures
    assert summary.scorecard["OPERATIONS"] == 50


def test_no_valid_baseline_runs_resilience_only() -> None:
    summary = run_stress_exam_v2(
        baseline=None,
        resilience_probes={
            "llm_timeout": _probe(True),
            "llm_malformed": _probe(True),
            "probability_unavailable": _probe(True),
        },
    )
    assert summary.baseline_status == "UNAVAILABLE_BASELINE"
    assert "MARKET_SCENARIOS_SKIPPED_NO_VALID_BASELINE" in summary.warnings


def test_artifacts_written_with_required_files(tmp_path) -> None:
    summary = run_stress_exam_v2(baseline=_baseline())
    paths = write_stress_exam_v2_artifacts(summary, tmp_path)
    names = {path.name for path in paths}
    assert names == {
        "stress_exam_v2_summary.json",
        "stress_exam_v2_scenarios.json",
        "stress_exam_v2_risk_reactions.json",
    }
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


def test_scorecard_never_hides_alpha_zero() -> None:
    summary = run_stress_exam_v2(baseline=_baseline())
    assert summary.scorecard["ALPHA"] == 0
    assert "NOT_ALPHA_CERTIFICATION" in summary.warnings
