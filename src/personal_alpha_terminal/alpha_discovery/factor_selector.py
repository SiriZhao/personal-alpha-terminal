from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from itertools import combinations
from math import ceil, isfinite
from statistics import fmean

from scipy.stats import rankdata, spearmanr

from personal_alpha_terminal.alpha_discovery.factor_evaluator import (
    adjust_evaluation_p_values,
    evaluate_factor,
    evaluate_factor_library,
    validate_non_overlapping_panel,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryConfig,
    ChronologicalSplit,
    FactorCombinationEvaluation,
    FactorDefinition,
    FactorObservation,
    FactorPanel,
    FactorSelectionResult,
    ICEvaluation,
)


@dataclass(frozen=True, slots=True)
class _CombinationCandidate:
    factors: tuple[str, ...]
    panel: FactorPanel
    train: ICEvaluation
    validation: ICEvaluation
    train_long_short_return: float | None
    validation_long_short_return: float | None
    maximum_pairwise_correlation: float


def discover_factor_combinations(
    panel: FactorPanel,
    config: AlphaDiscoveryConfig,
) -> FactorSelectionResult:
    """Select on validation data and reveal the test set only after freezing."""

    validate_non_overlapping_panel(panel)
    split = chronological_split(panel, config)
    individual = evaluate_factor_library(
        panel,
        split_name="train",
        dates=split.train_dates,
        minimum_cross_section=config.minimum_cross_section,
        minimum_dates=config.minimum_dates_per_split,
        fdr_alpha=config.fdr_alpha,
    )
    definition_by_name = {item.name: item for item in panel.definitions}
    eligible = [
        item
        for item in individual
        if item.evaluation_axis == "cross_sectional"
        and item.significant
        and item.directional_mean_ic is not None
        and item.directional_mean_ic >= config.minimum_abs_directional_ic
    ]
    eligible.sort(
        key=lambda item: (
            -(item.directional_mean_ic or 0.0),
            item.adjusted_p_value if item.adjusted_p_value is not None else 1.0,
            item.factor_name,
        )
    )
    factor_names = tuple(item.factor_name for item in eligible[: config.maximum_candidate_factors])
    candidates: list[_CombinationCandidate] = []
    for size in range(1, min(config.maximum_combination_size, len(factor_names)) + 1):
        for factor_names_tuple in combinations(factor_names, size):
            maximum_correlation = _maximum_pairwise_correlation(
                panel,
                factor_names_tuple,
                split.train_dates,
                definition_by_name,
                minimum_cross_section=config.minimum_cross_section,
            )
            if maximum_correlation > config.maximum_factor_correlation:
                continue
            composite = _composite_panel(
                panel,
                factor_names_tuple,
                definition_by_name,
                minimum_cross_section=config.minimum_cross_section,
            )
            train_evaluation = evaluate_factor(
                composite,
                composite.definitions[0].name,
                split_name="train",
                dates=split.train_dates,
                minimum_cross_section=config.minimum_cross_section,
                minimum_dates=config.minimum_dates_per_split,
            )
            validation_evaluation = evaluate_factor(
                composite,
                composite.definitions[0].name,
                split_name="validation",
                dates=split.validation_dates,
                minimum_cross_section=config.minimum_cross_section,
                minimum_dates=config.minimum_dates_per_split,
            )
            candidates.append(
                _CombinationCandidate(
                    factors=factor_names_tuple,
                    panel=composite,
                    train=train_evaluation,
                    validation=validation_evaluation,
                    train_long_short_return=_long_short_return(
                        composite,
                        split.train_dates,
                        config.selection_quantile,
                        config.minimum_cross_section,
                    ),
                    validation_long_short_return=_long_short_return(
                        composite,
                        split.validation_dates,
                        config.selection_quantile,
                        config.minimum_cross_section,
                    ),
                    maximum_pairwise_correlation=maximum_correlation,
                )
            )
    candidates = _adjust_candidate_p_values(candidates, alpha=config.fdr_alpha)
    selectable = [
        item
        for item in candidates
        if item.train.significant
        and item.validation.significant
        and item.train.directional_mean_ic is not None
        and item.validation.directional_mean_ic is not None
        and item.train.directional_mean_ic >= config.minimum_abs_directional_ic
        and item.validation.directional_mean_ic >= config.minimum_abs_directional_ic
    ]
    selectable.sort(
        key=lambda item: (
            -((item.validation.directional_mean_ic or 0.0) - 0.005 * (len(item.factors) - 1)),
            len(item.factors),
            item.factors,
        )
    )
    frozen = selectable[: config.maximum_selected_combinations]
    test_evaluations = [
        evaluate_factor(
            item.panel,
            item.panel.definitions[0].name,
            split_name="test",
            dates=split.test_dates,
            minimum_cross_section=config.minimum_cross_section,
            minimum_dates=config.minimum_dates_per_split,
        )
        for item in frozen
    ]
    adjusted_test = adjust_evaluation_p_values(
        test_evaluations,
        alpha=config.fdr_alpha,
    )
    final = tuple(
        _finalize_combination(
            rank=index + 1,
            candidate=candidate,
            test=test,
            split=split,
            config=config,
        )
        for index, (candidate, test) in enumerate(zip(frozen, adjusted_test, strict=True))
    )
    validation_individual = evaluate_factor_library(
        panel,
        split_name="validation",
        dates=split.validation_dates,
        minimum_cross_section=config.minimum_cross_section,
        minimum_dates=config.minimum_dates_per_split,
        fdr_alpha=config.fdr_alpha,
    )
    test_individual = evaluate_factor_library(
        panel,
        split_name="test",
        dates=split.test_dates,
        minimum_cross_section=config.minimum_cross_section,
        minimum_dates=config.minimum_dates_per_split,
        fdr_alpha=config.fdr_alpha,
    )
    return FactorSelectionResult(
        split=split,
        factor_evaluations=(
            *individual,
            *validation_individual,
            *test_individual,
        ),
        combinations=final,
        tested_factor_count=len(panel.definitions),
        tested_combination_count=len(candidates),
    )


