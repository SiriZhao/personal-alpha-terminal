from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.round4_research import (
    _target_weights,
    apply_probability_adjustment,
    build_factor_panel,
    rebalance_dates,
    temporal_splits,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1Config,
)


def _panel(
    *,
    symbols: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J"),
    periods: int = 320,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=periods)
    rows: list[dict[str, object]] = []
    for offset, symbol in enumerate(symbols):
        drift = 0.0001 * (offset - len(symbols) / 2)
        shocks = rng.normal(drift, 0.01, periods)
        close = 100.0 * np.cumprod(1.0 + shocks)
        for day, value in zip(index, close, strict=True):
            rows.append(
                {
                    "permanent_security_id": f"US:XNAS:{symbol}",
                    "ticker": symbol,
                    "trade_date": day.date(),
                    "available_time": datetime.combine(
                        day.date(),
                        time(20, 30),
                        tzinfo=UTC,
                    ),
                    "close": float(value),
                    "volume": 1_000_000.0,
                    "role": "alpha",
                }
            )
    return pd.DataFrame(rows)


def _factor_frame(
    panel: pd.DataFrame,
    *,
    dates: tuple[date, ...],
) -> pd.DataFrame:
    return build_factor_panel(
        panel,
        dates=dates,
        config=USAdaptiveAlphaCoreV1Config(),
    )


def test_future_price_poison_does_not_change_factor_features() -> None:
    panel = _panel()
    cutoff_date = pd.to_datetime(panel["trade_date"]).max().date()
    features = _factor_frame(panel, dates=(cutoff_date,))
    poisoned = pd.concat(
        [
            panel,
            pd.DataFrame(
                [
                    {
                        "permanent_security_id": "US:XNAS:A",
                        "ticker": "A",
                        "trade_date": (cutoff_date + timedelta(days=1)),
                        "available_time": datetime.combine(
                            cutoff_date + timedelta(days=1),
                            time(20, 30),
                            tzinfo=UTC,
                        ),
                        "close": 10_000_000.0,
                        "volume": 1_000_000.0,
                        "role": "alpha",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    poisoned_features = _factor_frame(poisoned, dates=(cutoff_date,))
    baseline = features.sort_values("ticker").reset_index(drop=True)
    changed = poisoned_features.sort_values("ticker").reset_index(drop=True)
    pd.testing.assert_frame_equal(
        baseline[
            [
                "ticker",
                "momentum_12_1__raw",
                "momentum_12_1__normalized",
                "trend_slope__normalized",
                "volatility__normalized",
                "composite",
            ]
        ],
        changed[
            [
                "ticker",
                "momentum_12_1__raw",
                "momentum_12_1__normalized",
                "trend_slope__normalized",
                "volatility__normalized",
                "composite",
            ]
        ],
    )


def test_future_security_does_not_change_historical_cross_section() -> None:
    panel = _panel()
    cutoff_date = pd.to_datetime(panel["trade_date"]).max().date()
    baseline = _factor_frame(panel, dates=(cutoff_date,))
    future = pd.DataFrame(
        [
            {
                "permanent_security_id": "US:XNAS:FUTURE",
                "ticker": "FUTURE",
                "trade_date": cutoff_date + timedelta(days=1),
                "available_time": datetime.combine(
                    cutoff_date + timedelta(days=1),
                    time(20, 30),
                    tzinfo=UTC,
                ),
                "close": 100.0,
                "volume": 1_000_000.0,
                "role": "alpha",
            }
        ]
    )
    with_future = _factor_frame(
        pd.concat([panel, future], ignore_index=True),
        dates=(cutoff_date,),
    )
    pd.testing.assert_frame_equal(
        baseline.sort_values("ticker").reset_index(drop=True),
        with_future.sort_values("ticker").reset_index(drop=True),
    )


def test_probability_adjustment_is_neutral_at_fifty_and_changes_alpha() -> None:
    frame = pd.DataFrame(
        {
            "ticker": [f"S{i}" for i in range(6)],
            "expected_alpha": [0.02, 0.01, 0.005, -0.01, 0.03, 0.015],
            "probability": [0.50, 0.70, 0.30, 0.50, 0.80, 0.20],
        }
    )
    adjusted = apply_probability_adjustment(
        frame,
        probability_column="probability",
        maximum_multiplier=0.25,
    )
    neutral = adjusted.loc[adjusted["probability"] == 0.50]
    assert np.allclose(neutral["adjusted_alpha"], neutral["expected_alpha"])
    boosted = adjusted.loc[adjusted["probability"] == 0.80, "adjusted_alpha"].iloc[0]
    reduced = adjusted.loc[adjusted["probability"] == 0.20, "adjusted_alpha"].iloc[0]
    assert boosted > 0.03
    assert reduced < 0.015


def test_probability_adjustment_can_change_target_weights() -> None:
    frame = pd.DataFrame(
        {
            "as_of_date": [date(2026, 8, 12)] * 12,
            "ticker": [f"S{i}" for i in range(12)],
            "expected_alpha": [0.05, 0.04, 0.03, 0.02, 0.01, 0.0] * 2,
            "probability": [0.10, 0.20, 0.30, 0.90, 0.80, 0.70] * 2,
            "forward_return": 0.01,
        }
    )
    adjusted = apply_probability_adjustment(
        frame,
        probability_column="probability",
        maximum_multiplier=0.50,
    )
    classical = _target_weights(
        adjusted,
        alpha_column="expected_alpha",
        dates=(date(2026, 8, 12),),
        top_fraction=0.50,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    probability = _target_weights(
        adjusted,
        alpha_column="adjusted_alpha",
        dates=(date(2026, 8, 12),),
        top_fraction=0.50,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    assert classical != probability


def test_temporal_splits_are_chronological_and_disjoint() -> None:
    dates = tuple(
        date(2024, 1, 1) + timedelta(days=21 * index)
        for index in range(20)
    )
    train, calibration, oos = temporal_splits(dates)
    assert train[0] <= train[1] < calibration[0] <= calibration[1] < oos[0] <= oos[1]
    assert len(dates) == 20


def test_rebalance_dates_are_seasoned_and_spaced() -> None:
    panel = _panel(periods=320)
    dates = rebalance_dates(panel, end_date=date(2025, 12, 31), horizon=21)
    assert dates
    assert len(dates) > 5


def test_broad_cli_optional_date_parsing() -> None:
    from personal_alpha_terminal.terminal.broad_universe_cli import _optional_date

    assert _optional_date("2026-08-12") == date(2026, 8, 12)
    assert _optional_date(None) is None
    with pytest.raises(ValueError):
        _optional_date("not-a-date")
