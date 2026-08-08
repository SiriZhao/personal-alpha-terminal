from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean, median, pstdev

import numpy as np
import pandas as pd

from personal_alpha_terminal.analysis.event_study.statistics import (
    moving_block_bootstrap_mean_interval,
)
from personal_alpha_terminal.analysis.statistical_validation import wilson_interval
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    IntelligenceStatus,
    UnifiedEvent,
)
from personal_alpha_terminal.intelligence.time import EventTradingClock


@dataclass(frozen=True, slots=True)
class EventStudyObservation:
    event_id: str
    canonical_cluster_id: str
    symbol: str
    horizon: int
    baseline_session: pd.Timestamp
    outcome_session: pd.Timestamp
    asset_return: float
    benchmark_return: float
    abnormal_return: float
    overlap_flag: bool
    regime: str


@dataclass(frozen=True, slots=True)
class EventStudyStatistic:
    horizon: int
    status: IntelligenceStatus
    sample_size: int
    effective_sample_size: float
    positive_probability: float | None
    positive_probability_interval: tuple[float, float] | None
    mean_return: float | None
    median_return: float | None
    mean_abnormal_return: float | None
    median_abnormal_return: float | None
    return_std: float | None
    mean_confidence_interval: tuple[float, float] | None
    percentiles: dict[int, float]
    worst_return: float | None
    best_return: float | None
    expected_shortfall_5: float | None
    benchmark: str
    regime_distribution: dict[str, int]
    overlap_count: int
    limitation: str | None


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    as_of: datetime
    status: IntelligenceStatus
    observations: tuple[EventStudyObservation, ...]
    statistics: tuple[EventStudyStatistic, ...]
    rejected_event_ids: tuple[str, ...]
    model_version: str = "pit-event-study-v2"


