from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from personal_alpha_terminal.quant_engine.backtest.validation import WalkForwardFold
from personal_alpha_terminal.quant_engine.probability import (
    ConditionalProbability2,
    ProbabilityCalibration,
    estimate_conditional_probability_2,
    evaluate_probability_calibration,
)


class SampleRole(StrEnum):
    DISCOVERY = "DISCOVERY"
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"


@dataclass(frozen=True, slots=True)
class ConditionalObservation:
    session: date
    forward_return: float
    condition_matched: bool
    independent_weight: float = 1.0
    regime: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if not 0 < self.independent_weight <= 1:
            raise ValueError("independent_weight must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class ConditionalDefinition:
    condition_id: str
    features: tuple[str, ...]
    horizon: int
    return_threshold: float = 0.0
    preregistered: bool = True

    def __post_init__(self) -> None:
        if not self.condition_id or not self.features or self.horizon < 1:
            raise ValueError("conditional definition is incomplete")
        if len(self.features) > 6:
            raise ValueError("conditional definitions are capped at six features")


@dataclass(frozen=True, slots=True)
class ConditionalFoldResult:
    fold_id: int
    estimate: ConditionalProbability2
    oos_probabilities: tuple[float, ...]
    oos_outcomes: tuple[bool, ...]
    oos_expected_return_lift: float | None


@dataclass(frozen=True, slots=True)
class ConditionalEvidenceValidation:
    definition: ConditionalDefinition
    folds: tuple[ConditionalFoldResult, ...]
    calibration: ProbabilityCalibration
    valid_fold_ratio: float
    oos_positive_lift_ratio: float | None
    status: str
    reason: str | None
    model_version: str = "conditional-evidence-walk-forward-v2"


class ConditionalEvidenceEngine:
    """Preregistered, chronological conditional evidence evaluation."""

    def __init__(self, *, minimum_sample_size: int = 30, prior_strength: float = 10.0) -> None:
        if minimum_sample_size < 30:
            raise ValueError("production conditional evidence requires at least 30 samples")
        self.minimum_sample_size = minimum_sample_size
        self.prior_strength = prior_strength

    def walk_forward(
        self,
        definition: ConditionalDefinition,
        observations: tuple[ConditionalObservation, ...],
        folds: tuple[WalkForwardFold, ...],
    ) -> ConditionalEvidenceValidation:
        if not definition.preregistered:
            return self._invalid(definition, "condition family was not preregistered")
        if tuple(sorted(item.session for item in observations)) != tuple(
            item.session for item in observations
        ):
            raise ValueError("conditional observations must be chronological")
        results: list[ConditionalFoldResult] = []
        all_probabilities: list[float] = []
        all_outcomes: list[bool] = []
        oos_lifts: list[float] = []
        for fold in folds:
            split = fold.split
            development = tuple(
                item
                for item in observations
                if split.train_start <= item.session <= split.validation_end
            )
            oos = tuple(
                item
                for item in observations
                if split.test_start <= item.session <= split.test_end
            )
            baseline_returns = tuple(item.forward_return for item in development)
            conditional = tuple(item for item in development if item.condition_matched)
            estimate = estimate_conditional_probability_2(
                tuple(item.forward_return for item in conditional),
                baseline_returns,
                success_threshold=definition.return_threshold,
                minimum_sample_size=self.minimum_sample_size,
                effective_sample_size=sum(item.independent_weight for item in conditional),
                prior_strength=self.prior_strength,
            )
            matched_oos = tuple(item for item in oos if item.condition_matched)
            probabilities = (
                tuple(estimate.adjusted_probability for _ in matched_oos)
                if estimate.valid and estimate.adjusted_probability is not None
                else ()
            )
            outcomes = tuple(
                item.forward_return > definition.return_threshold for item in matched_oos
            )
            oos_lift = None
            if matched_oos and development:
                oos_lift = (
                    sum(item.forward_return for item in matched_oos) / len(matched_oos)
                    - sum(item.forward_return for item in development) / len(development)
                )
                oos_lifts.append(oos_lift)
            all_probabilities.extend(value for value in probabilities if value is not None)
            all_outcomes.extend(outcomes if probabilities else ())
            results.append(
                ConditionalFoldResult(
                    fold.fold_id,
                    estimate,
                    tuple(value for value in probabilities if value is not None),
                    outcomes if probabilities else (),
                    oos_lift,
                )
            )
        calibration = evaluate_probability_calibration(
            tuple(all_probabilities),
            tuple(all_outcomes),
            minimum_observations=self.minimum_sample_size,
        )
        valid_ratio = (
            sum(item.estimate.valid for item in results) / len(results) if results else 0.0
        )
        lift_ratio = (
            sum(value > 0 for value in oos_lifts) / len(oos_lifts) if oos_lifts else None
        )
        valid = (
            len(results) >= 2
            and valid_ratio >= 0.6
            and lift_ratio is not None
            and lift_ratio >= 0.6
            and calibration.calibrated
        )
        return ConditionalEvidenceValidation(
            definition,
            tuple(results),
            calibration,
            valid_ratio,
            lift_ratio,
            "TESTED" if valid else "VALIDATING",
            None if valid else "OOS stability/calibration gate not passed",
        )

    @staticmethod
    def _invalid(
        definition: ConditionalDefinition, reason: str
    ) -> ConditionalEvidenceValidation:
        return ConditionalEvidenceValidation(
            definition,
            (),
            ProbabilityCalibration(None, None, None, 0, False, reason),
            0.0,
            None,
            "DISABLED",
            reason,
        )
