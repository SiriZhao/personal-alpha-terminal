from collections.abc import Sequence
from datetime import date, timedelta
from math import ceil, sqrt
from statistics import fmean, stdev

from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorBacktestPeriodResult,
    FactorBacktestSummaryResult,
    FactorDataset,
    FactorFinancialPoint,
    FactorStockScore,
)
from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc

FACTOR_DIRECTIONS = {
    "pe": "low",
    "pb": "low",
    "fcf_yield": "high",
    "revenue_growth": "high",
    "eps_growth": "high",
    "roe": "high",
    "roic": "high",
    "momentum": "high",
    "volatility": "low",
}
CATEGORIES = {
    "value": ("pe", "pb", "fcf_yield"),
    "growth": ("revenue_growth", "eps_growth"),
    "quality": ("roe", "roic"),
    "momentum": ("momentum",),
    "volatility": ("volatility",),
}


def calculate_factor_scores(
    dataset: FactorDataset,
    *,
    as_of_date: date,
    momentum_lookback: int,
    momentum_skip: int,
    volatility_window: int,
    minimum_categories: int,
) -> tuple[FactorStockScore, ...]:
    raw_by_id: dict[int, dict[str, float | None]] = {}
    assets_by_id = {asset.instrument.id: asset for asset in dataset.assets}
    for asset in dataset.assets:
        raw = _raw_factors(
            asset,
            as_of_date=as_of_date,
            momentum_lookback=momentum_lookback,
            momentum_skip=momentum_skip,
            volatility_window=volatility_window,
        )
        if raw is not None:
            raw_by_id[asset.instrument.id] = raw

    normalized_by_id: dict[int, dict[str, float | None]] = {
        stock_id: {factor: None for factor in FACTOR_DIRECTIONS} for stock_id in raw_by_id
    }
    for factor, direction in FACTOR_DIRECTIONS.items():
        observations: list[tuple[int, float]] = []
        for stock_id, raw in raw_by_id.items():
            value = raw[factor]
            if value is not None:
                observations.append((stock_id, value))
        ranked = _percentile_scores(
            observations,
            high_is_better=direction == "high",
        )
        for stock_id, score in ranked.items():
            normalized_by_id[stock_id][factor] = score

    results: list[FactorStockScore] = []
    for stock_id, raw in raw_by_id.items():
        normalized = normalized_by_id[stock_id]
        categories: dict[str, float | None] = {}
        for category, factors in CATEGORIES.items():
            available: list[float] = []
            for factor in factors:
                value = normalized[factor]
                if value is not None:
                    available.append(value)
            categories[category] = fmean(available) if available else None
        available_categories = [value for value in categories.values() if value is not None]
        if len(available_categories) < minimum_categories:
            continue
        results.append(
            FactorStockScore(
                as_of_date=as_of_date,
                instrument=assets_by_id[stock_id].instrument,
                raw_factors=raw,
                normalized_factors=normalized,
                category_scores=categories,
                factor_score=fmean(available_categories),
                category_coverage=len(available_categories),
            )
        )
    return tuple(
        sorted(
            results,
            key=lambda item: (-item.factor_score, item.instrument.symbol),
        )
    )


