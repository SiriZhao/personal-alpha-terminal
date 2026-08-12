from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_alpha_terminal.intelligence.schemas import _aware
from personal_alpha_terminal.quant_engine.probability import (
    ConditionalProbability2,
    ProbabilityCalibration,
    estimate_conditional_probability_2,
    evaluate_probability_calibration,
)


class LLMProbabilityStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VALIDATING = "VALIDATING"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class LLMProbabilityObservation:
    security_id: str
    session_id: str
    feature_id: str
    feature_time: datetime
    condition_time: datetime
    outcome_horizon_sessions: int
    outcome_time: datetime
    outcome_available_at: datetime
    benchmark_relative_return: float
    condition_active: bool

    def __post_init__(self) -> None:
        for name in ("feature_time", "condition_time", "outcome_time", "outcome_available_at"):
            _aware(getattr(self, name), name)
        if self.feature_time > self.condition_time:
            raise ValueError("feature_time cannot follow condition_time")
        if self.condition_time >= self.outcome_time:
            raise ValueError("probability outcome leaks into its condition")
        if self.outcome_time > self.outcome_available_at:
            raise ValueError("outcome availability precedes outcome time")
        if self.outcome_horizon_sessions < 1:
            raise ValueError("outcome horizon must be positive")


@dataclass(frozen=True, slots=True)
class LLMProbabilityResearchEvidence:
    estimate: ConditionalProbability2
    calibration: ProbabilityCalibration
    status: LLMProbabilityStatus
    blockers: tuple[str, ...]
    feature_ids: tuple[str, ...]
    can_affect_production: bool


def research_llm_probability_feature(
    training: tuple[LLMProbabilityObservation, ...],
    locked_oos: tuple[LLMProbabilityObservation, ...],
    *,
    minimum_sample_size: int = 30,
    production_artifact_matches: bool = False,
) -> LLMProbabilityResearchEvidence:
    """Estimate benchmark-relative probability without using OOS for fitting.

    The training sample produces the empirical-Bayes estimate. Locked OOS is used
    only for calibration and promotion evidence; it never selects the condition.
    """

    conditional = tuple(
        item.benchmark_relative_return for item in training if item.condition_active
    )
    baseline = tuple(item.benchmark_relative_return for item in training)
    estimate = estimate_conditional_probability_2(
        conditional,
        baseline,
        minimum_sample_size=minimum_sample_size,
    )
    oos_probabilities = tuple(
        estimate.adjusted_probability
        for item in locked_oos
        if item.condition_active and estimate.adjusted_probability is not None
    )
    oos_outcomes = tuple(
        item.benchmark_relative_return > 0
        for item in locked_oos
        if item.condition_active and estimate.adjusted_probability is not None
    )
    calibration = evaluate_probability_calibration(
        oos_probabilities,
        oos_outcomes,
        minimum_observations=minimum_sample_size,
    )
    blockers: list[str] = []
    if not estimate.valid:
        blockers.append("LLM_PROBABILITY_TRAINING_SAMPLE_INSUFFICIENT")
    if len(locked_oos) < 252:
        blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
    if not calibration.calibrated:
        blockers.append("LLM_PROBABILITY_CALIBRATION_FAILED")
    if not production_artifact_matches:
        blockers.append("LLM_PROBABILITY_APPROVAL_ARTIFACT_MISSING_OR_MISMATCHED")
    approved = not blockers
    return LLMProbabilityResearchEvidence(
        estimate=estimate,
        calibration=calibration,
        status=(
            LLMProbabilityStatus.PRODUCTION_APPROVED
            if approved
            else LLMProbabilityStatus.RESEARCH_ONLY
        ),
        blockers=tuple(blockers),
        feature_ids=tuple(sorted({item.feature_id for item in (*training, *locked_oos)})),
        can_affect_production=approved,
    )
