"""ROUND25 PHASE 4: deterministic MARKET_STATE_SNAPSHOT tests."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.application.market_state import (
    MARKET_STATE_METRIC_CONTRACT,
    METRIC_KIND_DECIMAL_RETURN,
    METRIC_KIND_PERCENT,
    _series_metrics,
)


def _flat_series(days: int = 300) -> pd.Series:
    return pd.Series(np.linspace(100.0, 200.0, days))


def test_contract_units_are_explicit() -> None:
    assert MARKET_STATE_METRIC_CONTRACT["return_252d"]["kind"] == METRIC_KIND_DECIMAL_RETURN
    assert MARKET_STATE_METRIC_CONTRACT["distance_ma20"]["kind"] == METRIC_KIND_PERCENT
    assert MARKET_STATE_METRIC_CONTRACT["breadth_pct_above_ma50"]["kind"] == METRIC_KIND_PERCENT


def test_returns_are_decimal_and_correct() -> None:
    close = _flat_series(300)
    metrics = _series_metrics(close)
    # 252d return: last / (last - 252 - 1) - 1 for a linear ramp 100 -> 200.
    expected = close.iloc[-1] / close.iloc[-253] - 1.0
    assert metrics["returns"]["return_252d"] == pytest.approx(expected)
    assert isinstance(metrics["returns"]["return_1d"], float)


def test_drawdown_flat_up_series_is_zero() -> None:
    close = _flat_series(300)
    metrics = _series_metrics(close)
    assert metrics["drawdowns"]["drawdown_252d"] == pytest.approx(0.0)


def test_drawdown_down_series_is_negative_decimal() -> None:
    values = [100.0] * 60 + [50.0] * 50
    close = pd.Series(values)
    metrics = _series_metrics(close)
    assert metrics["drawdowns"]["drawdown_63d"] == pytest.approx(-0.5)


def test_realized_vol_is_annualized_percent() -> None:
    rng = np.random.RandomState(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    metrics = _series_metrics(close)
    vol = metrics["realized_vols"]["realized_vol_63d"]
    assert vol is not None
    assert math.isfinite(vol)
    # daily sigma 0.01 -> annualized ~0.158
    assert 0.10 < vol < 0.25


def test_short_series_returns_none_metrics() -> None:
    close = pd.Series([100.0, 101.0])
    metrics = _series_metrics(close)
    assert metrics["returns"]["return_252d"] is None
    assert metrics["realized_vols"]["realized_vol_20d"] is None
    assert metrics["ma_distances"]["distance_ma200"] is None
