from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr


@dataclass(frozen=True, slots=True)
class FactorEvaluation:
    horizon: int
    pearson_ic: float | None
    spearman_ic: float | None
    mean_ic: float | None
    ic_std: float | None
    icir: float | None
    positive_ic_ratio: float | None
    quantile_returns: tuple[float | None, ...]
    top_bottom_spread: float | None
    long_only_top_return: float | None
    turnover: float | None
    hit_rate: float | None
    rolling_ic: tuple[tuple[str, float], ...]
    sector_stability: dict[str, float | None]
    regime_stability: dict[str, float | None]
    date_count: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class ICDecayReport:
    evaluations: tuple[FactorEvaluation, ...]
    peak_horizon: int | None
    approximate_half_life: float | None
    recommended_rebalance_horizon: int | None


def evaluate_factor(
    panel: pd.DataFrame,
    *,
    signal_column: str,
    forward_return_column: str,
    horizon: int,
    quantiles: int = 5,
    minimum_cross_section: int = 5,
    rolling_window: int = 12,
) -> FactorEvaluation:
    required = {"as_of_date", "permanent_security_id", signal_column, forward_return_column}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"factor evaluation misses columns: {sorted(missing)}")
    frame = panel.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"], errors="raise").dt.date
    frame[signal_column] = pd.to_numeric(frame[signal_column], errors="coerce")
    frame[forward_return_column] = pd.to_numeric(frame[forward_return_column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[signal_column, forward_return_column]
    )
    per_date: list[tuple[object, float, float, int]] = []
    top_sets: list[set[str]] = []
    quantile_values: list[list[float]] = [[] for _ in range(quantiles)]
    top_hits: list[bool] = []
    for as_of, group in frame.groupby("as_of_date", sort=True):
        if len(group) < minimum_cross_section:
            continue
        if group[signal_column].nunique() < 2 or group[forward_return_column].nunique() < 2:
            continue
        pearson = float(pearsonr(group[signal_column], group[forward_return_column]).statistic)
        spearman = float(spearmanr(group[signal_column], group[forward_return_column]).statistic)
        if not (isfinite(pearson) and isfinite(spearman)):
            continue
        per_date.append((as_of, pearson, spearman, len(group)))
        ordinal = group[signal_column].rank(method="first") - 1
        labels = np.minimum(
            quantiles - 1,
            np.floor(ordinal * quantiles / len(group)).astype(int),
        )
        dated_quantiles: list[float | None] = []
        for label in range(quantiles):
            selected = group.loc[labels == label, forward_return_column]
            mean = float(selected.mean()) if not selected.empty else None
            dated_quantiles.append(mean)
            if mean is not None:
                quantile_values[label].append(mean)
        top_ids = set(group.loc[labels == quantiles - 1, "permanent_security_id"].astype(str))
        top_sets.append(top_ids)
        if dated_quantiles[-1] is not None:
            top_hits.append(dated_quantiles[-1] > float(group[forward_return_column].mean()))
    pearsons = [item[1] for item in per_date]
    rank_ics = [item[2] for item in per_date]
    mean_ic = float(np.mean(rank_ics)) if rank_ics else None
    std_ic = float(np.std(rank_ics, ddof=1)) if len(rank_ics) > 1 else None
    average_quantiles = tuple(float(np.mean(items)) if items else None for items in quantile_values)
    turnover_values = []
    for previous, current in zip(top_sets, top_sets[1:], strict=False):
        denominator = max(1, len(previous))
        turnover_values.append(1 - len(previous & current) / denominator)
    rolling = (
        pd.Series(rank_ics, index=[str(item[0]) for item in per_date], dtype=float)
        .rolling(rolling_window, min_periods=max(3, rolling_window // 2))
        .mean()
        .dropna()
    )
    return FactorEvaluation(
        horizon=horizon,
        pearson_ic=float(np.mean(pearsons)) if pearsons else None,
        spearman_ic=mean_ic,
        mean_ic=mean_ic,
        ic_std=std_ic,
        icir=mean_ic / std_ic if mean_ic is not None and std_ic and std_ic > 0 else None,
        positive_ic_ratio=(
            sum(value > 0 for value in rank_ics) / len(rank_ics)
            if rank_ics
            else None
        ),
        quantile_returns=average_quantiles,
        top_bottom_spread=(
            average_quantiles[-1] - average_quantiles[0]
            if average_quantiles[-1] is not None and average_quantiles[0] is not None
            else None
        ),
        long_only_top_return=average_quantiles[-1],
        turnover=float(np.mean(turnover_values)) if turnover_values else None,
        hit_rate=sum(top_hits) / len(top_hits) if top_hits else None,
        rolling_ic=tuple((str(index), float(value)) for index, value in rolling.items()),
        sector_stability=_group_stability(frame, "sector", signal_column, forward_return_column),
        regime_stability=_group_stability(frame, "regime", signal_column, forward_return_column),
        date_count=len(per_date),
        observation_count=sum(item[3] for item in per_date),
    )


def evaluate_ic_decay(
    panel: pd.DataFrame,
    *,
    signal_column: str,
    horizons: tuple[int, ...] = (1, 5, 10, 20, 40, 60, 120),
    minimum_cross_section: int = 5,
) -> ICDecayReport:
    evaluations = tuple(
        evaluate_factor(
            panel,
            signal_column=signal_column,
            forward_return_column=f"forward_return_{horizon}d",
            horizon=horizon,
            minimum_cross_section=minimum_cross_section,
        )
        for horizon in horizons
        if f"forward_return_{horizon}d" in panel
    )
    valid = [item for item in evaluations if item.mean_ic is not None]
    if not valid:
        return ICDecayReport(evaluations, None, None, None)

    def mean_ic_value(item: FactorEvaluation) -> float:
        assert item.mean_ic is not None
        return item.mean_ic

    peak = max(valid, key=lambda item: abs(mean_ic_value(item)))
    half_threshold = abs(mean_ic_value(peak)) / 2
    later = [
        item.horizon
        for item in valid
        if item.horizon > peak.horizon
        and abs(mean_ic_value(item)) <= half_threshold
    ]
    half_life = float(min(later)) if later else None
    recommended = peak.horizon if peak.mean_ic and peak.mean_ic > 0 else None
    return ICDecayReport(evaluations, peak.horizon, half_life, recommended)


def _group_stability(
    frame: pd.DataFrame,
    column: str,
    signal_column: str,
    return_column: str,
) -> dict[str, float | None]:
    if column not in frame:
        return {}
    output: dict[str, float | None] = {}
    for name, group in frame.dropna(subset=[column]).groupby(column, sort=True):
        dated: list[float] = []
        for _as_of, cross_section in group.groupby("as_of_date", sort=True):
            if (
                len(cross_section) < 5
                or cross_section[signal_column].nunique() < 2
                or cross_section[return_column].nunique() < 2
            ):
                continue
            value = float(
                spearmanr(
                    cross_section[signal_column], cross_section[return_column]
                ).statistic
            )
            if isfinite(value):
                dated.append(value)
        output[str(name)] = float(np.mean(dated)) if dated else None
    return output
