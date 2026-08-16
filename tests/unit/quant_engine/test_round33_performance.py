from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.performance_metrics import (
    FrequencySpec,
    annualize_sharpe,
    annualize_volatility,
    calculate_equity_performance,
)
from personal_alpha_terminal.quant_engine.round4_research import (
    _simulate_weights,
    allocate_positive_alpha_weights,
)
from personal_alpha_terminal.quant_engine.round33_performance import (
    AlphaCalibrationSpec,
    ResearchExecutionPolicy,
    build_corrected_labeled_panel,
    calibrate_alpha,
)


def _allocation_frame(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [f"S{i}" for i in range(count)],
            "expected_alpha": [0.05 - index * 0.0001 for index in range(count)],
        }
    )


@pytest.mark.parametrize("universe_count", [0, 1, 2, 5, 10, 20, 100, 392, 500, 1000, 1959])
def test_weight_allocation_invariants(universe_count: int) -> None:
    result = allocate_positive_alpha_weights(
        _allocation_frame(universe_count),
        alpha_column="expected_alpha",
        top_fraction=0.20,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    weights = dict(result.weights)
    assert result.sum_error == pytest.approx(0.0, abs=1e-12)
    assert all(0.0 <= weight <= 0.12 + 1e-12 for weight in weights.values())
    if universe_count:
        assert result.actual_gross == pytest.approx(
            min(0.90, result.positive_selected_count * 0.12)
        )
        assert sum(weights.values()) == pytest.approx(result.actual_gross)
    else:
        assert result.actual_gross == 0.0


def test_large_universe_regression_gross_is_ninety_percent() -> None:
    result = allocate_positive_alpha_weights(
        _allocation_frame(1959),
        alpha_column="expected_alpha",
        top_fraction=0.20,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    assert result.actual_gross == pytest.approx(0.90)
    assert result.positive_selected_count == 392


def test_positive_alpha_filtering_capacity_uses_filtered_count() -> None:
    frame = pd.DataFrame(
        {
            "ticker": [f"S{i}" for i in range(10)],
            "expected_alpha": [
                0.03,
                0.02,
                0.01,
                -0.01,
                -0.02,
                -0.015,
                -0.005,
                -0.025,
                -0.001,
                -0.003,
            ],
        }
    )
    result = allocate_positive_alpha_weights(
        frame,
        alpha_column="expected_alpha",
        top_fraction=0.50,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    assert result.selected_count == 5
    assert result.positive_selected_count == 3
    assert result.capacity == pytest.approx(0.36)
    assert result.actual_gross == pytest.approx(0.36)


def test_metric_frequency_does_not_guess_252() -> None:
    returns = [0.01, -0.005, 0.01, -0.005, 0.01]
    daily = annualize_sharpe(returns, periods_per_year=FrequencySpec.daily().periods_per_year)
    holding = annualize_sharpe(
        returns,
        periods_per_year=FrequencySpec.holding(21).periods_per_year,
    )
    assert daily != holding
    assert annualize_volatility(returns, periods_per_year=252) != annualize_volatility(
        returns, periods_per_year=252 / 21
    )
    with pytest.raises(ValueError):
        FrequencySpec.holding(0)


def test_daily_equity_performance_matches_analytical_values() -> None:
    returns = [0.01, -0.005, 0.01, -0.005, 0.01]
    equity = [1.0]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value))
    points = tuple(
        (date(2026, 1, 1) + timedelta(days=index), value)
        for index, value in enumerate(equity)
    )
    result = calculate_equity_performance(points, frequency_spec=FrequencySpec.daily())
    expected_sharpe = annualize_sharpe(returns, periods_per_year=252)
    assert result.sharpe == pytest.approx(expected_sharpe)
    assert result.return_frequency.value == "DAILY"
    assert result.periods_per_year == 252


def test_missing_adv_raises_cost_unavailable_not_zero() -> None:
    adjusted = pd.DataFrame(
        {
            "as_of_date": [date(2026, 1, 1)] * 6,
            "ticker": [f"S{i}" for i in range(6)],
            "expected_alpha": [0.05, 0.04, 0.03, 0.02, 0.01, -0.01],
            "forward_return": 0.01,
        }
    )
    price_panel = pd.DataFrame(
        {
            "trade_date": [date(2025, 12, 1)] * 6,
            "ticker": [f"S{i}" for i in range(6)],
            "close": [100.0] * 6,
            "volume": [np.nan] * 6,
        }
    )
    with pytest.raises(ValueError, match="COST_UNAVAILABLE"):
        _simulate_weights(
            adjusted,
            adjusted,
            alpha_column="expected_alpha",
            dates=(date(2026, 1, 1),),
            price_panel=price_panel,
            top_fraction=0.5,
            maximum_weight=0.12,
            minimum_cash=0.10,
            cost_model=TransactionCostModel(TransactionCostConfig()),
        )


def _execution_panel() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=60)
    rows: list[dict[str, object]] = []
    for symbol, _offset in (("A", 0.0), ("SPY", 0.0), ("QQQ", 0.0)):
        close = 100.0 * np.cumprod(1.0 + np.full(len(dates), 0.0005))
        for index, day in enumerate(dates):
            rows.append(
                {
                    "permanent_security_id": f"US:{symbol}",
                    "ticker": symbol,
                    "trade_date": day.date(),
                    "available_time": datetime.combine(day.date(), time(20, 30), tzinfo=UTC),
                    "open": float(close[index]),
                    "high": float(close[index]) * 1.001,
                    "low": float(close[index]) * 0.999,
                    "close": float(close[index]),
                    "volume": 1_000_000.0,
                    "ingested_at": datetime.combine(day.date(), time(21), tzinfo=UTC),
                    "open_tradable": True,
                    "source": "fixture",
                    "provider": "fixture",
                    "role": "alpha" if symbol == "A" else "reference",
                }
            )
    return pd.DataFrame(rows)


