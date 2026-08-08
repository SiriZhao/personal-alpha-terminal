from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from math import ceil
from statistics import fmean, median, pstdev

import numpy as np

from personal_alpha_terminal.analysis.event_study.schemas import (
    EventMatch,
    EventOutcome,
    EventStatistic,
    InstrumentOption,
    PriceBar,
)
from personal_alpha_terminal.analysis.statistical_validation import wilson_interval
from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc


def calculate_outcomes(
    events: Sequence[EventMatch],
    target: InstrumentOption,
    bars: tuple[PriceBar, ...],
    *,
    trigger_market: str,
    horizons: tuple[int, ...],
    win_threshold: float,
) -> tuple[EventOutcome, ...]:
    outcomes: list[EventOutcome] = []
    target_available_times = [
        normalize_utc(bar.available_time)
        if bar.available_time is not None
        else market_close_utc(bar.date, target.market)
        for bar in bars
    ]
    for event in events:
        event_known_at = (
            normalize_utc(event.available_time)
            if event.available_time is not None
            else market_close_utc(event.date, trigger_market)
        )
        future_start = bisect_right(target_available_times, event_known_at)
        baseline_index = future_start - 1
        if baseline_index < 0:
            continue
        baseline = bars[baseline_index]
        if baseline.close <= 0:
            continue
        for horizon in horizons:
            terminal_index = future_start + horizon - 1
            if terminal_index >= len(bars):
                continue
            path = bars[baseline_index : terminal_index + 1]
            terminal = path[-1]
            forward_return = terminal.close / baseline.close - 1
            relative_path = [bar.close / baseline.close - 1 for bar in path]
            max_upside = max(relative_path)
            peak = path[0].close
            max_drawdown = 0.0
            for bar in path[1:]:
                peak = max(peak, bar.close)
                max_drawdown = min(max_drawdown, bar.close / peak - 1)
            outcomes.append(
                EventOutcome(
                    event=event,
                    target=target,
                    horizon_days=horizon,
                    baseline_date=baseline.date,
                    horizon_date=terminal.date,
                    forward_return=forward_return,
                    max_upside=max_upside,
                    max_drawdown=max_drawdown,
                    is_win=forward_return > win_threshold,
                )
            )
    return tuple(outcomes)


def aggregate_outcomes(
    outcomes: Sequence[EventOutcome],
    *,
    minimum_sample_size: int = 30,
    confidence_level: float = 0.95,
    bootstrap_resamples: int = 10_000,
    random_seed: int = 42,
) -> tuple[EventStatistic, ...]:
    if minimum_sample_size < 30:
        raise ValueError("event-study minimum sample size must be at least 30")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if bootstrap_resamples < 1_000:
        raise ValueError("bootstrap_resamples must be at least 1000")
    grouped: defaultdict[tuple[int, int], list[EventOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[(outcome.target.id, outcome.horizon_days)].append(outcome)

    statistics: list[EventStatistic] = []
    for (_, horizon), items in grouped.items():
        target = items[0].target
        returns = [item.forward_return for item in items]
        max_upside = [item.max_upside for item in items]
        max_drawdown = [item.max_drawdown for item in items]
        sample_size = len(items)
        positive_count = sum(value > 0 for value in returns)
        win_count = sum(item.is_win for item in items)
        meets_minimum = sample_size >= minimum_sample_size
        positive_interval = (
            wilson_interval(
                positive_count,
                sample_size,
                confidence_level=confidence_level,
            )
            if meets_minimum
            else (None, None)
        )
        win_interval = (
            wilson_interval(
                win_count,
                sample_size,
                confidence_level=confidence_level,
            )
            if meets_minimum
            else (None, None)
        )
        mean_interval = (
            moving_block_bootstrap_mean_interval(
                returns,
                confidence_level=confidence_level,
                resamples=bootstrap_resamples,
                random_seed=random_seed + target.id * 1009 + horizon * 9176,
            )
            if meets_minimum
            else (None, None)
        )
        statistics.append(
            EventStatistic(
                target=target,
                horizon_days=horizon,
                sample_size=sample_size,
                positive_probability=positive_count / sample_size,
                win_rate=win_count / sample_size,
                average_return=fmean(returns),
                median_return=median(returns),
                return_stddev=pstdev(returns),
                best_return=max(returns),
                worst_return=min(returns),
                average_max_upside=fmean(max_upside),
                best_max_upside=max(max_upside),
                average_max_drawdown=fmean(max_drawdown),
                worst_max_drawdown=min(max_drawdown),
                meets_minimum=meets_minimum,
                confidence_level=confidence_level,
                positive_probability_lower=positive_interval[0],
                positive_probability_upper=positive_interval[1],
                win_rate_lower=win_interval[0],
                win_rate_upper=win_interval[1],
                average_return_lower=mean_interval[0],
                average_return_upper=mean_interval[1],
            )
        )
    return tuple(
        sorted(
            statistics,
            key=lambda item: (item.horizon_days, item.target.market, item.target.symbol),
        )
    )


def moving_block_bootstrap_mean_interval(
    values: Sequence[float],
    *,
    confidence_level: float,
    resamples: int,
    random_seed: int,
    block_size: int | None = None,
) -> tuple[float, float]:
    """Percentile interval using contiguous blocks to retain local dependence."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if resamples < 1_000:
        raise ValueError("resamples must be at least 1000")
    observations = np.asarray(values, dtype=float)
    if not np.isfinite(observations).all():
        raise ValueError("values must be finite")
    sample_size = len(observations)
    resolved_block_size = block_size or max(1, ceil(sample_size ** (1 / 3)))
    if not 1 <= resolved_block_size <= sample_size:
        raise ValueError("block_size must be between one and sample size")

    rng = np.random.default_rng(random_seed)
    block_starts = np.arange(sample_size)
    block_offsets = np.arange(resolved_block_size)
    block_count = ceil(sample_size / resolved_block_size)
    means = np.empty(resamples, dtype=float)
    for index in range(resamples):
        starts = rng.choice(block_starts, size=block_count, replace=True)
        indices = (starts[:, None] + block_offsets) % sample_size
        means[index] = float(observations[indices.ravel()[:sample_size]].mean())
    tail = (1 - confidence_level) / 2
    lower, upper = np.quantile(means, (tail, 1 - tail))
    return float(lower), float(upper)
