"""ROUND 8: Champion/Challenger promotion gate.

The Classical Quant Core is the CHAMPION.  Any new strategy is a CHALLENGER and
defaults to no production access.  Promotion requires a pre-fixed, all-gates
policy covering OOS net alpha, Sharpe/IR, drawdown, turnover, cost, stability,
forward consistency and robustness.  Merely higher returns are never enough;
CLASSICAL_CHAMPION_RETAINED is a fully valid outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PromotionVerdict(StrEnum):
    CHALLENGER_PROMOTED = "CHALLENGER_PROMOTED"
    CLASSICAL_CHAMPION_RETAINED = "CLASSICAL_CHAMPION_RETAINED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Pre-fixed promotion criteria.  All must pass."""

    min_oos_net_alpha: float = 0.02  # 200 bps annualized net after cost
    min_oos_sharpe: float = 0.50
    min_oos_ir: float = 0.50
    max_drawdown: float = 0.25
    max_annual_turnover: float = 4.0
    max_cost_bps: float = 100.0
    min_stability: float = 0.60
    min_forward_consistency: float = 0.50
    min_robustness: float = 0.50
    # A challenger must beat the champion by a meaningful edge, not just be
    # marginally higher.  These margins prevent promotion on luck.
    min_alpha_edge: float = 0.01  # 100 bps net-alpha edge over champion
    min_sharpe_edge: float = 0.10
    min_ir_edge: float = 0.10

    def __post_init__(self) -> None:
        if (
            self.min_oos_net_alpha <= 0
            or self.min_oos_sharpe <= 0
            or self.min_oos_ir <= 0
            or not 0 < self.max_drawdown <= 1
            or self.max_annual_turnover <= 0
            or self.max_cost_bps <= 0
            or not 0 <= self.min_stability <= 1
            or not 0 <= self.min_forward_consistency <= 1
            or not 0 <= self.min_robustness <= 1
            or self.min_alpha_edge <= 0
            or self.min_sharpe_edge <= 0
            or self.min_ir_edge <= 0
        ):
            raise ValueError("promotion policy bounds are invalid")


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    oos_net_alpha: float
    oos_sharpe: float
    oos_ir: float
    max_drawdown: float
    annual_turnover: float
    cost_bps: float
    stability: float
    forward_consistency: float
    robustness: float


@dataclass(frozen=True, slots=True)
class PromotionEvaluation:
    verdict: PromotionVerdict
    failures: tuple[str, ...]
    champion: StrategyMetrics
    challenger: StrategyMetrics
    policy: PromotionPolicy
    challenger_id: str

    def document(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "failures": list(self.failures),
            "champion": _metrics_document(self.champion),
            "challenger": _metrics_document(self.challenger),
            "policy": _policy_document(self.policy),
            "challenger_id": self.challenger_id,
        }


def evaluate_promotion(
    *,
    challenger_id: str,
    champion: StrategyMetrics,
    challenger: StrategyMetrics,
    policy: PromotionPolicy | None = None,
) -> PromotionEvaluation:
    """Fail-closed promotion gate.  Every criterion must be satisfied."""
    configured = policy or PromotionPolicy()
    failures: list[str] = []

    if challenger.oos_net_alpha <= champion.oos_net_alpha + configured.min_alpha_edge:
        failures.append("OOS_NET_ALPHA_NOT_SUPERIOR")
    if challenger.oos_net_alpha < configured.min_oos_net_alpha:
        failures.append("OOS_NET_ALPHA_BELOW_MINIMUM")
    if challenger.oos_sharpe < max(
        configured.min_oos_sharpe, champion.oos_sharpe + configured.min_sharpe_edge
    ):
        failures.append("OOS_SHARPE_NOT_SUPERIOR")
    if challenger.oos_ir < max(
        configured.min_oos_ir, champion.oos_ir + configured.min_ir_edge
    ):
        failures.append("OOS_IR_NOT_SUPERIOR")
    if challenger.max_drawdown > min(configured.max_drawdown, champion.max_drawdown):
        failures.append("DRAWDOWN_WORSE_OR_EXCESSIVE")
    if challenger.annual_turnover > min(configured.max_annual_turnover, champion.annual_turnover):
        failures.append("TURNOVER_WORSE_OR_EXCESSIVE")
    if challenger.cost_bps > max(configured.max_cost_bps, champion.cost_bps):
        failures.append("COST_WORSE_OR_EXCESSIVE")
    # Drawdown, turnover and cost must also be at least as good as the champion.
    if challenger.max_drawdown >= champion.max_drawdown:
        failures.append("DRAWDOWN_NOT_IMPROVED")
    if challenger.annual_turnover >= champion.annual_turnover:
        failures.append("TURNOVER_NOT_IMPROVED")
    if challenger.cost_bps >= champion.cost_bps:
        failures.append("COST_NOT_IMPROVED")
    if challenger.stability < max(configured.min_stability, champion.stability):
        failures.append("STABILITY_NOT_SUPERIOR")
    if challenger.forward_consistency < max(
        configured.min_forward_consistency, champion.forward_consistency
    ):
        failures.append("FORWARD_CONSISTENCY_NOT_SUPERIOR")
    if challenger.robustness < max(configured.min_robustness, champion.robustness):
        failures.append("ROBUSTNESS_NOT_SUPERIOR")

    verdict = (
        PromotionVerdict.CHALLENGER_PROMOTED
        if not failures
        else PromotionVerdict.CLASSICAL_CHAMPION_RETAINED
    )
    return PromotionEvaluation(
        verdict=verdict,
        failures=tuple(failures),
        champion=champion,
        challenger=challenger,
        policy=configured,
        challenger_id=challenger_id,
    )


def _metrics_document(metrics: StrategyMetrics) -> dict[str, float]:
    return {
        "oos_net_alpha": metrics.oos_net_alpha,
        "oos_sharpe": metrics.oos_sharpe,
        "oos_ir": metrics.oos_ir,
        "max_drawdown": metrics.max_drawdown,
        "annual_turnover": metrics.annual_turnover,
        "cost_bps": metrics.cost_bps,
        "stability": metrics.stability,
        "forward_consistency": metrics.forward_consistency,
        "robustness": metrics.robustness,
    }


def _policy_document(policy: PromotionPolicy) -> dict[str, float]:
    return {
        "min_oos_net_alpha": policy.min_oos_net_alpha,
        "min_oos_sharpe": policy.min_oos_sharpe,
        "min_oos_ir": policy.min_oos_ir,
        "max_drawdown": policy.max_drawdown,
        "max_annual_turnover": policy.max_annual_turnover,
        "max_cost_bps": policy.max_cost_bps,
        "min_stability": policy.min_stability,
        "min_forward_consistency": policy.min_forward_consistency,
        "min_robustness": policy.min_robustness,
        "min_alpha_edge": policy.min_alpha_edge,
        "min_sharpe_edge": policy.min_sharpe_edge,
        "min_ir_edge": policy.min_ir_edge,
    }
