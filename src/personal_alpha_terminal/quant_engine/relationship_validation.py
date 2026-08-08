from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class RelationshipUse(StrEnum):
    RESEARCH_INSIGHT = "RESEARCH_INSIGHT"
    ALPHA_CANDIDATE = "ALPHA_CANDIDATE"


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    adjusted_p_value: float
    gross_expected_return: float
    estimated_cost: float
    oos_periods: int
    oos_survival_ratio: float
    effective_sample_size: float


@dataclass(frozen=True, slots=True)
class RelationshipValidation:
    use: RelationshipUse
    after_cost_expected_return: float
    blockers: tuple[str, ...]


def validate_relationship_for_alpha(
    evidence: RelationshipEvidence,
    *,
    significance_level: float = 0.05,
    minimum_effective_sample: float = 30,
    minimum_oos_periods: int = 3,
    minimum_oos_survival: float = 0.6,
) -> RelationshipValidation:
    """Separate statistical relationships from economically useful Alpha."""

    values = (
        evidence.adjusted_p_value,
        evidence.gross_expected_return,
        evidence.estimated_cost,
        evidence.oos_survival_ratio,
        evidence.effective_sample_size,
    )
    if any(not isfinite(value) for value in values):
        raise ValueError("relationship evidence must be finite")
    net = evidence.gross_expected_return - evidence.estimated_cost
    blockers: list[str] = []
    if evidence.adjusted_p_value > significance_level:
        blockers.append("multiple-testing-adjusted significance failed")
    if evidence.effective_sample_size < minimum_effective_sample:
        blockers.append("effective sample size is insufficient")
    if evidence.oos_periods < minimum_oos_periods:
        blockers.append("too few out-of-sample periods")
    if evidence.oos_survival_ratio < minimum_oos_survival:
        blockers.append("out-of-sample edge survival is unstable")
    if net <= 0:
        blockers.append("expected relationship return is not positive after cost")
    return RelationshipValidation(
        RelationshipUse.RESEARCH_INSIGHT if blockers else RelationshipUse.ALPHA_CANDIDATE,
        net,
        tuple(blockers),
    )
