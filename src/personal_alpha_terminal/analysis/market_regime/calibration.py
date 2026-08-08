from dataclasses import dataclass, replace
from datetime import date
from math import isfinite
from typing import cast

from personal_alpha_terminal.analysis.market_regime.schemas import (
    CalibrationCurvePoint,
    CalibrationStatus,
    MarketRegimePoint,
    RegimeCalibrationReport,
    RegimeName,
    RegimePricePoint,
)

REGIMES: tuple[RegimeName, ...] = ("risk_on", "neutral", "risk_off")


@dataclass(frozen=True, slots=True)
class _LabelledScore:
    point: MarketRegimePoint
    actual: RegimeName
    available_date: date


@dataclass(frozen=True, slots=True)
class _WalkForwardPrediction:
    point_date: date
    calibrated: dict[RegimeName, float]
    raw: dict[RegimeName, float]
    baseline: dict[RegimeName, float]
    actual: RegimeName | None


def walk_forward_calibrate(
    points: tuple[MarketRegimePoint, ...],
    benchmark: tuple[RegimePricePoint, ...],
    *,
    label_horizon_days: int,
    return_threshold: float,
    minimum_training_observations: int,
    minimum_out_of_sample_observations: int,
    minimum_class_observations: int,
    bins: int,
    minimum_bin_observations: int,
    minimum_brier_improvement: float,
    data_eligible: bool,
    data_limitations: tuple[str, ...] = (),
) -> tuple[tuple[MarketRegimePoint, ...], RegimeCalibrationReport]:
    """Calibrate scores using only labels available before each prediction date.

    Labels use the benchmark's forward trading-observation return. A label ending on
    date ``t`` may train predictions only after ``t``; this strict inequality keeps the
    same close out of both the training outcome and the current prediction.
    """

    _validate_parameters(
        label_horizon_days=label_horizon_days,
        return_threshold=return_threshold,
        minimum_training_observations=minimum_training_observations,
        minimum_out_of_sample_observations=minimum_out_of_sample_observations,
        minimum_class_observations=minimum_class_observations,
        bins=bins,
        minimum_bin_observations=minimum_bin_observations,
        minimum_brier_improvement=minimum_brier_improvement,
    )
    ordered_points = tuple(sorted(points, key=lambda item: item.as_of_date))
    if len({item.as_of_date for item in ordered_points}) != len(ordered_points):
        raise ValueError("market regime points must have unique dates")
    ordered_benchmark = tuple(sorted(benchmark, key=lambda item: item.date))
    if len({item.date for item in ordered_benchmark}) != len(ordered_benchmark):
        raise ValueError("benchmark points must have unique dates")

    labelled = _build_labels(
        ordered_points,
        ordered_benchmark,
        horizon=label_horizon_days,
        threshold=return_threshold,
    )
    label_by_date = {item.point.as_of_date: item for item in labelled}
    predictions: list[_WalkForwardPrediction] = []
    prediction_by_date: dict[date, _WalkForwardPrediction] = {}

    for point in ordered_points:
        training = tuple(item for item in labelled if item.available_date < point.as_of_date)
        counts = _class_counts(training)
        if len(training) < minimum_training_observations or any(
            counts[name] < minimum_class_observations for name in REGIMES
        ):
            continue
        raw = point.scores
        calibrated = _calibrate_scores(
            raw,
            training,
            bins=bins,
            minimum_bin_observations=minimum_bin_observations,
        )
        baseline = {
            name: (counts[name] + 1) / (len(training) + len(REGIMES)) for name in REGIMES
        }
        current_label = label_by_date.get(point.as_of_date)
        prediction = _WalkForwardPrediction(
            point_date=point.as_of_date,
            calibrated=calibrated,
            raw=raw,
            baseline=baseline,
            actual=current_label.actual if current_label is not None else None,
        )
        prediction_by_date[point.as_of_date] = prediction
        if prediction.actual is not None:
            predictions.append(prediction)

    brier = _brier_score(predictions, "calibrated")
    raw_brier = _brier_score(predictions, "raw")
    baseline_brier = _brier_score(predictions, "baseline")
    reasons = _validation_reasons(
        predictions,
        brier=brier,
        raw_brier=raw_brier,
        baseline_brier=baseline_brier,
        minimum_out_of_sample_observations=minimum_out_of_sample_observations,
        minimum_class_observations=minimum_class_observations,
        minimum_brier_improvement=minimum_brier_improvement,
        data_eligible=data_eligible,
        data_limitations=data_limitations,
    )
    status: CalibrationStatus = "calibrated" if not reasons else "score_only"
    calibrated_points = tuple(
        _apply_prediction(point, prediction_by_date.get(point.as_of_date))
        if status == "calibrated"
        else point
        for point in ordered_points
    )
    report = RegimeCalibrationReport(
        status=status,
        method="walk_forward_fixed_bin_beta_smoothing",
        label_horizon_days=label_horizon_days,
        risk_on_return_threshold=return_threshold,
        risk_off_return_threshold=-return_threshold,
        training_minimum=minimum_training_observations,
        out_of_sample_count=len(predictions),
        brier_score=brier,
        raw_score_brier=raw_brier,
        baseline_brier=baseline_brier,
        calibration_curve=_calibration_curve(predictions, bins=bins),
        reasons=reasons,
    )
    return calibrated_points, report


