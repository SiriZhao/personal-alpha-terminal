from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import pandas as pd


@dataclass(frozen=True, slots=True)
class BacktestPerformance:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    maximum_drawdown: float
    positive_period_rate: float | None
    observations: int


def evaluate_equity_curve(
    equity: pd.Series,
    *,
    annual_risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> BacktestPerformance:
    """Calculate transparent daily-equity metrics without calling periods trades."""
    clean = equity.astype(float).dropna()
    if len(clean) < 2 or bool((clean <= 0).any()):
        raise ValueError("equity curve needs at least two finite positive observations")
    returns = clean.pct_change().dropna()
    total_return = float(clean.iloc[-1] / clean.iloc[0] - 1)
    annualized_return = float((1 + total_return) ** (periods_per_year / len(returns)) - 1)
    volatility = float(returns.std(ddof=1) * sqrt(periods_per_year)) if len(returns) > 1 else 0.0
    daily_rf = (1 + annual_risk_free_rate) ** (1 / periods_per_year) - 1
    excess = returns - daily_rf
    excess_std = float(excess.std(ddof=1)) if len(excess) > 1 else 0.0
    sharpe = (
        float(excess.mean() / excess_std * sqrt(periods_per_year))
        if excess_std > 0
        else None
    )
    drawdown = clean / clean.cummax() - 1
    return BacktestPerformance(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        maximum_drawdown=float(drawdown.min()),
        positive_period_rate=float((returns > 0).mean()) if len(returns) else None,
        observations=len(returns),
    )