def backtest_period(
    dataset: FactorDataset,
    scores: Sequence[FactorStockScore],
    *,
    selection_quantile: float,
    holding_period: int,
) -> FactorBacktestPeriodResult | None:
    if not scores:
        return None
    selected_count = max(1, ceil(len(scores) * selection_quantile))
    selected_scores = tuple(scores[:selected_count])
    assets_by_id = {asset.instrument.id: asset for asset in dataset.assets}
    portfolio_observations = [
        observation
        for score in selected_scores
        if (
            observation := _forward_return(
                assets_by_id[score.instrument.id],
                score.as_of_date,
                holding_period,
            )
        )
        is not None
    ]
    benchmark_observations = [
        observation
        for score in scores
        if (
            observation := _forward_return(
                assets_by_id[score.instrument.id],
                score.as_of_date,
                holding_period,
            )
        )
        is not None
    ]
    if len(portfolio_observations) != len(selected_scores) or len(benchmark_observations) != len(
        scores
    ):
        return None
    selected_ids = {score.instrument.id for score in selected_scores}
    selected_with_returns = tuple(
        assets_by_id[stock_id].instrument
        for stock_id, _, _ in portfolio_observations
        if stock_id in selected_ids
    )
    return FactorBacktestPeriodResult(
        rebalance_date=selected_scores[0].as_of_date,
        period_end_date=max(item[2] for item in portfolio_observations),
        selected=selected_with_returns,
        portfolio_return=fmean(item[1] for item in portfolio_observations),
        benchmark_return=fmean(item[1] for item in benchmark_observations),
        excess_return=(
            fmean(item[1] for item in portfolio_observations)
            - fmean(item[1] for item in benchmark_observations)
        ),
    )


def summarize_backtest(
    periods: Sequence[FactorBacktestPeriodResult],
    *,
    holding_period: int,
    annual_risk_free_rate: float,
) -> FactorBacktestSummaryResult:
    if not periods:
        raise ValueError("backtest requires at least one completed period")
    ordered_periods = sorted(periods, key=lambda item: item.rebalance_date)
    for previous, current in zip(
        ordered_periods,
        ordered_periods[1:],
        strict=False,
    ):
        if current.rebalance_date < previous.period_end_date:
            raise ValueError("backtest periods overlap and cannot be compounded")
    portfolio_returns = [item.portfolio_return for item in ordered_periods]
    benchmark_returns = [item.benchmark_return for item in ordered_periods]
    cumulative = _compound(portfolio_returns)
    benchmark_cumulative = _compound(benchmark_returns)
    elapsed_days = (ordered_periods[-1].period_end_date - ordered_periods[0].rebalance_date).days
    if elapsed_days <= 0:
        raise ValueError("backtest elapsed time must be positive")
    years = elapsed_days / 365.2425
    periods_per_year = len(ordered_periods) / years
    annualized_return = (1 + cumulative) ** (1 / years) - 1
    annualized_volatility = (
        stdev(portfolio_returns) * sqrt(periods_per_year) if len(portfolio_returns) >= 2 else 0.0
    )
    period_risk_free = (1 + annual_risk_free_rate) ** (1 / periods_per_year) - 1
    sharpe = (
        (fmean(portfolio_returns) - period_risk_free)
        / stdev(portfolio_returns)
        * sqrt(periods_per_year)
        if len(portfolio_returns) >= 2 and stdev(portfolio_returns) > 0
        else None
    )
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for period_return in portfolio_returns:
        equity *= 1 + period_return
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, equity / peak - 1)
    return FactorBacktestSummaryResult(
        period_count=len(periods),
        cumulative_return=cumulative,
        benchmark_cumulative_return=benchmark_cumulative,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe,
        max_drawdown=maximum_drawdown,
        excess_hit_rate=(
            sum(item.excess_return > 0 for item in ordered_periods) / len(ordered_periods)
        ),
    )


def rebalance_dates(
    dataset: FactorDataset,
    *,
    start_date: date,
    end_date: date,
    interval: int,
) -> tuple[date, ...]:
    dates = sorted(
        {
            point.date
            for asset in dataset.assets
            for point in asset.prices
            if start_date <= point.date <= end_date
        }
    )
    return tuple(dates[index] for index in range(0, len(dates), interval))


