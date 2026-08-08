from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date
from math import isfinite
from statistics import fmean, median, stdev

from scipy.stats import pearsonr, spearmanr, ttest_1samp

from personal_alpha_terminal.alpha_discovery.schemas import (
    FactorDefinition,
    FactorObservation,
    FactorPanel,
    ICEvaluation,
    SplitName,
)


def evaluate_factor(
    panel: FactorPanel,
    factor_name: str,
    *,
    split_name: SplitName = "full",
    dates: Iterable[date] | None = None,
    minimum_cross_section: int = 5,
    minimum_dates: int = 5,
) -> ICEvaluation:
    """Evaluate cross-sectional Rank IC or de-duplicated market time-series IC."""

    definition = _definition(panel, factor_name)
    allowed_dates = set(dates) if dates is not None else None
    selected = tuple(
        item
        for item in panel.observations
        if allowed_dates is None or item.as_of_date in allowed_dates
    )
    if definition.scope == "time_series":
        return _evaluate_time_series(
            selected,
            definition,
            split_name=split_name,
            minimum_dates=minimum_dates,
        )
    return _evaluate_cross_section(
        selected,
        definition,
        split_name=split_name,
        minimum_cross_section=minimum_cross_section,
        minimum_dates=minimum_dates,
    )


def evaluate_factor_library(
    panel: FactorPanel,
    *,
    split_name: SplitName = "full",
    dates: Iterable[date] | None = None,
    minimum_cross_section: int = 5,
    minimum_dates: int = 5,
    fdr_alpha: float = 0.10,
) -> tuple[ICEvaluation, ...]:
    evaluations = tuple(
        evaluate_factor(
            panel,
            definition.name,
            split_name=split_name,
            dates=dates,
            minimum_cross_section=minimum_cross_section,
            minimum_dates=minimum_dates,
        )
        for definition in panel.definitions
    )
    return adjust_evaluation_p_values(evaluations, alpha=fdr_alpha)


def adjust_evaluation_p_values(
    evaluations: Sequence[ICEvaluation],
    *,
    alpha: float,
) -> tuple[ICEvaluation, ...]:
    valid = [
        (index, item.p_value)
        for index, item in enumerate(evaluations)
        if item.p_value is not None and isfinite(item.p_value)
    ]
    adjusted = benjamini_hochberg([float(item[1]) for item in valid])
    by_index = {
        original_index: adjusted_value
        for (original_index, _), adjusted_value in zip(valid, adjusted, strict=True)
    }
    return tuple(
        replace(
            item,
            adjusted_p_value=by_index.get(index),
            significant=(by_index.get(index) is not None and float(by_index[index]) <= alpha),
            confidence_score=_confidence_score(
                item.date_count,
                by_index.get(index),
                item.positive_ratio,
            ),
        )
        for index, item in enumerate(evaluations)
    )


def benjamini_hochberg(p_values: Sequence[float]) -> tuple[float, ...]:
    """Return monotone Benjamini-Hochberg adjusted p-values."""

    if any(not isfinite(value) or value < 0 or value > 1 for value in p_values):
        raise ValueError("p-values must be finite and between 0 and 1")
    count = len(p_values)
    if count == 0:
        return ()
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    results = [1.0] * count
    running = 1.0
    for reverse_rank in range(count - 1, -1, -1):
        original_index, value = ordered[reverse_rank]
        rank = reverse_rank + 1
        running = min(running, value * count / rank)
        results[original_index] = min(1.0, running)
    return tuple(results)


def validate_non_overlapping_panel(panel: FactorPanel) -> None:
    """Reject overlapping forward-label windows that overstate effective samples."""

    grouped = _group_by_date(panel.observations)
    ordered_dates = sorted(grouped)
    for current_date, next_date in zip(ordered_dates, ordered_dates[1:], strict=False):
        latest_end = max(item.forward_end_date for item in grouped[current_date])
        if next_date < latest_end:
            raise ValueError(
                "forward-return windows overlap: "
                f"{current_date} ends {latest_end}, next formation is {next_date}"
            )


def _evaluate_cross_section(
    observations: Sequence[FactorObservation],
    definition: FactorDefinition,
    *,
    split_name: SplitName,
    minimum_cross_section: int,
    minimum_dates: int,
) -> ICEvaluation:
    rank_ics: list[float] = []
    pearson_ics: list[float] = []
    used_observations = 0
    for dated in _group_by_date(observations).values():
        pairs = [
            (value, item.forward_return)
            for item in dated
            if (value := item.factor_values.get(definition.name)) is not None
            and isfinite(value)
            and isfinite(item.forward_return)
        ]
        if len(pairs) < minimum_cross_section:
            continue
        factor_values = [item[0] for item in pairs]
        returns = [item[1] for item in pairs]
        if _constant(factor_values) or _constant(returns):
            continue
        rank_value = float(spearmanr(factor_values, returns).statistic)
        linear_value = float(pearsonr(factor_values, returns).statistic)
        if isfinite(rank_value):
            rank_ics.append(rank_value)
            used_observations += len(pairs)
        if isfinite(linear_value):
            pearson_ics.append(linear_value)
    return _summarize_ic_series(
        definition,
        split_name=split_name,
        rank_ics=rank_ics,
        pearson_ics=pearson_ics,
        observation_count=used_observations,
        minimum_dates=minimum_dates,
    )