def _build_labels(
    points: tuple[MarketRegimePoint, ...],
    benchmark: tuple[RegimePricePoint, ...],
    *,
    horizon: int,
    threshold: float,
) -> tuple[_LabelledScore, ...]:
    index_by_date = {item.date: index for index, item in enumerate(benchmark)}
    labelled: list[_LabelledScore] = []
    for point in points:
        index = index_by_date.get(point.as_of_date)
        if index is None or index + horizon >= len(benchmark):
            continue
        start = benchmark[index].close
        end_point = benchmark[index + horizon]
        if start <= 0 or end_point.close <= 0:
            continue
        forward_return = end_point.close / start - 1
        if forward_return > threshold:
            actual: RegimeName = "risk_on"
        elif forward_return < -threshold:
            actual = "risk_off"
        else:
            actual = "neutral"
        labelled.append(
            _LabelledScore(
                point=point,
                actual=actual,
                available_date=end_point.date,
            )
        )
    return tuple(labelled)


def _calibrate_scores(
    raw: dict[RegimeName, float],
    training: tuple[_LabelledScore, ...],
    *,
    bins: int,
    minimum_bin_observations: int,
) -> dict[RegimeName, float]:
    counts = _class_counts(training)
    components: dict[RegimeName, float] = {}
    for name in REGIMES:
        selected_bin = _bin_index(raw[name], bins)
        members = tuple(
            item for item in training if _bin_index(item.point.scores[name], bins) == selected_bin
        )
        if len(members) >= minimum_bin_observations:
            successes = sum(item.actual == name for item in members)
            components[name] = (successes + 1) / (len(members) + 2)
        else:
            components[name] = (counts[name] + 1) / (len(training) + len(REGIMES))
    denominator = sum(components.values())
    return {name: components[name] / denominator for name in REGIMES}


def _validation_reasons(
    predictions: list[_WalkForwardPrediction],
    *,
    brier: float | None,
    raw_brier: float | None,
    baseline_brier: float | None,
    minimum_out_of_sample_observations: int,
    minimum_class_observations: int,
    minimum_brier_improvement: float,
    data_eligible: bool,
    data_limitations: tuple[str, ...],
) -> tuple[str, ...]:
    reasons = list(data_limitations)
    if not data_eligible and not data_limitations:
        reasons.append("input data is not certified for probability calibration")
    if len(predictions) < minimum_out_of_sample_observations:
        reasons.append(
            "out-of-sample observations below minimum "
            f"({len(predictions)} < {minimum_out_of_sample_observations})"
        )
    actual_counts = {name: sum(item.actual == name for item in predictions) for name in REGIMES}
    for name in REGIMES:
        if actual_counts[name] < minimum_class_observations:
            reasons.append(
                f"out-of-sample class {name} below minimum "
                f"({actual_counts[name]} < {minimum_class_observations})"
            )
    if brier is None or raw_brier is None or baseline_brier is None:
        reasons.append("Brier scores are unavailable")
    else:
        if brier > raw_brier - minimum_brier_improvement:
            reasons.append("calibration does not improve Brier score over raw model scores")
        if brier > baseline_brier - minimum_brier_improvement:
            reasons.append("calibration does not improve Brier score over expanding climatology")
    return tuple(dict.fromkeys(reasons))


def _calibration_curve(
    predictions: list[_WalkForwardPrediction],
    *,
    bins: int,
) -> tuple[CalibrationCurvePoint, ...]:
    curve: list[CalibrationCurvePoint] = []
    for name in REGIMES:
        for bin_index in range(bins):
            members = tuple(
                item
                for item in predictions
                if _bin_index(item.calibrated[name], bins) == bin_index
            )
            if not members:
                continue
            curve.append(
                CalibrationCurvePoint(
                    regime=name,
                    bin_lower=bin_index / bins,
                    bin_upper=(bin_index + 1) / bins,
                    mean_predicted=(
                        sum(item.calibrated[name] for item in members) / len(members)
                    ),
                    observed_frequency=(
                        sum(item.actual == name for item in members) / len(members)
                    ),
                    sample_size=len(members),
                )
            )
    return tuple(curve)


def _brier_score(
    predictions: list[_WalkForwardPrediction],
    field: str,
) -> float | None:
    if not predictions:
        return None
    total = 0.0
    for item in predictions:
        values = cast(dict[RegimeName, float], getattr(item, field))
        total += sum((values[name] - float(item.actual == name)) ** 2 for name in REGIMES)
    return total / len(predictions)


def _apply_prediction(
    point: MarketRegimePoint,
    prediction: _WalkForwardPrediction | None,
) -> MarketRegimePoint:
    if prediction is None:
        return point
    regime = max(REGIMES, key=prediction.calibrated.__getitem__)
    return replace(
        point,
        regime=regime,
        risk_on_probability=prediction.calibrated["risk_on"],
        risk_off_probability=prediction.calibrated["risk_off"],
        neutral_probability=prediction.calibrated["neutral"],
    )


def _class_counts(training: tuple[_LabelledScore, ...]) -> dict[RegimeName, int]:
    return {name: sum(item.actual == name for item in training) for name in REGIMES}


def _bin_index(value: float, bins: int) -> int:
    return min(bins - 1, max(0, int(value * bins)))


def _validate_parameters(**values: int | float) -> None:
    if int(values["label_horizon_days"]) < 1:
        raise ValueError("label horizon must be positive")
    if not 0 < float(values["return_threshold"]) < 1:
        raise ValueError("return threshold must be between zero and one")
    for name in (
        "minimum_training_observations",
        "minimum_out_of_sample_observations",
        "minimum_class_observations",
        "minimum_bin_observations",
    ):
        if int(values[name]) < 1:
            raise ValueError(f"{name} must be positive")
    if int(values["bins"]) < 2:
        raise ValueError("calibration bins must be at least two")
    improvement = float(values["minimum_brier_improvement"])
    if not isfinite(improvement) or improvement < 0:
        raise ValueError("minimum Brier improvement must be finite and nonnegative")
