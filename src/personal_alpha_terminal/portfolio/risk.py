from collections import defaultdict
from datetime import date
from math import sqrt
from statistics import fmean, stdev

from personal_alpha_terminal.application.view_models import (
    Exposure,
    PortfolioOption,
    PortfolioRiskView,
    RiskMetrics,
    SeriesPoint,
)


def calculate_portfolio_risk(
    *,
    portfolio: PortfolioOption,
    weights: dict[int, float],
    histories: dict[int, tuple[tuple[date, float], ...]],
    markets: dict[int, str],
    industries: dict[int, str],
    annual_risk_free_rate: float,
) -> PortfolioRiskView:
    if not weights:
        return _unavailable(portfolio, "组合没有可估值持仓。")
    if any(weight < 0 for weight in weights.values()):
        return _unavailable(portfolio, "基础风险页暂不支持空头持仓。")
    if any(len(histories.get(stock_id, ())) < 3 for stock_id in weights):
        return _unavailable(portfolio, "至少一项持仓缺少足够的历史价格。")

    return_maps = {stock_id: _returns_by_date(histories[stock_id]) for stock_id in weights}
    common_dates = set.intersection(*(set(values) for values in return_maps.values()))
    ordered_dates = sorted(common_dates)
    if len(ordered_dates) < 2:
        return _unavailable(portfolio, "不同市场价格无法形成足够的共同交易日。")

    portfolio_returns = [
        sum(weights[stock_id] * return_maps[stock_id][day] for stock_id in weights)
        for day in ordered_dates
    ]
    equity_points, drawdown_points, max_drawdown = _curves(
        ordered_dates,
        portfolio_returns,
    )

    daily_mean = fmean(portfolio_returns)
    daily_volatility = stdev(portfolio_returns)
    annualized_volatility = daily_volatility * sqrt(252)
    compounded = 1.0
    for daily_return in portfolio_returns:
        compounded *= 1 + daily_return
    annualized_return = compounded ** (252 / len(portfolio_returns)) - 1
    daily_risk_free = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    sharpe_ratio = (
        (daily_mean - daily_risk_free) / daily_volatility * sqrt(252)
        if daily_volatility > 0
        else None
    )
    sorted_returns = sorted(portfolio_returns)
    percentile_index = max(0, int(0.05 * (len(sorted_returns) - 1)))
    daily_var_95 = max(0.0, -sorted_returns[percentile_index])
    invested_weight = sum(weights.values())
    normalized_weights = (
        [weight / invested_weight for weight in weights.values()] if invested_weight > 0 else []
    )
    top_position_weight = max(normalized_weights, default=0.0)
    concentration = sum(weight**2 for weight in normalized_weights)
    effective_positions = 1 / concentration if concentration > 0 else 0.0
    cash_weight = max(0.0, 1 - invested_weight)

    return PortfolioRiskView(
        portfolio=portfolio,
        available=True,
        reason=None,
        metrics=RiskMetrics(
            annualized_return=annualized_return,
            annualized_volatility=annualized_volatility,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            daily_var_95=daily_var_95,
            top_position_weight=top_position_weight,
            effective_positions=effective_positions,
            observations=len(portfolio_returns),
        ),
        equity_curve=equity_points,
        drawdown_curve=drawdown_points,
        market_exposure=_aggregate_exposure(weights, markets, cash_weight),
        industry_exposure=_aggregate_exposure(weights, industries, cash_weight),
    )


def _returns_by_date(history: tuple[tuple[date, float], ...]) -> dict[date, float]:
    returns: dict[date, float] = {}
    previous: float | None = None
    for day, close in history:
        if previous is not None and previous > 0:
            returns[day] = close / previous - 1
        previous = close
    return returns


def _curves(
    dates: list[date],
    returns: list[float],
) -> tuple[tuple[SeriesPoint, ...], tuple[SeriesPoint, ...], float]:
    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    equity_curve: list[SeriesPoint] = []
    drawdown_curve: list[SeriesPoint] = []

    for day, daily_return in zip(dates, returns, strict=True):
        equity *= 1 + daily_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        max_drawdown = min(max_drawdown, drawdown)
        equity_curve.append(SeriesPoint(day, equity))
        drawdown_curve.append(SeriesPoint(day, drawdown))

    return tuple(equity_curve), tuple(drawdown_curve), max_drawdown


def _aggregate_exposure(
    weights: dict[int, float],
    labels: dict[int, str],
    cash_weight: float,
) -> tuple[Exposure, ...]:
    totals: defaultdict[str, float] = defaultdict(float)
    for stock_id, weight in weights.items():
        totals[labels.get(stock_id, "未分类")] += weight
    if cash_weight > 0:
        totals["现金"] += cash_weight
    return tuple(
        Exposure(name=name, weight=weight)
        for name, weight in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    )


def _unavailable(portfolio: PortfolioOption, reason: str) -> PortfolioRiskView:
    return PortfolioRiskView(
        portfolio=portfolio,
        available=False,
        reason=reason,
        metrics=None,
    )