def _evaluate_time_series(
    observations: Sequence[FactorObservation],
    definition: FactorDefinition,
    *,
    split_name: SplitName,
    minimum_dates: int,
) -> ICEvaluation:
    factor_values: list[float] = []
    market_returns: list[float] = []
    for dated in _group_by_date(observations).values():
        values = [
            value
            for item in dated
            if (value := item.factor_values.get(definition.name)) is not None and isfinite(value)
        ]
        returns = [item.forward_return for item in dated if isfinite(item.forward_return)]
        if not values or not returns:
            continue
        if max(values) - min(values) > 1e-12:
            raise ValueError(f"time-series factor {definition.name} is inconsistent within a date")
        factor_values.append(values[0])
        market_returns.append(fmean(returns))
    count = len(factor_values)
    if count < minimum_dates or _constant(factor_values) or _constant(market_returns):
        return _empty_evaluation(
            definition,
            split_name,
            date_count=count,
            observation_count=count,
            warning=(f"requires at least {minimum_dates} non-constant market dates; found {count}"),
        )
    raw_ic = float(spearmanr(factor_values, market_returns).statistic)
    pearson_ic = float(pearsonr(factor_values, market_returns).statistic)
    p_value = float(spearmanr(factor_values, market_returns).pvalue)
    directional_ic = raw_ic * _direction_sign(definition)
    return ICEvaluation(
        factor_name=definition.name,
        split_name=split_name,
        evaluation_axis=definition.scope,
        date_count=count,
        observation_count=count,
        raw_mean_ic=raw_ic,
        directional_mean_ic=directional_ic,
        median_ic=raw_ic,
        ic_standard_deviation=None,
        information_ratio=None,
        positive_ratio=1.0 if directional_ic > 0 else 0.0,
        pearson_ic=pearson_ic,
        p_value=p_value,
        adjusted_p_value=None,
        significant=False,
        confidence_score=_confidence_score(
            count,
            p_value,
            1.0 if directional_ic > 0 else 0.0,
        ),
    )


def _summarize_ic_series(
    definition: FactorDefinition,
    *,
    split_name: SplitName,
    rank_ics: Sequence[float],
    pearson_ics: Sequence[float],
    observation_count: int,
    minimum_dates: int,
) -> ICEvaluation:
    date_count = len(rank_ics)
    if date_count < minimum_dates:
        return _empty_evaluation(
            definition,
            split_name,
            date_count=date_count,
            observation_count=observation_count,
            warning=f"requires at least {minimum_dates} valid IC dates; found {date_count}",
        )
    raw_mean = fmean(rank_ics)
    directional = [item * _direction_sign(definition) for item in rank_ics]
    standard_deviation = stdev(rank_ics) if date_count >= 2 else None
    if standard_deviation is not None and standard_deviation > 0:
        p_value = float(ttest_1samp(rank_ics, popmean=0.0).pvalue)
    elif abs(raw_mean) > 0:
        p_value = 0.0
    else:
        p_value = 1.0
    return ICEvaluation(
        factor_name=definition.name,
        split_name=split_name,
        evaluation_axis=definition.scope,
        date_count=date_count,
        observation_count=observation_count,
        raw_mean_ic=raw_mean,
        directional_mean_ic=fmean(directional),
        median_ic=median(rank_ics),
        ic_standard_deviation=standard_deviation,
        information_ratio=(
            raw_mean / standard_deviation
            if standard_deviation is not None and standard_deviation > 0
            else None
        ),
        positive_ratio=sum(item > 0 for item in directional) / date_count,
        pearson_ic=fmean(pearson_ics) if pearson_ics else None,
        p_value=p_value,
        adjusted_p_value=None,
        significant=False,
        confidence_score=_confidence_score(
            date_count,
            p_value,
            sum(item > 0 for item in directional) / date_count,
        ),
    )


def _empty_evaluation(
    definition: FactorDefinition,
    split_name: SplitName,
    *,
    date_count: int,
    observation_count: int,
    warning: str,
) -> ICEvaluation:
    return ICEvaluation(
        factor_name=definition.name,
        split_name=split_name,
        evaluation_axis=definition.scope,
        date_count=date_count,
        observation_count=observation_count,
        raw_mean_ic=None,
        directional_mean_ic=None,
        median_ic=None,
        ic_standard_deviation=None,
        information_ratio=None,
        positive_ratio=None,
        pearson_ic=None,
        p_value=None,
        adjusted_p_value=None,
        significant=False,
        confidence_score=0,
        warning=warning,
    )


def _confidence_score(
    date_count: int,
    adjusted_or_raw_p: float | None,
    positive_ratio: float | None,
) -> int:
    sample_component = min(30.0, date_count / 36 * 30)
    significance_component = (
        max(0.0, min(30.0, (1 - adjusted_or_raw_p) * 30)) if adjusted_or_raw_p is not None else 0.0
    )
    stability_component = (
        max(0.0, min(20.0, positive_ratio * 20)) if positive_ratio is not None else 0.0
    )
    return round(min(80.0, sample_component + significance_component + stability_component))


def _definition(panel: FactorPanel, factor_name: str) -> FactorDefinition:
    try:
        return next(item for item in panel.definitions if item.name == factor_name)
    except StopIteration as error:
        raise ValueError(f"factor {factor_name!r} is not in this panel") from error


def _group_by_date(
    observations: Sequence[FactorObservation],
) -> dict[date, list[FactorObservation]]:
    grouped: defaultdict[date, list[FactorObservation]] = defaultdict(list)
    for item in observations:
        grouped[item.as_of_date].append(item)
    return dict(sorted(grouped.items()))


def _constant(values: Sequence[float]) -> bool:
    return not values or max(values) - min(values) <= 1e-15


def _direction_sign(definition: FactorDefinition) -> float:
    return 1.0 if definition.direction == "high" else -1.0
