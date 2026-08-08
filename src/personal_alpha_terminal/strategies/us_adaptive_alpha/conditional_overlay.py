from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from math import exp, isfinite
from statistics import fmean, median

import numpy as np
from scipy.stats import beta as beta_distribution
from scipy.stats import fisher_exact

from personal_alpha_terminal.analysis.event_study.statistics import (
    moving_block_bootstrap_mean_interval,
)
from personal_alpha_terminal.analysis.statistical_validation import benjamini_hochberg
from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    ConditionalEvidence,
    ConditionalOverlayConfig,
    EvidenceGrade,
    ProbabilityCalibrationObservation,
    ProbabilityCalibrationReport,
    ProbabilityDriftReport,
    ReturnObservation,
)


def remove_overlapping_observations(
    observations: tuple[ReturnObservation, ...],
    *,
    as_of_date: date,
    decision_time: datetime,
) -> tuple[ReturnObservation, ...]:
    """Apply right-censoring, timestamp availability, duplicate and overlap removal."""

    eligible = sorted(
        (
            item
            for item in observations
            if item.horizon_end_date <= as_of_date and item.available_time <= decision_time
        ),
        key=lambda item: (item.event_date, item.horizon_end_date, item.observation_id),
    )
    retained: list[ReturnObservation] = []
    seen_dates: set[date] = set()
    last_end: date | None = None
    for item in eligible:
        if item.event_date in seen_dates:
            continue
        if last_end is not None and item.event_date <= last_end:
            continue
        retained.append(item)
        seen_dates.add(item.event_date)
        last_end = item.horizon_end_date
    return tuple(retained)


def effective_sample_size(values: tuple[float, ...]) -> float:
    """Conservative lag-1 autocorrelation adjustment, bounded to [2, n]."""

    size = len(values)
    if size < 3:
        return float(size)
    left = np.asarray(values[:-1], dtype=float)
    right = np.asarray(values[1:], dtype=float)
    if np.std(left) <= 1e-15 or np.std(right) <= 1e-15:
        return float(size)
    rho = float(np.corrcoef(left, right)[0, 1])
    if not isfinite(rho):
        return float(size)
    estimate = size * (1 - rho) / max(1e-12, 1 + rho)
    return min(float(size), max(2.0, estimate))


