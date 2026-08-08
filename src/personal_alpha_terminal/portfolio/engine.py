from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from math import sqrt
from statistics import fmean, stdev

from personal_alpha_terminal.portfolio.schemas import (
    FxSeries,
    PortfolioRiskData,
    PortfolioRiskResult,
    PositionRisk,
    PositionStressImpact,
    RiskPositionData,
    RiskSeriesPoint,
    StressScenario,
    StressTestResult,
)


def calculate_risk(
    data: PortfolioRiskData,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    annual_risk_free_rate: float,
    minimum_observations: int,
    fx_max_staleness_days: int,
    maximum_absolute_beta: float,
    price_max_staleness_days: int = 7,
) -> PortfolioRiskResult:
    if not data.positions:
        raise ValueError("portfolio has no stock or ETF positions")
    if data.cash_balance < 0:
        raise ValueError("negative cash and leveraged portfolios are not supported")
    converted_histories: dict[int, tuple[tuple[date, float], ...]] = {}
    current_values: dict[int, float] = {}
    for position in data.positions:
        history = _converted_history(
            position,
            data.base_currency,
            data.fx_series,
            start_date,
            end_date,
            fx_max_staleness_days,
        )
        if len(history) < 3:
            raise ValueError(f"insufficient price or FX history for {position.instrument.symbol}")
        converted_histories[position.instrument.id] = history
        current_point = next(
            (
                (point_date, value)
                for point_date, value in reversed(history)
                if point_date <= data.as_of_date
            ),
            None,
        )
        if current_point is None:
            raise ValueError(f"missing current valuation for {position.instrument.symbol}")
        current_date, current_price = current_point
        if (data.as_of_date - current_date).days > price_max_staleness_days:
            raise ValueError(
                f"stale valuation price for {position.instrument.symbol}: "
                f"{current_date.isoformat()}"
            )
        current_values[position.instrument.id] = position.quantity * current_price

    invested_value = sum(current_values.values())
    total_value = data.cash_balance + invested_value
    if total_value <= 0:
        raise ValueError("portfolio total value must be positive")
    weights = {stock_id: value / total_value for stock_id, value in current_values.items()}
    return_maps = {stock_id: _returns(history) for stock_id, history in converted_histories.items()}
    benchmark_history = _converted_history(
        RiskPositionData(
            instrument=data.benchmark,
            currency=data.benchmark_currency,
            industry=data.benchmark.industry or "基准",
            quantity=1.0,
            prices=data.benchmark_prices,
        ),
        data.base_currency,
        data.fx_series,
        start_date,
        end_date,
        fx_max_staleness_days,
    )
    benchmark_returns = _returns(benchmark_history)
    common_dates = set(benchmark_returns)
    for values in return_maps.values():
        common_dates &= set(values)
    ordered_dates = sorted(common_dates)
    if len(ordered_dates) < minimum_observations:
        raise ValueError(
            "insufficient common portfolio and benchmark observations; "
            f"need at least {minimum_observations}"
        )
    portfolio_returns = [
        sum(weights[stock_id] * return_maps[stock_id][day] for stock_id in weights)
        for day in ordered_dates
    ]
    aligned_benchmark = [benchmark_returns[day] for day in ordered_dates]
    annualized_return = _annualized_return(portfolio_returns)
    annualized_volatility = stdev(portfolio_returns) * sqrt(252)
    daily_risk_free = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    sharpe = (
        (fmean(portfolio_returns) - daily_risk_free) / stdev(portfolio_returns) * sqrt(252)
        if stdev(portfolio_returns) > 0
        else None
    )
    portfolio_beta = _beta(portfolio_returns, aligned_benchmark)
    equity_curve, drawdown_curve, maximum_drawdown = _curves(
        ordered_dates,
        portfolio_returns,
    )

    industries: defaultdict[str, float] = defaultdict(float)
    currencies: defaultdict[str, float] = defaultdict(float)
    positions: list[PositionRisk] = []
    position_by_id = {item.instrument.id: item for item in data.positions}
    for stock_id, weight in weights.items():
        position = position_by_id[stock_id]
        aligned_asset = [return_maps[stock_id][day] for day in ordered_dates]
        beta = _beta(aligned_asset, aligned_benchmark)
        if beta is not None:
            beta = max(-maximum_absolute_beta, min(maximum_absolute_beta, beta))
        industries[position.industry] += weight
        currencies[position.currency] += weight
        positions.append(
            PositionRisk(
                instrument=position.instrument,
                currency=position.currency,
                industry=position.industry,
                market_value=current_values[stock_id],
                weight=weight,
                beta=beta,
            )
        )
    cash_weight = data.cash_balance / total_value
    industries["现金"] += cash_weight
    currencies[data.base_currency] += cash_weight
    return PortfolioRiskResult(
        run_id=run_id,
        portfolio_id=data.portfolio_id,
        portfolio_name=data.portfolio_name,
        base_currency=data.base_currency,
        as_of_date=data.as_of_date,
        benchmark=data.benchmark,
        total_value=total_value,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=maximum_drawdown,
        sharpe_ratio=sharpe,
        beta=portfolio_beta,
        observation_count=len(ordered_dates),
        positions=tuple(sorted(positions, key=lambda item: item.weight, reverse=True)),
        industry_exposure=dict(industries),
        currency_exposure=dict(currencies),
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
    )