def chronological_split(
    panel: FactorPanel,
    config: AlphaDiscoveryConfig,
) -> ChronologicalSplit:
    dates = panel.dates
    minimum_total = config.minimum_dates_per_split * 3 + 2
    if len(dates) < minimum_total:
        raise ValueError(
            "insufficient non-overlapping dates for train/validation/test: "
            f"need at least {minimum_total}, found {len(dates)}"
        )
    train_end = max(
        config.minimum_dates_per_split,
        int(len(dates) * config.train_fraction),
    )
    validation_end = max(
        train_end + config.minimum_dates_per_split,
        int(len(dates) * (config.train_fraction + config.validation_fraction)),
    )
    if len(dates) - validation_end < config.minimum_dates_per_split:
        validation_end = len(dates) - config.minimum_dates_per_split
    raw_train = dates[:train_end]
    raw_validation = dates[train_end:validation_end]
    test = dates[validation_end:]
    train, purged_train = _purge_before_boundary(
        panel,
        raw_train,
        raw_validation[0],
    )
    validation, purged_validation = _purge_before_boundary(
        panel,
        raw_validation,
        test[0],
    )
    for name, split_dates in (
        ("train", train),
        ("validation", validation),
        ("test", test),
    ):
        if len(split_dates) < config.minimum_dates_per_split:
            raise ValueError(
                f"{name} has {len(split_dates)} dates after purging; "
                f"requires {config.minimum_dates_per_split}"
            )
    return ChronologicalSplit(
        train_dates=train,
        validation_dates=validation,
        test_dates=test,
        purged_dates=tuple(sorted((*purged_train, *purged_validation))),
    )


