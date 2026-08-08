from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import floor, isfinite

from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


class ReviewDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class RebalanceCandidate:
    ticker: str
    permanent_security_id: str
    current_weight: float
    target_weight: float
    reference_price: float
    lot_size: int
    maximum_shares: int
    evidence_grade: str
    base_signal: str
    conditional_overlay: str
    risk_adjustment: str
    estimated_cost_rate: float
    liquidity: str
    earnings_risk: str
    invalidation_condition: str
    order_deadline: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        numeric = (
            self.current_weight,
            self.target_weight,
            self.reference_price,
            self.estimated_cost_rate,
        )
        if any(not isfinite(value) for value in numeric):
            raise ValueError("rebalance candidate values must be finite")
        if not 0 <= self.current_weight <= 1 or not 0 <= self.target_weight <= 1:
            raise ValueError("rebalance weights must be in [0, 1]")
        if self.reference_price <= 0 or self.lot_size < 1 or self.maximum_shares < 0:
            raise ValueError("rebalance execution inputs are invalid")
        if self.estimated_cost_rate < 0:
            raise ValueError("estimated cost cannot be negative")
        if self.order_deadline.tzinfo is None:
            raise ValueError("order_deadline must be timezone-aware")
        if not self.ticker.strip() or not self.permanent_security_id.strip():
            raise ValueError("candidate requires ticker and permanent security id")


@dataclass(frozen=True, slots=True)
class ManualRebalanceItem:
    ticker: str
    permanent_security_id: str
    current_weight: float
    target_weight: float
    action: str
    suggested_shares: int
    maximum_shares: int
    reference_price: float
    evidence_grade: str
    base_signal: str
    conditional_overlay: str
    risk_adjustment: str
    expected_cost: float
    liquidity: str
    earnings_risk: str
    invalidation_condition: str
    order_deadline: datetime
    notes: str
    review_decision: ReviewDecision = ReviewDecision.PENDING
    review_reason: str = ""


@dataclass(frozen=True, slots=True)
class ManualRebalanceTicket:
    ticket_id: str
    generated_at: datetime
    signal_as_of: datetime
    decision_time: datetime
    order_generation_time: datetime
    earliest_execution_time: datetime
    portfolio_value: float
    available_cash: float
    items: tuple[ManualRebalanceItem, ...]
    authorization_id: str
    data_version: str
    manual_review_required: bool = True
    automatic_execution_allowed: bool = False