def estimate_conditional_evidence(
    *,
    hypothesis_id: str,
    horizon_days: int,
    regime: str,
    conditional_observations: tuple[ReturnObservation, ...],
    baseline_observations: tuple[ReturnObservation, ...],
    as_of_date: date,
    decision_time: datetime,
    calibration_passed: bool,
    drift_passed: bool,
    config: ConditionalOverlayConfig,
) -> ConditionalEvidence:
    """Estimate condition versus disjoint unconditional baseline evidence.

    This is an overlay estimator, not a position trigger. It intentionally suppresses
    inference until sample, OOS, calibration, drift, freshness and interval gates pass.
    """

    if not hypothesis_id.strip() or horizon_days < 1:
        raise ValueError("hypothesis_id and positive horizon_days are required")
    conditional = remove_overlapping_observations(
        conditional_observations,
        as_of_date=as_of_date,
        decision_time=decision_time,
    )
    condition_ids = {item.observation_id for item in conditional}
    baseline = remove_overlapping_observations(
        tuple(item for item in baseline_observations if item.observation_id not in condition_ids),
        as_of_date=as_of_date,
        decision_time=decision_time,
    )
    returns = tuple(item.forward_return for item in conditional)
    baseline_returns = tuple(item.forward_return for item in baseline)
    ess = effective_sample_size(returns)
    latest = max((item.available_time for item in conditional), default=None)
    data_age = (decision_time.date() - latest.date()).days if latest is not None else None
    decay = (
        exp(-max(data_age, 0) / config.evidence_half_life_days)
        if data_age is not None
        else 0.0
    )
    reasons = _eligibility_reasons(
        conditional,
        baseline,
        ess=ess,
        data_age=data_age,
        calibration_passed=calibration_passed,
        drift_passed=drift_passed,
        config=config,
    )
    if reasons:
        return _suppressed(
            hypothesis_id=hypothesis_id,
            horizon_days=horizon_days,
            regime=regime,
            conditional=conditional,
            baseline=baseline,
            ess=ess,
            data_age=data_age,
            decay=decay,
            calibration_passed=calibration_passed,
            drift_passed=drift_passed,
            reasons=reasons,
        )

    conditional_successes = sum(value > 0 for value in returns)
    baseline_successes = sum(value > 0 for value in baseline_returns)
    conditional_probability, conditional_interval = _posterior(
        conditional_successes,
        len(returns),
        config,
    )
    baseline_probability, baseline_interval = _posterior(
        baseline_successes,
        len(baseline_returns),
        config,
    )
    lift = conditional_probability - baseline_probability
    epsilon = 1e-12
    conditional_odds = conditional_probability / max(1 - conditional_probability, epsilon)
    baseline_odds = baseline_probability / max(1 - baseline_probability, epsilon)
    odds_ratio = conditional_odds / max(baseline_odds, epsilon)
    lift_lower = conditional_interval[0] - baseline_interval[1]
    lift_upper = conditional_interval[1] - baseline_interval[0]
    mean_interval = moving_block_bootstrap_mean_interval(
        returns,
        confidence_level=config.confidence_level,
        resamples=config.bootstrap_resamples,
        random_seed=config.random_seed,
    )
    contingency = (
        (conditional_successes, len(returns) - conditional_successes),
        (baseline_successes, len(baseline_returns) - baseline_successes),
    )
    raw_p = float(fisher_exact(contingency, alternative="two-sided").pvalue)
    conditional_expected = fmean(returns)
    baseline_expected = fmean(baseline_returns)
    cost = config.transaction_cost_bps / 10_000
    net_expected = conditional_expected - cost
    expected_return_lift = conditional_expected - baseline_expected - cost
    interval_width = conditional_interval[1] - conditional_interval[0]
    preliminary_reasons: list[str] = []
    if interval_width > config.maximum_interval_width:
        preliminary_reasons.append("posterior interval is too wide")
    grade = _grade(
        q_value=raw_p,
        lift=lift,
        lift_lower=lift_lower,
        lift_upper=lift_upper,
        net_expected_return=expected_return_lift,
        effective_n=ess,
        interval_width=interval_width,
        decay=decay,
        config=config,
        reasons=preliminary_reasons,
    )
    return ConditionalEvidence(
        hypothesis_id=hypothesis_id,
        horizon_days=horizon_days,
        regime=regime,
        conditional_sample_size=len(conditional),
        baseline_sample_size=len(baseline),
        effective_sample_size=ess,
        conditional_probability=conditional_probability,
        baseline_probability=baseline_probability,
        probability_lift=lift,
        odds_ratio=odds_ratio,
        lift_lower=lift_lower,
        lift_upper=lift_upper,
        conditional_lower=conditional_interval[0],
        conditional_upper=conditional_interval[1],
        average_return=fmean(returns),
        median_return=median(returns),
        tail_loss_5pct=float(np.quantile(np.asarray(returns), 0.05)),
        maximum_adverse_return=min(returns),
        net_expected_return=net_expected,
        baseline_expected_return=baseline_expected,
        conditional_expected_return=conditional_expected,
        expected_return_lift=expected_return_lift,
        mean_return_lower=mean_interval[0] - config.transaction_cost_bps / 10_000,
        mean_return_upper=mean_interval[1] - config.transaction_cost_bps / 10_000,
        raw_p_value=raw_p,
        fdr_q_value=raw_p,
        calibration_passed=calibration_passed,
        drift_passed=drift_passed,
        data_age_days=data_age,
        evidence_decay=decay,
        grade=grade,
        reasons=tuple(preliminary_reasons),
        retained_observation_ids=tuple(item.observation_id for item in conditional),
    )


def adjust_evidence_family(
    evidence: tuple[ConditionalEvidence, ...],
    *,
    config: ConditionalOverlayConfig,
) -> tuple[ConditionalEvidence, ...]:
    """Apply FDR across a pre-registered family and re-grade each hypothesis."""

    testable = [item for item in evidence if item.raw_p_value is not None]
    if not testable:
        return evidence
    raw_p_values: list[float] = []
    for item in testable:
        assert item.raw_p_value is not None
        raw_p_values.append(item.raw_p_value)
    q_values = benjamini_hochberg(raw_p_values)
    by_id: dict[str, ConditionalEvidence] = {}
    for item, q_value in zip(testable, q_values, strict=True):
        reasons = list(item.reasons)
        if q_value > config.fdr_alpha:
            reasons.append("FDR-adjusted evidence is not significant")
        interval_width = (
            item.conditional_upper - item.conditional_lower
            if item.conditional_upper is not None and item.conditional_lower is not None
            else 1.0
        )
        by_id[item.hypothesis_id] = replace(
            item,
            fdr_q_value=q_value,
            grade=_grade(
                q_value=q_value,
                lift=item.probability_lift,
                lift_lower=item.lift_lower,
                lift_upper=item.lift_upper,
                net_expected_return=item.expected_return_lift,
                effective_n=item.effective_sample_size,
                interval_width=interval_width,
                decay=item.evidence_decay,
                config=config,
                reasons=reasons,
            ),
            reasons=tuple(dict.fromkeys(reasons)),
        )
    return tuple(by_id.get(item.hypothesis_id, item) for item in evidence)


