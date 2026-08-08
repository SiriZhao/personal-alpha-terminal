from dataclasses import dataclass
from datetime import datetime
from math import floor

from personal_alpha_terminal.quant_engine.portfolio.holdings import PortfolioSnapshot
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class RebalanceTicket:
    permanent_security_id: str
    ticker: str
    current_weight: float
    target_weight: float
    action: str
    suggested_shares: int
    reference_price: float
    estimated_cost: float
    requires_manual_confirmation: bool = True


@dataclass(frozen=True, slots=True)
class ManualRebalancePlan:
    generated_at: datetime
    authorization_id: str
    tickets: tuple[RebalanceTicket, ...]
    cash_after_estimated_trades: float
    execution_status: str = "NOT_EXECUTED"


class RebalanceEngine:
    def generate_plan(
        self,
        *,
        authorization: ResearchDataAuthorization,
        snapshot: PortfolioSnapshot,
        target_weights: dict[str, float],
        reference_prices: dict[str, float],
        ticker_by_id: dict[str, str],
        generated_at: datetime,
        minimum_trade_value: float = 100.0,
        estimated_cost_rate: float = 0.0007,
    ) -> ManualRebalancePlan:
        ResearchDataGate.require(authorization, ResearchPurpose.REBALANCE)
        if generated_at.tzinfo is None or generated_at < snapshot.as_of:
            raise ValueError("rebalance generation time is invalid")
        if sum(target_weights.values()) > 1 + 1e-12 or any(
            not 0 <= weight <= 1 for weight in target_weights.values()
        ):
            raise ValueError("target weights must be long-only and sum to at most one")
        current = snapshot.weights
        tickets: list[RebalanceTicket] = []
        estimated_cash = snapshot.cash
        for security_id in sorted(set(current) | set(target_weights)):
            price = reference_prices.get(security_id)
            if price is None or price <= 0:
                raise ValueError(f"missing positive reference price for {security_id}")
            delta_value = (target_weights.get(security_id, 0) - current.get(security_id, 0)) * (
                snapshot.total_value
            )
            if abs(delta_value) < minimum_trade_value:
                continue
            shares = floor(abs(delta_value) / price)
            if shares == 0:
                continue
            signed_shares = shares if delta_value > 0 else -shares
            cost = abs(signed_shares) * price * estimated_cost_rate
            estimated_cash -= signed_shares * price + cost
            tickets.append(
                RebalanceTicket(
                    permanent_security_id=security_id,
                    ticker=ticker_by_id[security_id],
                    current_weight=current.get(security_id, 0),
                    target_weight=target_weights.get(security_id, 0),
                    action="BUY" if signed_shares > 0 else "SELL",
                    suggested_shares=signed_shares,
                    reference_price=price,
                    estimated_cost=cost,
                )
            )
        if estimated_cash < -1e-9:
            raise ValueError("rebalance plan exceeds available cash after estimated costs")
        return ManualRebalancePlan(
            generated_at,
            authorization.authorization_id,
            tuple(tickets),
            estimated_cash,
        )
