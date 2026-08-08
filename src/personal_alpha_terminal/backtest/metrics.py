from math import isfinite, sqrt

from personal_alpha_terminal.backtest.schemas import (
    BacktestMetrics,
    DailyPortfolioPoint,
    HoldingPeriodResult,
    RebalanceRecord,
)

TRADING_SESSIONS_PER_YEAR = 252


def calculate_metrics(
    points: tuple[DailyPortfolioPoint, ...],
    rebalances: tuple[RebalanceRecord, ...],
    holding_periods: tuple[HoldingPeriodResult, ...],
    *,
    initial_capital: float,
    annual_risk_free_rate: float,
) -> BacktestMetrics:
    if not points:
        raise ValueError("cannot calculate metrics without portfolio points")
    total_return = points[-1].nav / initial_capital - 1
    return_count = max(len(points) - 1, 1)
    annualized_return = _geometric_annualize(total_return, return_count)
    daily_returns = [item.daily_return for item in points[1:]]
    annualized_volatility = _sample_std(daily_returns) * sqrt(TRADING_SESSIONS_PER_YEAR)
    risk_free_daily = (1 + annual_risk_free_rate) ** (1 / TRADING_SESSIONS_PER_YEAR) - 1
    excess = [item - risk_free_daily for item in daily_returns]
    daily_std = _sample_std(excess)
    sharpe = (
        sum(excess) / len(excess) / daily_std * sqrt(TRADING_SESSIONS_PER_YEAR)
        if excess and daily_std > 0
        else None
    )
    downside = sqrt(sum(min(item, 0.0) ** 2 for item in excess) / len(excess)) if excess else 0.0
    sortino = (
        sum(excess) / len(excess) / downside * sqrt(TRADING_SESSIONS_PER_YEAR)
        if excess and downside > 0
        else None
    )
    period_returns = [item.net_return for item in holding_periods if item.is_closed]
    winners = [item for item in period_returns if item > 0]
    losers = [item for item in period_returns if item < 0]
    win_rate = len(winners) / len(period_returns) if period_returns else None
    profit_loss = (
        (sum(winners) / len(winners)) / abs(sum(losers) / len(losers))
        if winners and losers
        else None
    )
    executed = [item for item in rebalances if item.status == "executed"]
    total_turnover = sum(item.turnover for item in executed)
    average_turnover = total_turnover / len(executed) if executed else 0.0
    total_cost = sum(item.transaction_cost for item in executed)
    values = (
        total_return,
        annualized_return,
        annualized_volatility,
        points[-1].drawdown,
        total_turnover,
        average_turnover,
        total_cost,
    )
    if not all(isfinite(item) for item in values):
        raise ValueError("backtest metrics contain non-finite values")
    return BacktestMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        maximum_drawdown=min(item.drawdown for item in points),
        period_win_rate=win_rate,
        period_profit_loss_ratio=profit_loss,
        total_turnover=total_turnover,
        average_turnover=average_turnover,
        total_transaction_cost=total_cost,
        annual_returns=_annual_returns(points, initial_capital),
    )


def _geometric_annualize(total_return: float, session_count: int) -> float:
    if total_return <= -1:
        return -1.0
    return float((1 + total_return) ** (TRADING_SESSIONS_PER_YEAR / session_count) - 1)


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sqrt(sum((item - mean) ** 2 for item in values) / (len(values) - 1))


def _annual_returns(
    points: tuple[DailyPortfolioPoint, ...],
    initial_capital: float,
) -> dict[int, float]:
    output: dict[int, float] = {}
    prior_year_end = initial_capital
    by_year: dict[int, list[DailyPortfolioPoint]] = {}
    for point in points:
        by_year.setdefault(point.trade_date.year, []).append(point)
    for year in sorted(by_year):
        year_end = by_year[year][-1].nav
        output[year] = year_end / prior_year_end - 1
        prior_year_end = year_end
    return output