class PointInTimeEventStudyEngine:
    def __init__(
        self,
        *,
        horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
        minimum_sample_size: int = 30,
        bootstrap_resamples: int = 2_000,
        random_seed: int = 42,
        clock: EventTradingClock | None = None,
    ) -> None:
        if minimum_sample_size < 30:
            raise ValueError("event study minimum sample size cannot be below 30")
        if not horizons or any(value < 1 for value in horizons):
            raise ValueError("event study horizons must be positive")
        self.horizons = tuple(sorted(set(horizons)))
        self.minimum_sample_size = minimum_sample_size
        self.bootstrap_resamples = bootstrap_resamples
        self.random_seed = random_seed
        self.clock = clock or EventTradingClock()

    def run(
        self,
        events: tuple[UnifiedEvent, ...],
        *,
        asset_total_returns: dict[str, pd.Series],
        benchmark_total_return: pd.Series,
        benchmark_symbol: str,
        as_of: datetime,
        regime_by_session: dict[object, str] | None = None,
    ) -> EventStudyResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("event-study as_of must be timezone-aware")
        benchmark = _validated_series(benchmark_total_return, benchmark_symbol)
        regimes = regime_by_session or {}
        accepted: list[UnifiedEvent] = []
        rejected: list[str] = []
        for event in events:
            visible_event = event.at_cutoff(as_of)
            if (
                event.backtest_safety is not BacktestSafety.BACKTEST_SAFE
                or visible_event is None
                or event.symbol is None
                or event.symbol not in asset_total_returns
            ):
                rejected.append(event.event_id)
            else:
                accepted.append(visible_event)
        observations: list[EventStudyObservation] = []
        prior_outcome_by_symbol: dict[str, pd.Timestamp] = {}
        for event in sorted(accepted, key=lambda item: (item.observed_at, item.event_id)):
            prices = _validated_series(asset_total_returns[event.symbol or ""], event.symbol or "")
            common = prices.index.intersection(benchmark.index).sort_values()
            if len(common) < max(self.horizons) + 2:
                rejected.append(event.event_id)
                continue
            mapping = self.clock.map(event.observed_at)
            baseline = _session_lookup(common, mapping.last_completed_session)
            if baseline is None:
                rejected.append(event.event_id)
                continue
            baseline_index = int(common.get_loc(baseline))
            previous_outcome = prior_outcome_by_symbol.get(event.symbol or "")
            for horizon in self.horizons:
                terminal_index = baseline_index + horizon
                if terminal_index >= len(common):
                    continue  # right censored
                outcome_session = common[terminal_index]
                if self.clock.session_close(outcome_session) > as_of:
                    continue  # future outcome is invisible at replay cutoff
                start_asset = float(prices.loc[baseline])
                end_asset = float(prices.loc[outcome_session])
                start_benchmark = float(benchmark.loc[baseline])
                end_benchmark = float(benchmark.loc[outcome_session])
                values = (start_asset, end_asset, start_benchmark, end_benchmark)
                if any(not isfinite(value) or value <= 0 for value in values):
                    continue
                asset_return = end_asset / start_asset - 1
                benchmark_return = end_benchmark / start_benchmark - 1
                overlap = previous_outcome is not None and baseline <= previous_outcome
                observations.append(
                    EventStudyObservation(
                        event.event_id,
                        event.canonical_cluster_id or event.event_id,
                        event.symbol or "",
                        horizon,
                        baseline,
                        outcome_session,
                        asset_return,
                        benchmark_return,
                        asset_return - benchmark_return,
                        overlap,
                        regimes.get(outcome_session.date(), "UNKNOWN"),
                    )
                )
            if observations:
                own = [
                    item.outcome_session
                    for item in observations
                    if item.event_id == event.event_id
                ]
                if own:
                    prior_outcome_by_symbol[event.symbol or ""] = max(own)
        statistics = tuple(
            self._aggregate(
                tuple(item for item in observations if item.horizon == horizon),
                horizon=horizon,
                benchmark=benchmark_symbol,
            )
            for horizon in self.horizons
        )
        overall = (
            IntelligenceStatus.READY
            if any(item.status is IntelligenceStatus.READY for item in statistics)
            else IntelligenceStatus.INSUFFICIENT_SAMPLE
        )
        return EventStudyResult(
            as_of, overall, tuple(observations), statistics, tuple(sorted(set(rejected)))
        )

    def _aggregate(
        self,
        observations: tuple[EventStudyObservation, ...],
        *,
        horizon: int,
        benchmark: str,
    ) -> EventStudyStatistic:
        count = len(observations)
        effective = sum(0.5 if item.overlap_flag else 1.0 for item in observations)
        status = (
            IntelligenceStatus.READY
            if effective >= self.minimum_sample_size
            else IntelligenceStatus.INSUFFICIENT_SAMPLE
        )
        if count == 0:
            return EventStudyStatistic(
                horizon, status, 0, 0.0, None, None, None, None, None, None, None,
                None, {}, None, None, None, benchmark, {}, 0, "no observable outcomes",
            )
        returns = [item.asset_return for item in observations]
        abnormal = [item.abnormal_return for item in observations]
        positives = sum(value > 0 for value in abnormal)
        interval = (
            wilson_interval(positives, count, confidence_level=0.95)
            if status is IntelligenceStatus.READY
            else None
        )
        mean_interval = (
            moving_block_bootstrap_mean_interval(
                abnormal,
                confidence_level=0.95,
                resamples=self.bootstrap_resamples,
                random_seed=self.random_seed + horizon * 7919,
            )
            if status is IntelligenceStatus.READY
            else None
        )
        sorted_returns = sorted(returns)
        tail_count = max(1, int(np.ceil(count * 0.05)))
        return EventStudyStatistic(
            horizon=horizon,
            status=status,
            sample_size=count,
            effective_sample_size=effective,
            positive_probability=positives / count,
            positive_probability_interval=interval,
            mean_return=fmean(returns),
            median_return=median(returns),
            mean_abnormal_return=fmean(abnormal),
            median_abnormal_return=median(abnormal),
            return_std=pstdev(returns),
            mean_confidence_interval=mean_interval,
            percentiles={
                percentile: float(np.percentile(returns, percentile))
                for percentile in (5, 25, 75, 95)
            },
            worst_return=min(returns),
            best_return=max(returns),
            expected_shortfall_5=fmean(sorted_returns[:tail_count]),
            benchmark=benchmark,
            regime_distribution=dict(Counter(item.regime for item in observations)),
            overlap_count=sum(item.overlap_flag for item in observations),
            limitation=(
                None
                if status is IntelligenceStatus.READY
                else f"effective sample {effective:.1f} < {self.minimum_sample_size}"
            ),
        )


def _validated_series(series: pd.Series, label: str) -> pd.Series:
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError(f"{label} total-return series must have a DatetimeIndex")
    if not series.index.is_monotonic_increasing or series.index.has_duplicates:
        raise ValueError(f"{label} total-return sessions must be sorted and unique")
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"{label} total-return series contains missing/non-finite values")
    return numeric.astype(float)


def _session_lookup(index: pd.DatetimeIndex, session: pd.Timestamp | None) -> pd.Timestamp | None:
    if session is None:
        return None
    target_date = session.date()
    matches = [value for value in index if value.date() == target_date]
    return matches[0] if len(matches) == 1 else None
