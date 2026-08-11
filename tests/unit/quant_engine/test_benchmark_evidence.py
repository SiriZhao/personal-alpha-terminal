"""Contract tests for benchmark evidence computed from the certified PIT frame.

Part 3 requirement 4/5: benchmarks must inherit the strategy's PIT cutoff and
calendar semantics, and must never be fabricated when the symbol is absent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.benchmark import (
    BenchmarkEvidence,
    benchmark_evidence_from_returns,
)


def _returns(symbol_count: int = 2, periods: int = 30) -> pd.DataFrame:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    index = pd.DatetimeIndex(
        [start + timedelta(days=i) for i in range(periods)], tz="UTC"
    )
    frame = pd.DataFrame(index=index)
    for i in range(symbol_count):
        frame[f"SYM{i}"] = np.linspace(0.001, 0.002, periods) + i * 0.0001
    return frame


def test_benchmark_evidence_uses_frame_window_and_convention() -> None:
    frame = _returns()
    evidence = benchmark_evidence_from_returns(frame, "SYM0")
    assert evidence is not None
    assert evidence.symbol == "SYM0"
    assert evidence.observation_count == 30
    assert evidence.start_date == date(2026, 6, 1)
    assert evidence.end_date == date(2026, 6, 30)
    # Same window and same sessions as the strategy frame: no offset by design.
    assert evidence.end_date == frame.index[-1].date()
    expected_return = float(np.prod(1.0 + frame["SYM0"].to_numpy()) - 1.0)
    assert evidence.period_return == expected_return
    expected_vol = float(frame["SYM0"].std(ddof=1) * np.sqrt(252))
    assert evidence.annualized_volatility == expected_vol
    assert evidence.max_drawdown is not None and evidence.max_drawdown <= 0


def test_benchmark_missing_symbol_is_never_fabricated() -> None:
    frame = _returns()
    assert benchmark_evidence_from_returns(frame, "QQQ") is None
    assert benchmark_evidence_from_returns(frame, "") is None


def test_benchmark_empty_or_corrupt_series_is_none() -> None:
    frame = _returns()
    frame.loc[:, "SYM0"] = np.nan
    assert benchmark_evidence_from_returns(frame, "SYM0") is None

    empty = pd.DataFrame({"SYM0": pd.Series(dtype=float)})
    assert benchmark_evidence_from_returns(empty, "SYM0") is None


def test_benchmark_drawdown_sign_and_validation() -> None:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    index = pd.DatetimeIndex([start + timedelta(days=i) for i in range(10)], tz="UTC")
    crash = pd.DataFrame({"SYM0": [-0.05, -0.04, 0.01, 0.02, -0.03, 0.0, 0.0, 0.0, 0.0, 0.0]},
                         index=index)
    evidence = benchmark_evidence_from_returns(crash, "SYM0")
    assert evidence is not None
    assert evidence.max_drawdown is not None
    assert evidence.max_drawdown < 0

    try:
        BenchmarkEvidence("X", 1, date(2026, 1, 2), date(2026, 1, 1), 0.0, 0.1, -0.1)
    except ValueError:
        pass
    else:
        raise AssertionError("inverted benchmark window must be rejected")
    try:
        BenchmarkEvidence("X", 1, date(2026, 1, 1), date(2026, 1, 2), float("nan"), 0.1, -0.1)
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite period return must be rejected")
    try:
        BenchmarkEvidence("X", 1, date(2026, 1, 1), date(2026, 1, 2), 0.01, None, 0.5)
    except ValueError:
        pass
    else:
        raise AssertionError("positive drawdown must be rejected")