@dataclass(frozen=True, slots=True)
class ManualFill:
    permanent_security_id: str
    actual_price: float
    actual_shares: int
    fees: float
    timestamp: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        if self.actual_price <= 0 or self.actual_shares == 0 or self.fees < 0:
            raise ValueError("manual fill price, shares, or fees are invalid")
        if self.timestamp.tzinfo is None:
            raise ValueError("manual fill timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FillAttribution:
    permanent_security_id: str
    implementation_shortfall: float
    price_slippage: float
    fee_drag: float
    share_completion_rate: float
    target_value_deviation: float
    signal_decay_not_measured: bool = True


class ManualRebalanceEngine:
    """Generate reviewable tickets only; this class has no broker or order API."""

    def generate(
        self,
        *,
        authorization: ResearchDataAuthorization,
        candidates: tuple[RebalanceCandidate, ...],
        portfolio_value: float,
        available_cash: float,
        signal_as_of: datetime,
        order_generation_time: datetime,
        earliest_execution_time: datetime,
        maximum_turnover: float,
    ) -> ManualRebalanceTicket:
        ResearchDataGate.require(authorization, ResearchPurpose.REBALANCE)
        if min(portfolio_value, available_cash) < 0 or portfolio_value <= 0:
            raise ValueError("portfolio value and cash are invalid")
        if not 0 <= maximum_turnover <= 1:
            raise ValueError("maximum_turnover must be in [0, 1]")
        times = (signal_as_of, order_generation_time, earliest_execution_time)
        if any(item.tzinfo is None for item in times):
            raise ValueError("rebalance workflow timestamps must be timezone-aware")
        if not signal_as_of <= authorization.request.decision_time <= order_generation_time:
            raise ValueError("signal/decision/order timestamps are out of sequence")
        if earliest_execution_time <= order_generation_time:
            raise ValueError("execution must occur after order generation")
        if sum(item.target_weight for item in candidates) > 1 + 1e-12:
            raise ValueError("target weights imply leverage")

        turnover = sum(abs(item.target_weight - item.current_weight) for item in candidates) / 2
        scale = min(1.0, maximum_turnover / turnover) if turnover > 0 else 1.0
        items: list[ManualRebalanceItem] = []
        remaining_cash = available_cash
        for candidate in sorted(candidates, key=lambda item: item.permanent_security_id):
            delta_weight = (candidate.target_weight - candidate.current_weight) * scale
            desired_value = delta_weight * portfolio_value
            raw_shares = desired_value / candidate.reference_price
            sign = 1 if raw_shares > 0 else -1 if raw_shares < 0 else 0
            rounded = sign * floor(abs(raw_shares) / candidate.lot_size) * candidate.lot_size
            rounded = max(-candidate.maximum_shares, min(candidate.maximum_shares, rounded))
            if rounded > 0:
                affordable = (
                    floor(
                        remaining_cash
                        / (candidate.reference_price * (1 + candidate.estimated_cost_rate))
                        / candidate.lot_size
                    )
                    * candidate.lot_size
                )
                rounded = min(rounded, affordable)
            trade_value = rounded * candidate.reference_price
            expected_cost = abs(trade_value) * candidate.estimated_cost_rate
            if rounded > 0:
                remaining_cash -= trade_value + expected_cost
            elif rounded < 0:
                remaining_cash += abs(trade_value) - expected_cost
            action = "BUY" if rounded > 0 else "SELL" if rounded < 0 else "HOLD"
            items.append(
                ManualRebalanceItem(
                    ticker=candidate.ticker,
                    permanent_security_id=candidate.permanent_security_id,
                    current_weight=candidate.current_weight,
                    target_weight=candidate.current_weight + delta_weight,
                    action=action,
                    suggested_shares=rounded,
                    maximum_shares=candidate.maximum_shares,
                    reference_price=candidate.reference_price,
                    evidence_grade=candidate.evidence_grade,
                    base_signal=candidate.base_signal,
                    conditional_overlay=candidate.conditional_overlay,
                    risk_adjustment=candidate.risk_adjustment,
                    expected_cost=expected_cost,
                    liquidity=candidate.liquidity,
                    earnings_risk=candidate.earnings_risk,
                    invalidation_condition=candidate.invalidation_condition,
                    order_deadline=candidate.order_deadline,
                    notes=candidate.notes,
                )
            )
        ticket_id = (
            f"MR-{order_generation_time:%Y%m%dT%H%M%S}-{authorization.authorization_id[:12]}"
        )
        return ManualRebalanceTicket(
            ticket_id=ticket_id,
            generated_at=order_generation_time,
            signal_as_of=signal_as_of,
            decision_time=authorization.request.decision_time,
            order_generation_time=order_generation_time,
            earliest_execution_time=earliest_execution_time,
            portfolio_value=portfolio_value,
            available_cash=available_cash,
            items=tuple(items),
            authorization_id=authorization.authorization_id,
            data_version=authorization.decision.evidence_fingerprint,
        )

    @staticmethod
    def attribute_fill(
        ticket: ManualRebalanceTicket,
        fill: ManualFill,
    ) -> FillAttribution:
        item = next(
            (
                candidate
                for candidate in ticket.items
                if candidate.permanent_security_id == fill.permanent_security_id
            ),
            None,
        )
        if item is None:
            raise ValueError("fill does not belong to the rebalance ticket")
        if item.suggested_shares == 0:
            raise ValueError("a HOLD item cannot have a fill")
        if fill.actual_shares * item.suggested_shares <= 0:
            raise ValueError("fill direction differs from the reviewed ticket")
        direction = 1 if item.suggested_shares > 0 else -1
        price_slippage = (
            direction * (fill.actual_price - item.reference_price) * abs(fill.actual_shares)
        )
        reference_value = abs(fill.actual_shares) * item.reference_price
        fee_drag = fill.fees
        implementation_shortfall = price_slippage + fee_drag
        completion = min(1.0, abs(fill.actual_shares / item.suggested_shares))
        target_value = item.suggested_shares * item.reference_price
        actual_value = fill.actual_shares * fill.actual_price
        return FillAttribution(
            permanent_security_id=fill.permanent_security_id,
            implementation_shortfall=implementation_shortfall,
            price_slippage=(price_slippage / reference_value if reference_value else 0.0),
            fee_drag=(fee_drag / reference_value if reference_value else 0.0),
            share_completion_rate=completion,
            target_value_deviation=actual_value - target_value,
        )
