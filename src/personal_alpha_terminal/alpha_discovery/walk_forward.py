from dataclasses import dataclass
from datetime import date
from statistics import fmean

from personal_alpha_terminal.alpha_discovery.factor_evaluator import (
    adjust_evaluation_p_values,
    evaluate_factor,
    validate_non_overlapping_panel,
)
from personal_alpha_terminal.alpha_discovery.factor_selector import (
    _purge_before_boundary,
    build_composite_panel,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryConfig,
    FactorPanel,
    ICEvaluation,
    WalkForwardFold,
    WalkForwardValidationResult,
)


@dataclass(frozen=True, slots=True)
class _PendingFold:
    train_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    purged_dates: tuple[date, ...]
    train: ICEvaluation
    test: ICEvaluation


def walk_forward_validate(
    panel: FactorPanel,
    factor_names: tuple[str, ...],
    config: AlphaDiscoveryConfig,
    *,
    train_window_dates: int,
    test_window_dates: int,
    step_dates: int | None = None,
    minimum_folds: int = 3,
) -> WalkForwardValidationResult:
    """Evaluate one pre-registered, equal-weight hypothesis on rolling OOS folds.

    The factor set and weights are fixed before fold evaluation. Forward labels that
    touch the test boundary are purged from training, and test windows cannot overlap.
    """

    validate_non_overlapping_panel(panel)
    if train_window_dates < config.minimum_dates_per_split:
        raise ValueError("train_window_dates is below the configured minimum")
    if test_window_dates < config.minimum_dates_per_split:
        raise ValueError("test_window_dates is below the configured minimum")
    resolved_step = step_dates if step_dates is not None else test_window_dates
    if resolved_step < test_window_dates:
        raise ValueError("step_dates must prevent overlapping out-of-sample windows")
    if minimum_folds < 2:
        raise ValueError("minimum_folds must be at least 2")

    composite = build_composite_panel(
        panel,
        factor_names,
        minimum_cross_section=config.minimum_cross_section,
    )
    factor_name = composite.definitions[0].name
    dates = composite.dates
    pending: list[_PendingFold] = []
    cursor = train_window_dates
    while cursor + test_window_dates <= len(dates):
        raw_train = dates[cursor - train_window_dates : cursor]
        test_dates = dates[cursor : cursor + test_window_dates]
        train_dates, purged = _purge_before_boundary(composite, raw_train, test_dates[0])
        if len(train_dates) < config.minimum_dates_per_split:
            raise ValueError("training fold is too short after purging forward labels")
        train = evaluate_factor(
            composite,
            factor_name,
            split_name="train",
            dates=train_dates,
            minimum_cross_section=config.minimum_cross_section,
            minimum_dates=config.minimum_dates_per_split,
        )
        test = evaluate_factor(
            composite,
            factor_name,
            split_name="test",
            dates=test_dates,
            minimum_cross_section=config.minimum_cross_section,
            minimum_dates=config.minimum_dates_per_split,
        )
        pending.append(_PendingFold(train_dates, test_dates, purged, train, test))
        cursor += resolved_step

    if len(pending) < minimum_folds:
        raise ValueError(
            f"insufficient walk-forward folds: need {minimum_folds}, found {len(pending)}"
        )
    adjusted_tests = adjust_evaluation_p_values(
        [item.test for item in pending],
        alpha=config.fdr_alpha,
    )
    folds = tuple(
        WalkForwardFold(
            fold_number=index + 1,
            train_dates=item.train_dates,
            test_dates=item.test_dates,
            purged_train_dates=item.purged_dates,
            train=item.train,
            test=test,
            confirmed=(
                test.significant
                and test.directional_mean_ic is not None
                and test.directional_mean_ic >= config.minimum_abs_directional_ic
            ),
        )
        for index, (item, test) in enumerate(zip(pending, adjusted_tests, strict=True))
    )
    out_of_sample_ics = [
        fold.test.directional_mean_ic
        for fold in folds
        if fold.test.directional_mean_ic is not None
    ]
    positive_ratio = (
        sum(value > 0 for value in out_of_sample_ics) / len(out_of_sample_ics)
        if out_of_sample_ics
        else 0.0
    )
    confirmed_ratio = sum(fold.confirmed for fold in folds) / len(folds)
    stable = positive_ratio >= 2 / 3 and confirmed_ratio >= 2 / 3
    confidence = round(min(70.0, 70.0 * min(positive_ratio, confirmed_ratio)))
    return WalkForwardValidationResult(
        factors=factor_names,
        folds=folds,
        mean_out_of_sample_ic=fmean(out_of_sample_ics) if out_of_sample_ics else None,
        positive_fold_ratio=positive_ratio,
        confirmed_fold_ratio=confirmed_ratio,
        confidence_score=confidence,
        status="stable" if stable else "unstable",
        limitations=(
            "Factor names and equal weights must be pre-registered before this run.",
            "FDR is applied across fold-level out-of-sample tests.",
            "Walk-forward stability does not eliminate universe, regime, or cost bias.",
            "Confidence is capped at 70 until certified real-market replication exists.",
        ),
    )