def apply_stress(
    risk: PortfolioRiskResult,
    scenario: StressScenario,
) -> StressTestResult:
    if not -1 <= scenario.benchmark_shock <= 10:
        raise ValueError("benchmark shock must be between -100% and 1000%")
    if any(not -1 <= shock <= 10 for shock in scenario.currency_shocks.values()):
        raise ValueError("currency shocks must be between -100% and 1000%")
    impacts: list[PositionStressImpact] = []
    portfolio_return = 0.0
    uncovered_weight = 0.0
    for position in risk.positions:
        covered = position.beta is not None or scenario.benchmark_shock == 0
        market_return = (
            (position.beta or 0.0) * scenario.benchmark_shock
            if scenario.benchmark_shock != 0
            else 0.0
        )
        market_return = max(-1.0, market_return)
        currency_return = (
            0.0
            if position.currency == risk.base_currency
            else scenario.currency_shocks.get(position.currency, 0.0)
        )
        combined_return = (1 + market_return) * (1 + currency_return) - 1
        contribution = position.weight * combined_return
        portfolio_return += contribution
        if not covered:
            uncovered_weight += position.weight
        impacts.append(
            PositionStressImpact(
                instrument=position.instrument,
                weight=position.weight,
                beta=position.beta,
                market_return=market_return,
                currency_return=currency_return,
                combined_return=combined_return,
                contribution=contribution,
                pnl_amount=risk.total_value * contribution,
                beta_covered=covered,
            )
        )
    pnl_amount = risk.total_value * portfolio_return
    return StressTestResult(
        run_id=risk.run_id,
        scenario=scenario,
        original_value=risk.total_value,
        stressed_value=risk.total_value + pnl_amount,
        pnl_amount=pnl_amount,
        pnl_percent=portfolio_return,
        uncovered_weight=uncovered_weight,
        impacts=tuple(sorted(impacts, key=lambda item: item.contribution)),
    )


def _converted_history(
    position: RiskPositionData,
    target_currency: str,
    fx_series: Sequence[FxSeries],
    start_date: date,
    end_date: date,
    max_staleness_days: int,
) -> tuple[tuple[date, float], ...]:
    results: list[tuple[date, float]] = []
    for point in position.prices:
        if not start_date <= point.date <= end_date:
            continue
        rate = _fx_rate(
            position.currency,
            target_currency,
            point.date,
            fx_series,
            max_staleness_days,
        )
        if rate is not None:
            results.append((point.date, point.close * rate))
    return tuple(results)


def _fx_rate(
    source_currency: str,
    target_currency: str,
    as_of_date: date,
    series: Sequence[FxSeries],
    max_staleness_days: int,
) -> float | None:
    if source_currency == target_currency:
        return 1.0
    for item in series:
        direct = item.base_currency == source_currency and item.quote_currency == target_currency
        inverse = item.base_currency == target_currency and item.quote_currency == source_currency
        if not direct and not inverse:
            continue
        point = next(
            (value for value in reversed(item.values) if value.date <= as_of_date),
            None,
        )
        if point is None or (as_of_date - point.date).days > max_staleness_days:
            continue
        return point.rate if direct else 1 / point.rate
    return None


def _returns(history: Sequence[tuple[date, float]]) -> dict[date, float]:
    results: dict[date, float] = {}
    for index in range(1, len(history)):
        previous = history[index - 1][1]
        if previous > 0:
            results[history[index][0]] = history[index][1] / previous - 1
    return results


def _beta(asset_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float | None:
    if len(asset_returns) != len(benchmark_returns) or len(asset_returns) < 2:
        return None
    benchmark_mean = fmean(benchmark_returns)
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark_returns)
    if variance <= 1e-18:
        return None
    asset_mean = fmean(asset_returns)
    covariance = sum(
        (asset - asset_mean) * (benchmark - benchmark_mean)
        for asset, benchmark in zip(asset_returns, benchmark_returns, strict=True)
    )
    return covariance / variance


def _annualized_return(returns: Sequence[float]) -> float:
    compounded = 1.0
    for daily_return in returns:
        compounded *= 1 + daily_return
    return float(compounded ** (252 / len(returns)) - 1)


def _curves(
    dates: Sequence[date],
    returns: Sequence[float],
) -> tuple[tuple[RiskSeriesPoint, ...], tuple[RiskSeriesPoint, ...], float]:
    equity = 100.0
    peak = equity
    maximum_drawdown = 0.0
    equity_curve: list[RiskSeriesPoint] = []
    drawdown_curve: list[RiskSeriesPoint] = []
    for point_date, daily_return in zip(dates, returns, strict=True):
        equity *= 1 + daily_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        maximum_drawdown = min(maximum_drawdown, drawdown)
        equity_curve.append(RiskSeriesPoint(point_date, equity))
        drawdown_curve.append(RiskSeriesPoint(point_date, drawdown))
    return tuple(equity_curve), tuple(drawdown_curve), maximum_drawdown