def _raw_factors(
    asset: FactorAssetData,
    *,
    as_of_date: date,
    momentum_lookback: int,
    momentum_skip: int,
    volatility_window: int,
) -> dict[str, float | None] | None:
    price_index = next(
        (
            index
            for index in range(len(asset.prices) - 1, -1, -1)
            if asset.prices[index].date <= as_of_date
        ),
        None,
    )
    if price_index is None:
        return None
    current_price = asset.prices[price_index].close
    valuation_price = asset.prices[price_index].raw_close or current_price
    information_cutoff = market_close_utc(as_of_date, asset.instrument.market)
    visible_financials = [
        item
        for item in asset.financials
        if item.period_end <= as_of_date and normalize_utc(item.available_at) <= information_cutoff
    ]
    latest = (
        max(visible_financials, key=lambda item: (item.available_at, item.period_end))
        if visible_financials
        else None
    )
    prior = _prior_year_record(visible_financials, latest) if latest else None
    momentum = None
    if price_index >= momentum_lookback and momentum_lookback > momentum_skip:
        start_price = asset.prices[price_index - momentum_lookback].close
        end_price = asset.prices[price_index - momentum_skip].close
        if start_price > 0:
            momentum = end_price / start_price - 1
    volatility = None
    if price_index >= volatility_window:
        closes = [
            item.close for item in asset.prices[price_index - volatility_window : price_index + 1]
        ]
        returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(1, len(closes))
            if closes[index - 1] > 0
        ]
        if len(returns) >= 2:
            volatility = stdev(returns) * sqrt(252)

    pe = latest.pe if latest and latest.pe is not None and latest.pe > 0 else None
    pb = latest.pb if latest and latest.pb is not None and latest.pb > 0 else None
    fcf_yield = None
    if (
        latest
        and latest.period_type in {"annual", "ttm"}
        and latest.free_cash_flow is not None
        and latest.shares_outstanding is not None
        and latest.shares_outstanding > 0
        and valuation_price > 0
    ):
        fcf_yield = latest.free_cash_flow / (valuation_price * latest.shares_outstanding)
    return {
        "pe": pe,
        "pb": pb,
        "fcf_yield": fcf_yield,
        "revenue_growth": _growth(
            latest.revenue if latest else None,
            prior.revenue if prior else None,
        ),
        "eps_growth": _growth(
            latest.eps if latest else None,
            prior.eps if prior else None,
        ),
        "roe": latest.roe if latest else None,
        "roic": latest.roic if latest else None,
        "momentum": momentum,
        "volatility": volatility,
    }


def _prior_year_record(
    financials: Sequence[FactorFinancialPoint],
    latest: FactorFinancialPoint,
) -> FactorFinancialPoint | None:
    cutoff = latest.period_end - timedelta(days=300)
    candidates = [
        item
        for item in financials
        if item.period_type == latest.period_type and item.period_end <= cutoff
    ]
    return max(candidates, key=lambda item: item.period_end) if candidates else None


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or abs(prior) <= 1e-12:
        return None
    return (current - prior) / abs(prior)


def _percentile_scores(
    values: Sequence[tuple[int, float]],
    *,
    high_is_better: bool,
) -> dict[int, float]:
    if not values:
        return {}
    ordered = sorted(values, key=lambda item: item[1])
    if len(ordered) == 1:
        return {ordered[0][0]: 50.0}
    results: dict[int, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_position = (index + end - 1) / 2
        percentile = average_position / (len(ordered) - 1) * 100
        score = percentile if high_is_better else 100 - percentile
        for position in range(index, end):
            results[ordered[position][0]] = score
        index = end
    return results


def _forward_return(
    asset: FactorAssetData,
    as_of_date: date,
    holding_period: int,
) -> tuple[int, float, date] | None:
    entry_index = next(
        (
            index
            for index in range(len(asset.prices) - 1, -1, -1)
            if asset.prices[index].date <= as_of_date
        ),
        None,
    )
    if entry_index is None or entry_index + holding_period >= len(asset.prices):
        return None
    entry = asset.prices[entry_index]
    exit_point = asset.prices[entry_index + holding_period]
    if entry.close <= 0:
        return None
    return asset.instrument.id, exit_point.close / entry.close - 1, exit_point.date


def _compound(returns: Sequence[float]) -> float:
    value = 1.0
    for period_return in returns:
        value *= 1 + period_return
    return value - 1