def evaluate_probability_calibration(
    observations: tuple[ProbabilityCalibrationObservation, ...],
    *,
    minimum_observations: int = 100,
    maximum_brier_score: float = 0.25,
    minimum_brier_improvement: float = 0.005,
    bins: int = 5,
) -> ProbabilityCalibrationReport:
    if minimum_observations < 30 or bins < 2:
        raise ValueError("calibration thresholds are too small")
    valid = tuple(
        item for item in observations if 0 <= item.predicted_probability <= 1
    )
    reasons: list[str] = []
    if len(valid) < minimum_observations:
        reasons.append(
            f"calibration sample {len(valid)} < minimum {minimum_observations}"
        )
    if not valid:
        return ProbabilityCalibrationReport(
            status="uncalibrated",
            observation_count=0,
            brier_score=None,
            baseline_brier_score=None,
            calibration_error=None,
            bins=(),
            reasons=tuple(reasons or ["no calibration observations"]),
        )
    outcomes = np.asarray([float(item.outcome) for item in valid])
    predictions = np.asarray([item.predicted_probability for item in valid])
    brier = float(np.mean((predictions - outcomes) ** 2))
    climatology = float(np.mean(outcomes))
    baseline_brier = float(np.mean((climatology - outcomes) ** 2))
    rows: list[tuple[float, float, int]] = []
    weighted_error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        mask = (predictions >= lower) & (
            predictions <= upper if index == bins - 1 else predictions < upper
        )
        if not np.any(mask):
            continue
        predicted = float(np.mean(predictions[mask]))
        observed = float(np.mean(outcomes[mask]))
        count = int(np.sum(mask))
        rows.append((predicted, observed, count))
        weighted_error += abs(predicted - observed) * count / len(valid)
    if brier > maximum_brier_score:
        reasons.append("Brier score exceeds the configured ceiling")
    if brier > baseline_brier - minimum_brier_improvement:
        reasons.append("calibration does not beat unconditional climatology")
    return ProbabilityCalibrationReport(
        status="calibrated" if not reasons else "uncalibrated",
        observation_count=len(valid),
        brier_score=brier,
        baseline_brier_score=baseline_brier,
        calibration_error=weighted_error,
        bins=tuple(rows),
        reasons=tuple(reasons),
    )


def detect_probability_drift(
    reference: tuple[ProbabilityCalibrationObservation, ...],
    recent: tuple[ProbabilityCalibrationObservation, ...],
    *,
    minimum_observations: int = 30,
    maximum_mean_shift: float = 0.10,
    maximum_positive_rate_shift: float = 0.15,
) -> ProbabilityDriftReport:
    if len(reference) < minimum_observations or len(recent) < minimum_observations:
        return ProbabilityDriftReport(
            status="insufficient",
            reference_count=len(reference),
            recent_count=len(recent),
            mean_shift=None,
            positive_rate_shift=None,
            reasons=("drift windows do not meet the minimum sample size",),
        )
    mean_shift = fmean(item.predicted_probability for item in recent) - fmean(
        item.predicted_probability for item in reference
    )
    outcome_shift = fmean(float(item.outcome) for item in recent) - fmean(
        float(item.outcome) for item in reference
    )
    reasons: list[str] = []
    if abs(mean_shift) > maximum_mean_shift:
        reasons.append("mean predicted probability shifted beyond limit")
    if abs(outcome_shift) > maximum_positive_rate_shift:
        reasons.append("realized positive rate shifted beyond limit")
    return ProbabilityDriftReport(
        status="drifting" if reasons else "stable",
        reference_count=len(reference),
        recent_count=len(recent),
        mean_shift=mean_shift,
        positive_rate_shift=outcome_shift,
        reasons=tuple(reasons),
    )


