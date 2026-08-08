from dataclasses import dataclass
from math import sqrt

import pandas as pd

from personal_alpha_terminal.quant_engine.risk.drawdown import maximum_drawdown


@dataclass(frozen=True, slots=True)
class PortfolioRiskMetrics:
    annualized_volatility: float
    maximum_drawdown: float
    beta: float | None
    top_position_weight: float
    concentration_hhi: float
    observations: int


def calculate_portfolio_risk(
    returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    benchmark_returns: pd.Series | None = None,
) -> PortfolioRiskMetrics:
    if not weights or any(weight < 0 for weight in weights.values()):
        raise ValueError("portfolio risk requires non-negative holdings")
    missing = set(weights) - set(returns.columns)
    if missing:
        raise ValueError(f"missing return series: {sorted(missing)}")
    aligned = returns[list(weights)].dropna()
    if len(aligned) < 2:
        raise ValueError("portfolio risk requires at least two aligned return observations")
    portfolio_returns = aligned.mul(pd.Series(weights), axis=1).sum(axis=1)
    equity = (1 + portfolio_returns).cumprod()
    volatility = float(portfolio_returns.std(ddof=1) * sqrt(252))
    beta = None
    if benchmark_returns is not None:
        pair = pd.concat(
            [portfolio_returns, benchmark_returns.rename("benchmark")], axis=1, sort=False
        ).dropna()
        variance = float(pair["benchmark"].var(ddof=1)) if len(pair) > 1 else 0.0
        if variance > 0:
            beta = float(pair.iloc[:, 0].cov(pair["benchmark"]) / variance)
    invested = sum(weights.values())
    normalized = [weight / invested for weight in weights.values()] if invested > 0 else []
    return PortfolioRiskMetrics(
        annualized_volatility=volatility,
        maximum_drawdown=maximum_drawdown(equity),
        beta=beta,
        top_position_weight=max(weights.values()),
        concentration_hhi=sum(weight**2 for weight in normalized),
        observations=len(portfolio_returns),
    )
