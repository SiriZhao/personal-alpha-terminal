from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt

import numpy as np

from personal_alpha_terminal.quant_engine.probability import (
    estimate_conditional_probability_2,
    evaluate_probability_calibration,
)


@dataclass(frozen=True, slots=True)
class ConditionalSample:
    observed_at: datetime
    outcome_available_at: datetime
    return_value: float
    cluster_id: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.outcome_available_at.tzinfo is None:
            raise ValueError("conditional sample timestamps must be timezone-aware")
        if self.outcome_available_at < self.observed_at or not isfinite(self.return_value):
            raise ValueError("conditional sample timing or return is invalid")


@dataclass(frozen=True, slots=True)
class ConditionalEvidence:
    conditional_probability: float | None
    unconditional_probability: float | None
    probability_lift: float | None
    expected_return_lift: float | None
    cost_adjusted_expectation: float | None
    raw_sample_size: int
    effective_sample_size: float
    credible_interval: tuple[float, float] | None
    expected_shortfall: float | None
    oos_brier: float | None
    baseline_brier: float | None
    calibration_status: str
    drift_status: str
    freshness: str
    fdr_adjusted_p_value: float | None
    status: str
    reason: str | None


def build_conditional_evidence(
    *,
    conditional_samples: tuple[ConditionalSample, ...],
    baseline_samples: tuple[ConditionalSample, ...],
    information_cutoff: datetime,
    oos_probabilities: tuple[float, ...],
    oos_outcomes: tuple[bool, ...],
    transaction_cost_rate: float,
    raw_p_value: float,
    family_p_values: tuple[float, ...],
    minimum_sample_size: int = 30,
    maximum_age_days: int = 30,
) -> ConditionalEvidence:
    if information_cutoff.tzinfo is None:
        raise ValueError("information cutoff must be timezone-aware")
    if transaction_cost_rate < 0 or not 0 <= raw_p_value <= 1:
        raise ValueError("cost and p-value inputs are invalid")
    conditional = _mature_non_overlapping(conditional_samples, information_cutoff)
    baseline = _mature_non_overlapping(baseline_samples, information_cutoff)
    effective = _effective_sample_size(tuple(item.return_value for item in conditional))
    estimate = estimate_conditional_probability_2(
        tuple(item.return_value for item in conditional),
        tuple(item.return_value for item in baseline),
        minimum_sample_size=minimum_sample_size,
        effective_sample_size=effective,
    )
    calibration = evaluate_probability_calibration(
        oos_probabilities,
        oos_outcomes,
        minimum_observations=minimum_sample_size,
    )
    adjusted = benjamini_hochberg(family_p_values)
    adjusted_p = (
        adjusted[family_p_values.index(raw_p_value)]
        if raw_p_value in family_p_values
        else None
    )
    latest = max((item.observed_at for item in conditional), default=None)
    age_days = (information_cutoff - latest).days if latest is not None else maximum_age_days + 1
    freshness = "FRESH" if age_days <= maximum_age_days else "STALE"
    values = np.asarray([item.return_value for item in conditional], dtype=float)
    expected_shortfall = _expected_shortfall(values) if len(values) else None
    drift = _drift_status(values)
    calibrated = calibration.calibrated and calibration.brier_score is not None
    statistically_valid = adjusted_p is not None and adjusted_p <= 0.05
    valid = (
        estimate.valid
        and calibrated
        and drift == "STABLE"
        and freshness == "FRESH"
        and statistically_valid
    )
    cost_adjusted = (
        estimate.expected_return_lift - transaction_cost_rate
        if estimate.expected_return_lift is not None
        else None
    )
    if valid and (cost_adjusted is None or cost_adjusted <= 0):
        valid = False
    reason = None
    if not valid:
        reasons = []
        if not estimate.valid:
            reasons.append(estimate.reason or "insufficient sample")
        if not calibrated:
            reasons.append(calibration.reason or "OOS calibration unavailable")
        if drift != "STABLE":
            reasons.append("conditional effect drifted")
        if freshness != "FRESH":
            reasons.append("conditional evidence is stale")
        if not statistically_valid:
            reasons.append("predefined family did not survive BH-FDR")
        if cost_adjusted is not None and cost_adjusted <= 0:
            reasons.append("expected-return lift does not survive costs")
        reason = "; ".join(dict.fromkeys(reasons))
    return ConditionalEvidence(
        conditional_probability=estimate.adjusted_probability,
        unconditional_probability=estimate.baseline_probability,
        probability_lift=estimate.probability_lift,
        expected_return_lift=estimate.expected_return_lift,
        cost_adjusted_expectation=cost_adjusted,
        raw_sample_size=len(conditional),
        effective_sample_size=effective,
        credible_interval=estimate.credible_interval,
        expected_shortfall=expected_shortfall,
        oos_brier=calibration.brier_score,
        baseline_brier=calibration.baseline_brier,
        calibration_status="CALIBRATED_OOS" if calibrated else "NOT_CALIBRATED",
        drift_status=drift,
        freshness=freshness,
        fdr_adjusted_p_value=adjusted_p,
        status="VALIDATED_SUPPORTING_EVIDENCE" if valid else "BLOCKED",
        reason=reason,
    )


def _mature_non_overlapping(
    samples: tuple[ConditionalSample, ...], cutoff: datetime
) -> tuple[ConditionalSample, ...]:
    eligible = sorted(
        (sample for sample in samples if sample.outcome_available_at <= cutoff),
        key=lambda item: (item.observed_at, item.cluster_id),
    )
    selected: dict[str, ConditionalSample] = {}
    for sample in eligible:
        selected.setdefault(sample.cluster_id, sample)
    return tuple(selected.values())


def _effective_sample_size(values: tuple[float, ...]) -> float:
    if len(values) < 3:
        return float(len(values))
    array = np.asarray(values, dtype=float)
    first = array[:-1]
    second = array[1:]
    if float(first.std()) <= 1e-12 or float(second.std()) <= 1e-12:
        return float(len(values))
    rho = float(np.corrcoef(first, second)[0, 1])
    rho = max(-0.99, min(0.99, rho))
    return max(1.0, min(float(len(values)), len(values) * (1 - rho) / (1 + rho)))


def _expected_shortfall(values: np.ndarray, quantile: float = 0.05) -> float:
    threshold = float(np.quantile(values, quantile))
    return float(values[values <= threshold].mean())


def _drift_status(values: np.ndarray) -> str:
    if len(values) < 40:
        return "INSUFFICIENT_HISTORY"
    midpoint = len(values) // 2
    first = values[:midpoint]
    second = values[midpoint:]
    standard_error = sqrt(float(first.var(ddof=1) / len(first) + second.var(ddof=1) / len(second)))
    if standard_error <= 1e-12:
        return "STABLE" if abs(float(first.mean() - second.mean())) <= 1e-12 else "DRIFTED"
    drift_score = abs(float(first.mean() - second.mean())) / standard_error
    return "DRIFTED" if drift_score > 2.0 else "STABLE"


def benjamini_hochberg(p_values: tuple[float, ...]) -> tuple[float, ...]:
    if not p_values or any(not 0 <= value <= 1 for value in p_values):
        raise ValueError("BH-FDR requires non-empty p-values in [0, 1]")
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    for rank_from_end, index in enumerate(reversed(order), start=1):
        rank = len(p_values) - rank_from_end + 1
        running = min(running, p_values[index] * len(p_values) / rank)
        adjusted[index] = min(1.0, running)
    return tuple(adjusted)