def _posterior(
    successes: int,
    sample_size: int,
    config: ConditionalOverlayConfig,
) -> tuple[float, tuple[float, float]]:
    alpha = successes + config.prior_alpha
    beta = sample_size - successes + config.prior_beta
    tail = (1 - config.confidence_level) / 2
    return (
        alpha / (alpha + beta),
        (
            float(beta_distribution.ppf(tail, alpha, beta)),
            float(beta_distribution.ppf(1 - tail, alpha, beta)),
        ),
    )


def _eligibility_reasons(
    conditional: tuple[ReturnObservation, ...],
    baseline: tuple[ReturnObservation, ...],
    *,
    ess: float,
    data_age: int | None,
    calibration_passed: bool,
    drift_passed: bool,
    config: ConditionalOverlayConfig,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(conditional) < config.minimum_sample_size:
        reasons.append("conditional sample is below the minimum")
    if len(baseline) < config.minimum_sample_size:
        reasons.append("unconditional baseline sample is below the minimum")
    if ess < config.minimum_effective_sample_size:
        reasons.append("effective sample size is below the minimum")
    if config.require_out_of_sample and (
        not conditional or not all(item.is_out_of_sample for item in conditional)
    ):
        reasons.append("conditional evidence is not fully out-of-sample")
    if not calibration_passed:
        reasons.append("probability calibration gate did not pass")
    if not drift_passed:
        reasons.append("probability drift gate did not pass")
    if data_age is None or data_age > config.maximum_data_age_days:
        reasons.append("conditional evidence is stale or has no freshness timestamp")
    return tuple(reasons)


def _grade(
    *,
    q_value: float | None,
    lift: float | None,
    lift_lower: float | None,
    lift_upper: float | None,
    net_expected_return: float | None,
    effective_n: float,
    interval_width: float,
    decay: float,
    config: ConditionalOverlayConfig,
    reasons: list[str],
) -> EvidenceGrade:
    if reasons or None in (q_value, lift, lift_lower, lift_upper, net_expected_return):
        return EvidenceGrade.LOW if q_value is not None else EvidenceGrade.INSUFFICIENT
    assert q_value is not None
    assert lift is not None and lift_lower is not None and lift_upper is not None
    assert net_expected_return is not None
    if q_value > config.fdr_alpha or interval_width > config.maximum_interval_width:
        return EvidenceGrade.LOW
    directional = lift_lower > 0 or lift_upper < 0
    if not directional:
        return EvidenceGrade.LOW
    if lift > 0 and net_expected_return <= 0:
        return EvidenceGrade.LOW
    if effective_n >= 2 * config.minimum_effective_sample_size and decay >= 0.75:
        return EvidenceGrade.STRONG
    return EvidenceGrade.MODERATE


def _suppressed(
    *,
    hypothesis_id: str,
    horizon_days: int,
    regime: str,
    conditional: tuple[ReturnObservation, ...],
    baseline: tuple[ReturnObservation, ...],
    ess: float,
    data_age: int | None,
    decay: float,
    calibration_passed: bool,
    drift_passed: bool,
    reasons: tuple[str, ...],
) -> ConditionalEvidence:
    return ConditionalEvidence(
        hypothesis_id=hypothesis_id,
        horizon_days=horizon_days,
        regime=regime,
        conditional_sample_size=len(conditional),
        baseline_sample_size=len(baseline),
        effective_sample_size=ess,
        conditional_probability=None,
        baseline_probability=None,
        probability_lift=None,
        odds_ratio=None,
        lift_lower=None,
        lift_upper=None,
        conditional_lower=None,
        conditional_upper=None,
        average_return=None,
        median_return=None,
        tail_loss_5pct=None,
        maximum_adverse_return=None,
        net_expected_return=None,
        baseline_expected_return=None,
        conditional_expected_return=None,
        expected_return_lift=None,
        mean_return_lower=None,
        mean_return_upper=None,
        raw_p_value=None,
        fdr_q_value=None,
        calibration_passed=calibration_passed,
        drift_passed=drift_passed,
        data_age_days=data_age,
        evidence_decay=decay,
        grade=EvidenceGrade.INSUFFICIENT,
        reasons=reasons,
        retained_observation_ids=tuple(item.observation_id for item in conditional),
    )
