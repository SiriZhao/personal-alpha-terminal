from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import beta as beta_distribution


@dataclass(frozen=True, slots=True)
class ConditionalLiftEstimate:
    baseline_probability: float | None
    conditional_probability: float | None
    probability_lift: float | None
    odds_ratio: float | None
    baseline_expected_return: float | None
    conditional_expected_return: float | None
    expected_return_lift: float | None
    credible_interval: tuple[float, float] | None
    sample_size: int
    baseline_sample_size: int
    valid: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProbabilityCalibration:
    brier_score: float | None
    log_loss: float | None
    baseline_brier: float | None
    observation_count: int
    calibrated: bool
    reason: str | None
    expected_calibration_error: float | None = None
    reliability_buckets: tuple[ReliabilityBucket, ...] = ()


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    lower_bound: float
    upper_bound: float
    mean_probability: float
    observed_frequency: float
    count: int


@dataclass(frozen=True, slots=True)
class ConditionalProbability2:
    raw_probability: float | None
    adjusted_probability: float | None
    baseline_probability: float | None
    probability_lift: float | None
    odds_ratio: float | None
    baseline_expected_return: float | None
    conditional_expected_return: float | None
    expected_return_lift: float | None
    credible_interval: tuple[float, float] | None
    sample_size: int
    effective_sample_size: float
    confidence_level: float
    valid: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProbabilityStability:
    subperiod_lifts: tuple[float | None, ...]
    positive_subperiod_ratio: float | None
    stable: bool
    reason: str | None


def estimate_conditional_lift(
    conditional_returns: tuple[float, ...],
    baseline_returns: tuple[float, ...],
    *,
    minimum_sample_size: int = 30,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    confidence_level: float = 0.95,
) -> ConditionalLiftEstimate:
    if minimum_sample_size < 2 or prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("invalid conditional probability parameters")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    if (
        len(conditional_returns) < minimum_sample_size
        or len(baseline_returns) < minimum_sample_size
    ):
        return ConditionalLiftEstimate(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            len(conditional_returns),
            len(baseline_returns),
            False,
            "conditional and baseline samples must both meet the minimum",
        )
    conditional_success = sum(value > 0 for value in conditional_returns)
    baseline_success = sum(value > 0 for value in baseline_returns)
    conditional_alpha = conditional_success + prior_alpha
    conditional_beta = len(conditional_returns) - conditional_success + prior_beta
    baseline_alpha = baseline_success + prior_alpha
    baseline_beta = len(baseline_returns) - baseline_success + prior_beta
    conditional_probability = conditional_alpha / (conditional_alpha + conditional_beta)
    baseline_probability = baseline_alpha / (baseline_alpha + baseline_beta)
    tail = (1 - confidence_level) / 2
    conditional_interval = (
        float(beta_distribution.ppf(tail, conditional_alpha, conditional_beta)),
        float(beta_distribution.ppf(1 - tail, conditional_alpha, conditional_beta)),
    )
    baseline_interval = (
        float(beta_distribution.ppf(tail, baseline_alpha, baseline_beta)),
        float(beta_distribution.ppf(1 - tail, baseline_alpha, baseline_beta)),
    )
    lift_interval = (
        conditional_interval[0] - baseline_interval[1],
        conditional_interval[1] - baseline_interval[0],
    )
    epsilon = 1e-12
    conditional_odds = conditional_probability / max(epsilon, 1 - conditional_probability)
    baseline_odds = baseline_probability / max(epsilon, 1 - baseline_probability)
    conditional_mean = float(np.mean(conditional_returns))
    baseline_mean = float(np.mean(baseline_returns))
    return ConditionalLiftEstimate(
        baseline_probability,
        conditional_probability,
        conditional_probability - baseline_probability,
        conditional_odds / max(epsilon, baseline_odds),
        baseline_mean,
        conditional_mean,
        conditional_mean - baseline_mean,
        lift_interval,
        len(conditional_returns),
        len(baseline_returns),
        True,
        None,
    )