def test_corrected_execution_is_next_open_to_horizon_close() -> None:
    panel = _execution_panel()
    factor = pd.DataFrame(
        {
            "permanent_security_id": ["US:A"],
            "ticker": ["A"],
            "as_of_date": [panel["trade_date"].iloc[0]],
            "expected_alpha": [0.02],
        }
    )
    labeled = build_corrected_labeled_panel(
        panel,
        factor,
        benchmark="SPY",
        horizon=21,
        execution_policy=ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE,
    )
    assert not labeled.empty
    first = labeled.iloc[0]
    assert first["entry_date"] == panel["trade_date"].iloc[1]
    assert first["exit_date"] == panel["trade_date"].iloc[21]


def test_alpha_calibration_oos_is_locked_and_not_promoted() -> None:
    rng = np.random.default_rng(7)
    dates = tuple(
        date(2025, 1, 1) + timedelta(days=21 * index) for index in range(40)
    )
    rows: list[dict[str, object]] = []
    for as_of in dates:
        for index in range(50):
            rows.append(
                {
                    "permanent_security_id": f"US:{index}",
                    "ticker": f"S{index}",
                    "as_of_date": as_of,
                    "forward_return": rng.normal(0.001, 0.02),
                    "momentum_12_1__normalized": rng.normal(0.0, 1.0),
                    "trend_slope__normalized": rng.normal(0.0, 1.0),
                    "volatility__normalized": rng.normal(0.0, 1.0),
                    "composite": rng.normal(0.0, 1.0),
                    "expected_alpha": rng.normal(0.0, 0.01),
                }
            )
    panel = pd.DataFrame(rows)
    result, oos = calibrate_alpha(
        panel,
        session_dates=dates,
        spec=AlphaCalibrationSpec(method="regularized_ic_weighted"),
    )
    assert result.promotion_eligible is False
    assert result.oos_date_count > 0
    assert oos["calibrated_score"].notna().all()
