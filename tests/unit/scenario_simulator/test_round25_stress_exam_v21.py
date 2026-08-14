"""ROUND25 PHASE 19: Stress Exam 2.1 overlay comparison tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from personal_alpha_terminal.scenario_simulator.stress_exam_v2 import (
    ProductionBaseline,
)
from personal_alpha_terminal.scenario_simulator.stress_exam_v21 import (
    _variant_baseline,
    run_stress_exam_v21,
)


def _baseline() -> ProductionBaseline:
    index = pd.date_range("2025-01-01", periods=60, freq="B")
    returns = pd.DataFrame(
        np.random.RandomState(1).normal(0.0005, 0.01, (60, 3)),
        index=index,
        columns=["VSTS", "RVMD", "TVTX"],
    )
    return ProductionBaseline(
        run_id="r1",
        analysis_date="2026-08-13",
        holdings={"VSTS": 0.0694, "RVMD": 0.0405, "TVTX": 0.037},
        equity_symbols=("VSTS", "RVMD", "TVTX"),
        etf_symbols=(),
        returns=returns,
        average_dollar_volume={},
        sector_proxy={},
        portfolio_value=100_000.0,
        cash_weight=0.853,
        baseline_volatility=None,
        source="test",
    )


def test_variant_scaling_keeps_cash_accounted() -> None:
    baseline = _baseline()
    variant = _variant_baseline(baseline, {"scale_gross": 0.7})
    total = sum(variant.holdings.values()) + variant.cash_weight
    baseline_total = sum(baseline.holdings.values()) + baseline.cash_weight
    assert abs(total - baseline_total) < 1e-4
    assert variant.holdings["VSTS"] == round(0.0694 * 0.7, 8)


def test_etf_core_variant_adds_diversified_sleeve() -> None:
    baseline = _baseline()
    variant = _variant_baseline(
        baseline,
        {"etf_core": {"IVV": 0.0625, "VOO": 0.0625, "VTI": 0.0625, "IJR": 0.0625}},
    )
    assert set(variant.etf_symbols) == {"IVV", "VOO", "VTI", "IJR"}
    assert variant.holdings["IVV"] == 0.0625
    assert variant.holdings["VSTS"] == round(0.0694 * 0.75, 8)


def test_no_baseline_is_honest_unavailable() -> None:
    result = run_stress_exam_v21(None)
    assert result["status"] == "UNAVAILABLE_BASELINE"
    assert result["scenario_definitions_unchanged"] is True
    assert result["variants"] == {}


def test_scenarios_are_reused_unchanged() -> None:
    from personal_alpha_terminal.scenario_simulator.stress_exam_v2 import (
        MARKET_SCENARIOS,
    )

    # The ROUND24 scenario catalog remains the single source of truth.
    names = {spec.name for spec in MARKET_SCENARIOS}
    assert "BROAD_EQUITY_CRASH" in names
    assert "CORRELATION_TO_ONE" in names
    assert "LIQUIDITY_COLLAPSE" in names
    result = run_stress_exam_v21(_baseline())
    assert result["summary"]["scenario_definitions_unchanged"] is True
    assert result["summary"]["auto_promotion"] is False
    assert set(result["comparison"]) == {
        "A_classical_champion",
        "B_champion_regime_risk_budget",
        "C_champion_drawdown_governor",
        "D_champion_etf_core",
    }
