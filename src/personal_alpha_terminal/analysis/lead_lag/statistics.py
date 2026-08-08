import math
import warnings
from collections.abc import Sequence
from typing import Any

from statsmodels.tools.sm_exceptions import InfeasibleTestError
from statsmodels.tsa.stattools import grangercausalitytests

from personal_alpha_terminal.analysis.lead_lag.schemas import LagMetric
from personal_alpha_terminal.analysis.market_graph.schemas import MarketSeries
from personal_alpha_terminal.analysis.relationships.statistics import pearson
from personal_alpha_terminal.analysis.statistical_validation import (
    benjamini_hochberg,
    bonferroni_adjust,
)

__all__ = [
    "align_returns",
    "benjamini_hochberg",
    "bonferroni_adjust",
    "calculate_lag_metrics",
    "cross_correlation",
]


def align_returns(
    source: MarketSeries,
    target: MarketSeries,
) -> tuple[list[float], list[float]]:
    source_by_date = dict(source.returns)
    target_by_date = dict(target.returns)
    common_dates = sorted(source_by_date.keys() & target_by_date.keys())
    return (
        [source_by_date[item] for item in common_dates],
        [target_by_date[item] for item in common_dates],
    )


def cross_correlation(
    source_values: Sequence[float],
    target_values: Sequence[float],
    lag_days: int,
) -> float | None:
    """Corr(source[t], target[t + lag]); positive lag means source leads target."""
    if lag_days < 1 or len(source_values) != len(target_values):
        raise ValueError("lag_days must be positive and series lengths must match")
    if len(source_values) - lag_days < 2:
        return None
    return pearson(
        list(source_values[:-lag_days]),
        list(target_values[lag_days:]),
    )


def calculate_lag_metrics(
    source: MarketSeries,
    target: MarketSeries,
    *,
    maximum_lag_days: int,
    minimum_observations: int,
) -> tuple[LagMetric, ...]:
    source_values, target_values = align_returns(source, target)
    if len(source_values) < minimum_observations:
        return ()
    if len(source_values) <= 3 * maximum_lag_days + 2:
        return ()
    data = [[target, source] for source, target in zip(source_values, target_values, strict=True)]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            results: dict[int, Any] = grangercausalitytests(
                data,
                maxlag=maximum_lag_days,
                verbose=False,
            )
    except (InfeasibleTestError, ValueError):
        return ()

    metrics: list[LagMetric] = []
    for lag_days in range(1, maximum_lag_days + 1):
        correlation = cross_correlation(source_values, target_values, lag_days)
        if correlation is None:
            continue
        f_statistic, p_value, *_ = results[lag_days][0]["ssr_ftest"]
        f_value = float(f_statistic)
        p = float(p_value)
        if not math.isfinite(f_value) or not math.isfinite(p):
            continue
        metrics.append(
            LagMetric(
                lag_days=lag_days,
                cross_correlation=correlation,
                granger_f_statistic=max(0.0, f_value),
                granger_p_value=min(1.0, max(0.0, p)),
                sample_size=len(source_values) - lag_days,
            )
        )
    return tuple(metrics)
