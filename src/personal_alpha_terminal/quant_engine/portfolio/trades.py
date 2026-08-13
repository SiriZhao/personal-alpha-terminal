from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioTarget


class TradeAction(StrEnum):
    BUY = "BUY"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class TradeEvidence:
    expected_alpha: float
    confidence: float | None
    horizon: int
    primary_evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    confidence_calibrated: bool = False


@dataclass(frozen=True, slots=True)
class TradeProposal:
    ticker: str
    action: TradeAction
    current_weight: float
    target_weight: float
    delta_weight: float
    estimated_trade_value: float
    estimated_cost: float
    risk_contribution: float
    expected_alpha: float
    confidence: float | None
    horizon: int
    reason: str
    primary_evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    model_version: str
    data_version: str
    data_quality: str
    manual_confirmation_required: bool = True


class TradeGenerator:
    def __init__(self, cost_model: TransactionCostModel | None = None) -> None:
        self.cost_model = cost_model or TransactionCostModel()

    def generate(
        self,
        *,
        target: PortfolioTarget,
        current_weights: dict[str, float],
        portfolio_value: float,
        evidence: dict[str, TradeEvidence],
        risk_contribution: dict[str, float],
        average_daily_dollar_volume: dict[str, float],
        minimum_trade_weight: float,
    ) -> tuple[TradeProposal, ...]:
        if not target.operational_approved:
            return ()
        if portfolio_value <= 0 or minimum_trade_weight < 0:
            raise ValueError("trade generation inputs are invalid")
        proposals: list[TradeProposal] = []
        for symbol in sorted(set(current_weights) | set(target.target_weights)):
            current = current_weights.get(symbol, 0.0)
            desired = target.target_weights.get(symbol, 0.0)
            delta = desired - current
            if not all(isfinite(value) for value in (current, desired, delta)):
                raise ValueError("trade weights must be finite")
            if abs(delta) < minimum_trade_weight:
                action = TradeAction.HOLD
                desired = current
                delta = 0.0
            elif current == 0 and delta > 0:
                action = TradeAction.BUY
            elif desired == 0 and delta < 0:
                action = TradeAction.SELL
            elif delta > 0:
                action = TradeAction.INCREASE
            else:
                action = TradeAction.REDUCE
            trade_value = abs(delta) * portfolio_value
            cost = self.cost_model.estimate(
                trade_value=trade_value,
                average_daily_dollar_volume=average_daily_dollar_volume[symbol],
            )
            item = evidence.get(symbol)
            if item is None and action in {TradeAction.BUY, TradeAction.INCREASE}:
                raise ValueError(f"new or increased position lacks alpha evidence: {symbol}")
            if item is None:
                item = TradeEvidence(0.0, None, 0, (), ("position removed from target",))
            proposals.append(
                TradeProposal(
                    ticker=symbol,
                    action=action,
                    current_weight=current,
                    target_weight=desired,
                    delta_weight=delta,
                    estimated_trade_value=trade_value,
                    estimated_cost=cost.total_cost,
                    risk_contribution=risk_contribution.get(symbol, 0.0),
                    expected_alpha=item.expected_alpha,
                    confidence=item.confidence,
                    horizon=item.horizon,
                    reason=_reason(action, item, target),
                    primary_evidence=item.primary_evidence,
                    counter_evidence=item.counter_evidence,
                    model_version=target.model_version,
                    data_version=target.data_version,
                    data_quality="VALID",
                )
            )
        return tuple(proposals)


def _reason(action: TradeAction, evidence: TradeEvidence, target: PortfolioTarget) -> str:
    if action is TradeAction.HOLD:
        return "target difference is inside the no-trade band"
    if action in {TradeAction.BUY, TradeAction.INCREASE}:
        return (
            "validated expected alpha remained positive after covariance, risk, "
            "liquidity, turnover and cost constraints"
        )
    return (
        "portfolio optimizer reduced exposure after alpha, covariance, risk budget "
        f"and transaction-cost evaluation; target alpha={target.expected_alpha:.6f}"
    )
