from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite


class ModelStatus(StrEnum):
    EXPERIMENTAL = "Experimental"
    RESEARCH = "Research"
    VALIDATING = "Validating"
    TESTED = "Tested"
    PRODUCTION_APPROVED = "Production Approved"
    MANUAL_PILOT = "Manual Pilot"
    DISABLED = "Disabled"
    SUSPENDED = "Suspended"
    RETIRED = "Retired"


class ModelApprovalLevel(StrEnum):
    NONE = "none"
    CODE_REVIEW = "code_review"
    RESEARCH = "research"
    TESTED = "tested"
    PRODUCTION = "production"
    MANUAL_PILOT = "manual_pilot"


@dataclass(frozen=True, slots=True)
class ModelRegistryEntry:
    model_id: str
    version: str
    owner: str
    objective: str
    inputs: tuple[str, ...]
    data_requirements: tuple[str, ...]
    training_period: tuple[date, date] | None
    validation_period: tuple[date, date] | None
    test_period: tuple[date, date] | None
    hyperparameters: dict[str, object]
    status: ModelStatus
    limitations: tuple[str, ...]
    approval_level: ModelApprovalLevel
    last_validation: date | None
    drift_status: str

    def __post_init__(self) -> None:
        if not all(
            item.strip() for item in (self.model_id, self.version, self.owner, self.objective)
        ):
            raise ValueError("model registry identity fields are required")
        periods = tuple(
            item
            for item in (self.training_period, self.validation_period, self.test_period)
            if item is not None
        )
        if any(start >= end for start, end in periods):
            raise ValueError("model registry periods must have positive duration")
        if self.training_period and self.validation_period:
            if self.training_period[1] >= self.validation_period[0]:
                raise ValueError("training and validation periods must not overlap")
        if self.validation_period and self.test_period:
            if self.validation_period[1] >= self.test_period[0]:
                raise ValueError("validation and locked test periods must not overlap")


@dataclass(frozen=True, slots=True)
class DriftAssessment:
    status: str
    severity: str
    failed_metrics: tuple[str, ...]
    action: str
    observed: dict[str, float]
    thresholds: dict[str, float]


def assess_model_drift(
    observed: dict[str, float],
    thresholds: dict[str, float],
) -> DriftAssessment:
    if not observed or set(observed) != set(thresholds):
        return DriftAssessment(
            "insufficient",
            "high",
            tuple(sorted(set(thresholds) - set(observed))),
            "suspend_new_signals",
            observed,
            thresholds,
        )
    if any(
        not isfinite(value) or value < 0 for value in (*observed.values(), *thresholds.values())
    ):
        raise ValueError("drift metrics and thresholds must be finite and nonnegative")
    failed = tuple(sorted(name for name, value in observed.items() if value > thresholds[name]))
    if len(failed) >= max(2, len(observed) // 2):
        return DriftAssessment(
            "drifting", "high", failed, "suspend_new_signals", observed, thresholds
        )
    if failed:
        return DriftAssessment(
            "warning", "medium", failed, "degrade_to_research_only", observed, thresholds
        )
    return DriftAssessment("stable", "low", (), "continue_monitoring", observed, thresholds)
