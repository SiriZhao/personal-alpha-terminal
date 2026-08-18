"""Flagship synthetic stress tests through the production quant pipeline."""

from __future__ import annotations

from personal_alpha_terminal.scenario_simulator.flagship_stress import (
    SCENARIOS,
    run_flagship_synthetic_stress,
)


def test_flagship_stress_covers_required_regimes_and_is_deterministic() -> None:
    first = run_flagship_synthetic_stress()
    second = run_flagship_synthetic_stress()
    assert first.stress_id == second.stress_id
    assert {item.scenario for item in first.scenarios} == {item.name for item in SCENARIOS}
    assert {
        "极端系统性崩盘",
        "严重熊市",
        "中度熊市",
        "正常混合市场",
        "强势牛市",
    } <= {item.regime for item in first.scenarios}
    metrics = {item.scenario: item for item in first.scenarios}
    assert metrics["EXTREME_SYSTEMIC_CRASH"].benchmark_return <= -0.70
    assert metrics["SEVERE_BEAR_MARKET"].benchmark_return <= -0.45
    assert -0.30 <= metrics["MODERATE_BEAR_MARKET"].benchmark_return <= -0.15
    assert -0.02 <= metrics["NORMAL_MIXED_MARKET"].benchmark_return <= 0.10
    assert metrics["STRONG_BULL_MARKET"].benchmark_return >= 0.40


def test_flagship_stress_preserves_production_invariants() -> None:
    summary = run_flagship_synthetic_stress()
    assert summary.classification == "SYNTHETIC_STRESS_PASS_WITH_WARNINGS"
    for item in summary.scenarios:
        assert item.long_only_preserved
        assert item.gross_cap_preserved
        assert item.numerical_stability
        assert item.no_fixed_cardinality_cap
        assert item.probability_formal_influence == 0.0
        assert item.llm_formal_influence == 0.0
        optimizer_outcomes = (
            item.primary_optimizer_passes
            + item.feasibility_recovery_passes
            + item.sell_only_fallback_passes
            + item.optimizer_blocked
        )
        assert optimizer_outcomes >= 1
        assert item.optimizer_blocked == 0


def test_flagship_stress_faults_fail_closed_and_authority_stays_zero() -> None:
    checks = run_flagship_synthetic_stress().resilience_checks
    assert all(value.startswith("PASS") for value in checks.values())
    assert checks["future_timestamp_injection"] == "PASS_BLOCKED"
    assert checks["missing_data_collapse"] == "PASS_BLOCKED"
    assert checks["severe_risk_sell_only"] == "PASS_SELL_ONLY_NO_NEW_RISK"
    assert checks["risk_drift_repair"] == "PASS_HARD_BREACH_REPAIRED_MANUAL_ONLY"
    assert checks["probability_unavailable_fallback"] == "PASS_CLASSICAL_UNCHANGED"
    assert checks["llm_quant_disagreement"] == "PASS_ZERO_FORMAL_INFLUENCE"