def build_composite_panel(
    panel: FactorPanel,
    factor_names: tuple[str, ...],
    *,
    minimum_cross_section: int,
) -> FactorPanel:
    """Build a fixed equal-weight composite without fitting outcome data."""

    if not factor_names:
        raise ValueError("factor_names cannot be empty")
    if len(set(factor_names)) != len(factor_names):
        raise ValueError("factor_names must be unique")
    definitions = {item.name: item for item in panel.definitions}
    unknown = sorted(set(factor_names) - set(definitions))
    if unknown:
        raise ValueError("unknown factors: " + ", ".join(unknown))
    if any(definitions[name].scope != "cross_sectional" for name in factor_names):
        raise ValueError("walk-forward composites require cross-sectional factors")
    return _composite_panel(
        panel,
        factor_names,
        definitions,
        minimum_cross_section=minimum_cross_section,
    )


def _purge_before_boundary(
    panel: FactorPanel,
    dates: Sequence[date],
    next_start: date,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    end_by_date: dict[date, date] = {}
    for item in panel.observations:
        if item.as_of_date in dates:
            end_by_date[item.as_of_date] = max(
                end_by_date.get(item.as_of_date, item.forward_end_date),
                item.forward_end_date,
            )
    kept = tuple(item for item in dates if end_by_date[item] < next_start)
    purged = tuple(item for item in dates if item not in kept)
    return kept, purged


def _composite_panel(
    panel: FactorPanel,
    factor_names: tuple[str, ...],
    definitions: dict[str, FactorDefinition],
    *,
    minimum_cross_section: int,
) -> FactorPanel:
    name = "combo:" + "+".join(factor_names)
    definition = FactorDefinition(
        name=name,
        category="multi_factor",
        direction="high",
        scope="cross_sectional",
        description="Equal-weight mean of direction-adjusted within-date percentile ranks.",
        formula="mean(direction-adjusted cross-sectional percentile ranks)",
    )
    observations: list[FactorObservation] = []
    for dated in _group_by_date(panel.observations).values():
        complete = [
            item
            for item in dated
            if all(item.factor_values.get(factor) is not None for factor in factor_names)
        ]
        if len(complete) < minimum_cross_section:
            continue
        ranks_by_factor: dict[str, dict[int, float]] = {}
        for factor in factor_names:
            values: list[float] = []
            for observation in complete:
                value = observation.factor_values[factor]
                if value is None:
                    raise AssertionError("complete observation contains a null factor")
                values.append(float(value))
            signed = (
                values if definitions[factor].direction == "high" else [-value for value in values]
            )
            ranks = rankdata(signed, method="average")
            denominator = max(1, len(complete) - 1)
            ranks_by_factor[factor] = {
                item.instrument.id: (float(rank) - 1) / denominator
                for item, rank in zip(complete, ranks, strict=True)
            }
        for item in complete:
            composite = fmean(
                ranks_by_factor[factor][item.instrument.id] for factor in factor_names
            )
            observations.append(replace(item, factor_values={name: composite}))
    return FactorPanel(
        market=panel.market,
        horizon_days=panel.horizon_days,
        definitions=(definition,),
        observations=tuple(observations),
        data_fingerprint=f"{panel.data_fingerprint}:{name}",
    )


def _maximum_pairwise_correlation(
    panel: FactorPanel,
    factors: tuple[str, ...],
    dates: Iterable[date],
    definitions: dict[str, FactorDefinition],
    *,
    minimum_cross_section: int,
) -> float:
    if len(factors) < 2:
        return 0.0
    allowed = set(dates)
    maximum = 0.0
    for left, right in combinations(factors, 2):
        correlations: list[float] = []
        for dated_date, dated in _group_by_date(panel.observations).items():
            if dated_date not in allowed:
                continue
            pairs = [
                (
                    float(left_value),
                    float(right_value),
                )
                for item in dated
                if (left_value := item.factor_values.get(left)) is not None
                and (right_value := item.factor_values.get(right)) is not None
            ]
            if len(pairs) < minimum_cross_section:
                continue
            left_values = [item[0] for item in pairs]
            right_values = [item[1] for item in pairs]
            if definitions[left].direction == "low":
                left_values = [-item for item in left_values]
            if definitions[right].direction == "low":
                right_values = [-item for item in right_values]
            value = float(spearmanr(left_values, right_values).statistic)
            if isfinite(value):
                correlations.append(abs(value))
        if not correlations:
            return 1.0
        maximum = max(maximum, fmean(correlations))
    return maximum


def _long_short_return(
    panel: FactorPanel,
    dates: Iterable[date],
    quantile: float,
    minimum_cross_section: int,
) -> float | None:
    allowed = set(dates)
    factor_name = panel.definitions[0].name
    spreads: list[float] = []
    for dated_date, dated in _group_by_date(panel.observations).items():
        if dated_date not in allowed:
            continue
        valid = sorted(
            (
                (float(value), item.forward_return)
                for item in dated
                if (value := item.factor_values.get(factor_name)) is not None
            ),
            key=lambda item: item[0],
        )
        if len(valid) < minimum_cross_section:
            continue
        selected_count = max(1, ceil(len(valid) * quantile))
        bottom = valid[:selected_count]
        top = valid[-selected_count:]
        spreads.append(fmean(item[1] for item in top) - fmean(item[1] for item in bottom))
    return fmean(spreads) if spreads else None


def _adjust_candidate_p_values(
    candidates: Sequence[_CombinationCandidate],
    *,
    alpha: float,
) -> list[_CombinationCandidate]:
    adjusted_train = adjust_evaluation_p_values(
        [item.train for item in candidates],
        alpha=alpha,
    )
    adjusted_validation = adjust_evaluation_p_values(
        [item.validation for item in candidates],
        alpha=alpha,
    )
    return [
        replace(item, train=train, validation=validation)
        for item, train, validation in zip(
            candidates,
            adjusted_train,
            adjusted_validation,
            strict=True,
        )
    ]


def _finalize_combination(
    *,
    rank: int,
    candidate: _CombinationCandidate,
    test: ICEvaluation,
    split: ChronologicalSplit,
    config: AlphaDiscoveryConfig,
) -> FactorCombinationEvaluation:
    confirmed = (
        test.significant
        and test.directional_mean_ic is not None
        and test.directional_mean_ic >= config.minimum_abs_directional_ic
    )
    reasons = (
        "Factors passed training-set FDR and directional IC thresholds.",
        "Combination passed validation-set FDR before the test set was evaluated.",
        (
            "Locked test set confirmed the direction after FDR correction."
            if confirmed
            else "Locked test set did not confirm the pre-registered direction."
        ),
        "Weights are equal and interpretable; no optimizer fitted test data.",
    )
    confidence = round(
        min(
            80.0,
            0.25 * candidate.train.confidence_score
            + 0.35 * candidate.validation.confidence_score
            + 0.40 * test.confidence_score,
        )
    )
    return FactorCombinationEvaluation(
        rank=rank,
        factors=candidate.factors,
        weights=tuple(1 / len(candidate.factors) for _ in candidate.factors),
        train=candidate.train,
        validation=candidate.validation,
        test=test,
        train_long_short_return=candidate.train_long_short_return,
        validation_long_short_return=candidate.validation_long_short_return,
        test_long_short_return=_long_short_return(
            candidate.panel,
            split.test_dates,
            config.selection_quantile,
            config.minimum_cross_section,
        ),
        maximum_pairwise_correlation=candidate.maximum_pairwise_correlation,
        confidence_score=confidence,
        status="test_confirmed" if confirmed else "test_not_confirmed",
        selection_reasons=reasons,
    )


def _group_by_date(
    observations: Sequence[FactorObservation],
) -> dict[date, list[FactorObservation]]:
    grouped: defaultdict[date, list[FactorObservation]] = defaultdict(list)
    for item in observations:
        grouped[item.as_of_date].append(item)
    return dict(sorted(grouped.items()))
