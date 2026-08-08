from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class EventObservation:
    event_id: str
    available_time: datetime
    event_session: pd.Timestamp
    cluster_id: str
    regime: str

    def __post_init__(self) -> None:
        if self.available_time.tzinfo is None or self.event_session.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    sample_size: int
    mean_abnormal_return: float | None
    median_abnormal_return: float | None
    car: float | None
    bhar: float | None
    confidence_interval: tuple[float, float] | None
    expected_shortfall: float | None
    subperiod_stable: bool
    regime_stable: bool
    status: str
    limitations: tuple[str, ...]


def run_event_study(
    *,
    events: tuple[EventObservation, ...],
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    information_cutoff: datetime,
    post_sessions: int = 5,
    minimum_sample_size: int = 20,
    bootstrap_samples: int = 500,
    block_size: int = 5,
    random_seed: int = 0,
    production_adapter_approved: bool = False,
) -> EventStudyResult:
    if information_cutoff.tzinfo is None or post_sessions < 1 or minimum_sample_size < 3:
        raise ValueError("event study timing parameters are invalid")
    aligned = pd.concat(
        [asset_returns.rename("asset"), benchmark_returns.rename("benchmark")], axis=1
    ).dropna()
    if aligned.index.tz is None or not aligned.index.is_monotonic_increasing:
        raise ValueError("event study returns require a sorted timezone-aware session index")
    abnormal_paths: list[np.ndarray] = []
    regimes: list[str] = []
    seen_clusters: set[str] = set()
    limitations: list[str] = []
    for event in sorted(events, key=lambda item: item.available_time):
        if event.available_time > information_cutoff or event.cluster_id in seen_clusters:
            continue
        # First session not earlier than information availability prevents after-close leakage.
        eligible = aligned.index[aligned.index >= pd.Timestamp(event.available_time)]
        if len(eligible) < post_sessions:
            continue
        path = aligned.loc[eligible[:post_sessions], "asset"].to_numpy(dtype=float) - aligned.loc[
            eligible[:post_sessions], "benchmark"
        ].to_numpy(dtype=float)
        if len(path) == post_sessions and np.all(np.isfinite(path)):
            abnormal_paths.append(path)
            regimes.append(event.regime)
            seen_clusters.add(event.cluster_id)
    if len(abnormal_paths) < minimum_sample_size:
        return EventStudyResult(
            len(abnormal_paths), None, None, None, None, None, None, False, False,
            "INSUFFICIENT_SAMPLE", ("right-censored and overlapping events were excluded",),
        )
    matrix = np.vstack(abnormal_paths)
    event_car = matrix.sum(axis=1)
    event_bhar = np.prod(1 + matrix, axis=1) - 1
    rng = np.random.default_rng(random_seed)
    bootstrap_means = _moving_block_bootstrap(
        event_car, bootstrap_samples=bootstrap_samples, block_size=block_size, rng=rng
    )
    interval = tuple(float(value) for value in np.quantile(bootstrap_means, [0.025, 0.975]))
    tail_threshold = float(np.quantile(event_car, 0.05))
    expected_shortfall = float(event_car[event_car <= tail_threshold].mean())
    midpoint = len(event_car) // 2
    first_mean = float(event_car[:midpoint].mean())
    second_mean = float(event_car[midpoint:].mean())
    subperiod_stable = first_mean * second_mean > 0
    regime_means = {
        regime: float(event_car[np.asarray(regimes) == regime].mean())
        for regime in sorted(set(regimes))
        if sum(item == regime for item in regimes) >= 3
    }
    regime_stable = len(regime_means) <= 1 or all(
        value * float(event_car.mean()) >= 0 for value in regime_means.values()
    )
    if not production_adapter_approved:
        limitations.append("supporting evidence only; no locked-OOS production adapter")
    status = (
        "PRODUCTION_SUPPORT_APPROVED"
        if production_adapter_approved and subperiod_stable and regime_stable
        else "RESEARCH_SUPPORT_ONLY"
    )
    return EventStudyResult(
        sample_size=len(event_car),
        mean_abnormal_return=float(event_car.mean()),
        median_abnormal_return=float(np.median(event_car)),
        car=float(event_car.mean()),
        bhar=float(event_bhar.mean()),
        confidence_interval=(interval[0], interval[1]),
        expected_shortfall=expected_shortfall,
        subperiod_stable=subperiod_stable,
        regime_stable=regime_stable,
        status=status,
        limitations=tuple(limitations),
    )


def _moving_block_bootstrap(
    values: np.ndarray,
    *,
    bootstrap_samples: int,
    block_size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if bootstrap_samples < 100 or block_size < 1:
        raise ValueError("bootstrap requires at least 100 samples and positive block size")
    block_size = min(block_size, len(values))
    starts = np.arange(0, len(values) - block_size + 1)
    results = np.empty(bootstrap_samples, dtype=float)
    for sample in range(bootstrap_samples):
        selected: list[float] = []
        while len(selected) < len(values):
            start = int(rng.choice(starts))
            selected.extend(values[start : start + block_size])
        results[sample] = float(np.mean(selected[: len(values)]))
    return results