def evaluate_probability_calibration(
    probabilities: tuple[float, ...],
    outcomes: tuple[bool, ...],
    *,
    minimum_observations: int = 30,
    bucket_count: int = 10,
) -> ProbabilityCalibration:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must align")
    if any(not 0 <= value <= 1 for value in probabilities):
        raise ValueError("probabilities must be in [0, 1]")
    if bucket_count < 2:
        raise ValueError("bucket_count must be at least two")
    if len(probabilities) < minimum_observations:
        return ProbabilityCalibration(
            None,
            None,
            None,
            len(probabilities),
            False,
            "insufficient OOS calibration observations",
        )
    values = np.asarray(probabilities, dtype=float)
    actual = np.asarray(outcomes, dtype=float)
    clipped = np.clip(values, 1e-12, 1 - 1e-12)
    brier = float(np.mean((values - actual) ** 2))
    log_loss = float(
        -np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped))
    )
    baseline = float(actual.mean())
    baseline_brier = float(np.mean((baseline - actual) ** 2))
    buckets: list[ReliabilityBucket] = []
    ece = 0.0
    edges = np.linspace(0.0, 1.0, bucket_count + 1)
    for index in range(bucket_count):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        selected = (values >= lower) & (
            values <= upper if index == bucket_count - 1 else values < upper
        )
        count = int(selected.sum())
        if count == 0:
            continue
        mean_probability = float(values[selected].mean())
        observed_frequency = float(actual[selected].mean())
        ece += count / len(values) * abs(mean_probability - observed_frequency)
        buckets.append(
            ReliabilityBucket(
                lower, upper, mean_probability, observed_frequency, count
            )
        )
    passed = brier < baseline_brier
    return ProbabilityCalibration(
        brier,
        log_loss,
        baseline_brier,
        len(probabilities),
        passed,
        None if passed else "probabilities do not improve Brier score over the OOS base rate",
        ece,
        tuple(buckets),
    )


def estimate_conditional_probability_2(
    conditional_returns: tuple[float, ...],
    baseline_returns: tuple[float, ...],
    *,
    success_threshold: float = 0.0,
    minimum_sample_size: int = 30,
    effective_sample_size: float | None = None,
    prior_strength: float = 10.0,
    confidence_level: float = 0.95,
) -> ConditionalProbability2:
    """Empirical-Bayes conditional estimate anchored to the baseline rate."""

    if minimum_sample_size < 2 or prior_strength <= 0:
        raise ValueError("conditional probability parameters are invalid")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    effective = float(
        len(conditional_returns)
        if effective_sample_size is None
        else effective_sample_size
    )
    if effective < 0 or effective > len(conditional_returns) + 1e-12:
        raise ValueError("effective sample size must be within the raw sample")
    if (
        len(baseline_returns) < minimum_sample_size
        or len(conditional_returns) < minimum_sample_size
        or effective < minimum_sample_size
    ):
        return ConditionalProbability2(
            None, None, None, None, None, None, None, None, None,
            len(conditional_returns), effective, confidence_level, False,
            "raw, effective, and baseline samples must meet the minimum",
        )
    conditional_success = sum(value > success_threshold for value in conditional_returns)
    baseline_success = sum(value > success_threshold for value in baseline_returns)
    raw = conditional_success / len(conditional_returns)
    baseline = baseline_success / len(baseline_returns)
    prior_alpha = max(1e-9, baseline * prior_strength)
    prior_beta = max(1e-9, (1 - baseline) * prior_strength)
    # Dependence reduces evidence while retaining the observed success rate.
    scaled_success = raw * effective
    posterior_alpha = prior_alpha + scaled_success
    posterior_beta = prior_beta + effective - scaled_success
    adjusted = posterior_alpha / (posterior_alpha + posterior_beta)
    tail = (1 - confidence_level) / 2
    interval = (
        float(beta_distribution.ppf(tail, posterior_alpha, posterior_beta)),
        float(beta_distribution.ppf(1 - tail, posterior_alpha, posterior_beta)),
    )
    epsilon = 1e-12
    odds = adjusted / max(epsilon, 1 - adjusted)
    baseline_odds = baseline / max(epsilon, 1 - baseline)
    baseline_mean = float(np.mean(baseline_returns))
    conditional_mean = float(np.mean(conditional_returns))
    return ConditionalProbability2(
        raw,
        adjusted,
        baseline,
        adjusted - baseline,
        odds / max(epsilon, baseline_odds),
        baseline_mean,
        conditional_mean,
        conditional_mean - baseline_mean,
        interval,
        len(conditional_returns),
        effective,
        confidence_level,
        True,
        None,
    )


def evaluate_probability_stability(
    conditional_subperiods: tuple[tuple[float, ...], ...],
    baseline_subperiods: tuple[tuple[float, ...], ...],
    *,
    minimum_sample_size: int = 30,
    minimum_positive_ratio: float = 0.6,
) -> ProbabilityStability:
    if len(conditional_subperiods) != len(baseline_subperiods):
        raise ValueError("conditional and baseline subperiods must align")
    lifts: list[float | None] = []
    for conditional, baseline in zip(conditional_subperiods, baseline_subperiods, strict=True):
        estimate = estimate_conditional_lift(
            conditional,
            baseline,
            minimum_sample_size=minimum_sample_size,
        )
        lifts.append(estimate.expected_return_lift if estimate.valid else None)
    valid = [value for value in lifts if value is not None]
    if len(valid) < 2:
        return ProbabilityStability(tuple(lifts), None, False, "fewer than two valid subperiods")
    ratio = sum(value > 0 for value in valid) / len(valid)
    return ProbabilityStability(
        tuple(lifts),
        ratio,
        ratio >= minimum_positive_ratio,
        None
        if ratio >= minimum_positive_ratio
        else "expected-return lift is not stable across subperiods",
    )
