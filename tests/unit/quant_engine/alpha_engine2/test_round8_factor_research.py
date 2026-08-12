"""ROUND 8: factor research and redundancy diagnostics tests."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    factor_catalog,
    factor_redundancy,
    research_factor,
)


def _labeled_panel(periods: int = 40, names: int = 8) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for period in range(periods):
        day = date(2024, 1, 2) + pd.Timedelta(days=period * 2).to_pytimedelta()
        for symbol_index in range(names):
            drift = 0.0005 + 0.0004 * symbol_index
            noise = 0.005 * np.sin(period + symbol_index)
            forward = drift + noise
            rows.append(
                {
                    "as_of_date": day,
                    "permanent_security_id": f"SEC-{symbol_index}",
                    "ticker": f"S{symbol_index}",
                    "forward_return": forward,
                    "momentum_12_1__normalized": forward * 20 + symbol_index * 0.01,
                    "trend_slope__normalized": forward * 15 + symbol_index * 0.02,
                    "volatility__normalized": -abs(noise) * 10 + symbol_index * 0.005,
                    "composite": forward * 10,
                    "expected_alpha": forward * 5,
                }
            )
    return pd.DataFrame(rows)


def test_factor_catalog_lists_research_factors_with_rationale_and_pit() -> None:
    catalog = factor_catalog()
    names = {item["name"] for item in catalog}
    for expected in (
        "momentum_12_1",
        "trend_slope",
        "low_volatility",
        "short_term_reversal",
        "residual_momentum",
        "volatility_regime",
        "liquidity",
        "quality",
        "profitability",
        "investment",
        "value",
        "market_breadth",
    ):
        assert expected in names, expected
    for item in catalog:
        assert item["rationale"].strip()
        assert item["pit"].strip()
        assert item["direction"].strip()


def test_research_factor_reports_ic_stability_and_cost_adjusted_value() -> None:
    panel = _labeled_panel()
    result = research_factor(
        panel,
        name="momentum_12_1",
        signal_column="momentum_12_1__normalized",
        direction="higher_is_better",
        horizon=5,
        cost_rate=0.001,
    )
    assert result.rank_ic is not None
    assert result.ic_ir is not None
    assert result.turnover is not None
    assert result.stability is not None
    assert result.cost_adjusted_value is not None
    assert result.candidate is not None
    assert result.economic_rationale.strip()


def test_factor_redundancy_flags_highly_correlated_pairs() -> None:
    panel = _labeled_panel()
    # Add a near-duplicate momentum factor.
    panel["momentum_copy"] = panel["momentum_12_1__normalized"] * 1.001 + 0.0001
    report = factor_redundancy(
        panel,
        signal_columns=("momentum_12_1__normalized", "momentum_copy", "volatility__normalized"),
        threshold=0.85,
    )
    names = {pair[0] for pair in report.redundant_pairs}
    names |= {pair[1] for pair in report.redundant_pairs}
    assert "momentum_12_1__normalized" in names
    assert "momentum_copy" in names
    assert report.correlation["momentum_copy"]["momentum_12_1__normalized"] > 0.99
    assert "momentum_12_1__normalized" in report.marginal_ic
    assert "momentum_12_1__normalized" in report.incremental_contribution


def test_factor_redundancy_no_false_positive_on_uncorrelated() -> None:
    rng = np.random.default_rng(7)
    panel = _labeled_panel()
    panel["random_factor"] = rng.normal(0, 1, len(panel))
    report = factor_redundancy(
        panel,
        signal_columns=("momentum_12_1__normalized", "random_factor"),
        threshold=0.85,
    )
    assert report.redundant_pairs == ()
