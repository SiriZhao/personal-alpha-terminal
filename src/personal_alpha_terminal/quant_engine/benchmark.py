"""Benchmark evidence computed from the SAME certified PIT return frame.

A benchmark row is only produced from returns that already passed the daily
data gate and PIT assembly; it inherits the strategy's cutoff, calendar and
timezone semantics.  When a configured benchmark is absent from the certified
frame, no statistics are fabricated: the evidence is ``None`` and the caller
must display NOT_AVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    symbol: str
    observation_count: int
    start_date: date
    end_date: date
    period_return: float
    annualized_volatility: float | None
    max_drawdown: float | None

    def __post_init__(self) -> None:
        if self.observation_count < 1:
            raise ValueError("benchmark evidence requires at least one observation")
        if self.start_date > self.end_date:
            raise ValueError("benchmark evidence window is inverted")
        if not np.isfinite(self.period_return):
            raise ValueError("benchmark period return must be finite")
        if self.annualized_volatility is not None and (
            not np.isfinite(self.annualized_volatility)
            or self.annualized_volatility < 0
        ):
            raise ValueError("benchmark volatility must be finite and non-negative")
        if self.max_drawdown is not None and (
            not np.isfinite(self.max_drawdown) or self.max_drawdown > 0
        ):
            raise ValueError("benchmark drawdown must be finite and non-positive")


def benchmark_evidence_from_returns(
    returns: pd.DataFrame,
    symbol: str,
    *,
    annualization_sessions: int = 252,
) -> BenchmarkEvidence | None:
    """Compute benchmark statistics from the shared PIT return frame.

    Returns ``None`` when the symbol is missing or has no usable observations;
    the caller must render NOT_AVAILABLE rather than inventing numbers.
    """

    if symbol not in returns.columns:
        return None
    series = pd.to_numeric(returns[symbol], errors="coerce").dropna()
    if series.empty:
        return None
    values = series.to_numpy(dtype=float)
    if np.any(~np.isfinite(values)):
        return None
    wealth = np.cumprod(1.0 + values)
    running_max = np.maximum.accumulate(wealth)
    max_drawdown = float(np.min(wealth / running_max - 1.0)) if len(wealth) else None
    volatility = (
        float(series.std(ddof=1) * np.sqrt(annualization_sessions))
        if len(series) > 1
        else None
    )
    return BenchmarkEvidence(
        symbol=symbol,
        observation_count=len(series),
        start_date=series.index[0].date(),
        end_date=series.index[-1].date(),
        period_return=float(np.prod(1.0 + values) - 1.0),
        annualized_volatility=volatility,
        max_drawdown=max_drawdown,
    )
