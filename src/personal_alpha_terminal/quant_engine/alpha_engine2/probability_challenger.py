"""ROUND 8: Probability challenger gate.

The Classical Quant Core is the champion.  The Probability challenger is
re-trained and compared strictly against the classical-only arm.  It is promoted
only when every gate passes: calibration, discrimination, OOS incremental value,
actual target-weight change, cost-adjusted improvement and stability.  Any
miss keeps Probability RESEARCH_ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProbabilityVerdict(StrEnum):
    PROBABILITY_PROMOTED = "PROBABILITY_PROMOTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class ProbabilityChallengerEvidence:
    calibration_ok: bool
    discrimination_ok: bool
    oos_incremental_ok: bool
    target_weight_changed: bool
    cost_adjusted_improvement: bool
    stability_ok: bool
    # Supporting numbers (recorded regardless of verdict)
    brier_score: float | None = None
    roc_auc: float | None = None
    oos_classical_net_return: float | None = None
    oos_probability_net_return: float | None = None
    target_change_count: int = 0
    cost_delta: float | None = None

    @property
    def promoted(self) -> bool:
        return all(
            (
                self.calibration_ok,
                self.discrimination_ok,
                self.oos_incremental_ok,
                self.target_weight_changed,
                self.cost_adjusted_improvement,
                self.stability_ok,
            )
        )

    def verdict(self) -> ProbabilityVerdict:
        return (
            ProbabilityVerdict.PROBABILITY_PROMOTED
            if self.promoted
            else ProbabilityVerdict.RESEARCH_ONLY
        )

    def document(self) -> dict[str, object]:
        return {
            "calibration_ok": self.calibration_ok,
            "discrimination_ok": self.discrimination_ok,
            "oos_incremental_ok": self.oos_incremental_ok,
            "target_weight_changed": self.target_weight_changed,
            "cost_adjusted_improvement": self.cost_adjusted_improvement,
            "stability_ok": self.stability_ok,
            "brier_score": self.brier_score,
            "roc_auc": self.roc_auc,
            "oos_classical_net_return": self.oos_classical_net_return,
            "oos_probability_net_return": self.oos_probability_net_return,
            "target_change_count": self.target_change_count,
            "cost_delta": self.cost_delta,
            "verdict": self.verdict().value,
        }


def evaluate_probability_challenger(
    *,
    brier_score: float,
    baseline_brier_score: float,
    roc_auc: float,
    oos_classical_net_return: float,
    oos_probability_net_return: float,
    target_change_count: int,
    cost_delta: float,
    stability: float,
    min_roc_auc: float = 0.55,
    min_stability: float = 0.60,
) -> ProbabilityChallengerEvidence:
    """Evaluate the six promotion gates with the pre-fixed thresholds.

    - calibration_ok: probability Brier improves on the baseline classifier.
    - discrimination_ok: ROC-AUC is materially better than chance.
    - oos_incremental_ok: adding probability improves OOS net return.
    - target_weight_changed: at least one target weight actually moved.
    - cost_adjusted_improvement: net improvement exceeds added cost.
    - stability_ok: the improvement is stable across periods.
    """
    calibration_ok = brier_score < baseline_brier_score
    discrimination_ok = roc_auc >= min_roc_auc
    oos_incremental_ok = oos_probability_net_return > oos_classical_net_return
    target_weight_changed = target_change_count > 0
    cost_adjusted_improvement = (
        oos_probability_net_return - oos_classical_net_return
    ) > max(0.0, cost_delta)
    stability_ok = stability >= min_stability
    return ProbabilityChallengerEvidence(
        calibration_ok=calibration_ok,
        discrimination_ok=discrimination_ok,
        oos_incremental_ok=oos_incremental_ok,
        target_weight_changed=target_weight_changed,
        cost_adjusted_improvement=cost_adjusted_improvement,
        stability_ok=stability_ok,
        brier_score=brier_score,
        roc_auc=roc_auc,
        oos_classical_net_return=oos_classical_net_return,
        oos_probability_net_return=oos_probability_net_return,
        target_change_count=target_change_count,
        cost_delta=cost_delta,
    )
