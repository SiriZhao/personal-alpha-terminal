from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from math import isfinite

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import (
    ManualExecutionFill,
    ManualExecutionOrder,
    ManualExecutionRecord,
    ManualRebalanceTicketRecord,
    QuantDecisionRecommendation,
    QuantDecisionRun,
)
from personal_alpha_terminal.portfolio.lifecycle import (
    FillGateDecision,
    evaluate_fill_gate,
)
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)
from personal_alpha_terminal.portfolio.management_schemas import TransactionDraft
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSession,
    MarketSessionCalendar,
)


class ManualExecutionStatus(StrEnum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    MODIFIED = "MODIFIED"


@dataclass(frozen=True, slots=True)
class ManualExecutionSubmission:
    execution_id: str
    ticket_record_id: int
    stock_id: int
    status: ManualExecutionStatus
    requested_shares: int
    actual_shares: int
    expected_price: float
    actual_price: float | None
    expected_cost: float
    actual_fee: float
    reported_at: datetime
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ManualExecutionAudit:
    execution_id: str
    status: ManualExecutionStatus
    slippage: float | None
    execution_deviation: float | None
    completion_rate: float
    holdings_changed: bool = False


class ManualExecutionAuditService:
    """Persist user-reported execution evidence without mutating holdings."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, submission: ManualExecutionSubmission) -> ManualExecutionAudit:
        self._validate(submission)
        existing = self.session.scalar(
            select(ManualExecutionRecord).where(
                ManualExecutionRecord.execution_id == submission.execution_id
            )
        )
        if existing is not None:
            return self._audit(existing)
        ticket = self.session.get(ManualRebalanceTicketRecord, submission.ticket_record_id)
        if ticket is None:
            raise ValueError("manual execution references an unknown rebalance ticket")

        slippage: float | None = None
        deviation: float | None = None
        if submission.actual_shares:
            assert submission.actual_price is not None
            direction = 1 if submission.requested_shares > 0 else -1
            slippage = direction * (submission.actual_price - submission.expected_price)
            completion = abs(submission.actual_shares / submission.requested_shares)
            prorated_expected_cost = submission.expected_cost * min(1.0, completion)
            deviation = (
                slippage * abs(submission.actual_shares)
                + submission.actual_fee
                - prorated_expected_cost
            )

        record = ManualExecutionRecord(
            execution_id=submission.execution_id,
            ticket_id=submission.ticket_record_id,
            stock_id=submission.stock_id,
            status=submission.status.value,
            requested_shares=submission.requested_shares,
            actual_shares=submission.actual_shares,
            expected_price=submission.expected_price,
            actual_price=submission.actual_price,
            expected_cost=submission.expected_cost,
            actual_fee=submission.actual_fee,
            slippage=slippage,
            execution_deviation=deviation,
            reported_at=submission.reported_at,
            notes=submission.notes,
        )
        self.session.add(record)
        if submission.status is ManualExecutionStatus.PARTIAL:
            ticket.status = "partially_filled"
        elif submission.status is ManualExecutionStatus.FILLED:
            ticket.status = "completed"
        elif submission.status is ManualExecutionStatus.CANCELLED:
            ticket.status = "cancelled"
        self.session.flush()
        return self._audit(record)

    @staticmethod
    def _validate(submission: ManualExecutionSubmission) -> None:
        if not submission.execution_id.strip() or submission.ticket_record_id <= 0:
            raise ValueError("manual execution identity is invalid")
        if submission.stock_id <= 0 or submission.requested_shares == 0:
            raise ValueError("manual execution security or requested quantity is invalid")
        if submission.reported_at.tzinfo is None:
            raise ValueError("manual execution timestamp must be timezone-aware")
        numeric = (submission.expected_price, submission.expected_cost, submission.actual_fee)
        if any(not isfinite(value) for value in numeric):
            raise ValueError("manual execution values must be finite")
        costs_are_negative = min(submission.expected_cost, submission.actual_fee) < 0
        if submission.expected_price <= 0 or costs_are_negative:
            raise ValueError("manual execution prices and costs are invalid")

        no_fill = submission.status in {
            ManualExecutionStatus.PENDING,
            ManualExecutionStatus.CANCELLED,
        }
        if no_fill:
            if submission.actual_shares != 0 or submission.actual_price is not None:
                raise ValueError("pending/cancelled execution cannot contain a fill")
            return
        if submission.actual_shares == 0 or submission.actual_price is None:
            raise ValueError("filled execution requires quantity and actual price")
        if not isfinite(submission.actual_price) or submission.actual_price <= 0:
            raise ValueError("actual execution price is invalid")
        if submission.actual_shares * submission.requested_shares <= 0:
            raise ValueError("actual execution direction differs from requested direction")
        actual = abs(submission.actual_shares)
        requested = abs(submission.requested_shares)
        if submission.status is ManualExecutionStatus.PARTIAL and not actual < requested:
            raise ValueError("partial execution must be smaller than requested quantity")
        if submission.status is ManualExecutionStatus.FILLED and actual != requested:
            raise ValueError("filled execution must equal requested quantity")
        if submission.status is ManualExecutionStatus.MODIFIED and actual == requested:
            raise ValueError("modified execution must differ from requested quantity")

    @staticmethod
    def _audit(record: ManualExecutionRecord) -> ManualExecutionAudit:
        completion = abs(record.actual_shares / record.requested_shares)
        return ManualExecutionAudit(
            execution_id=record.execution_id,
            status=ManualExecutionStatus(record.status),
            slippage=float(record.slippage) if record.slippage is not None else None,
            execution_deviation=(
                float(record.execution_deviation)
                if record.execution_deviation is not None
                else None
            ),
            completion_rate=completion,
        )


@dataclass(frozen=True, slots=True)
class ManualFillSubmission:
    fill_id: str
    recommendation_id: str
    quantity: float
    price: float
    fee: float
    executed_at: datetime
    external_reference: str | None = None
    notes: str = ""
    # Explicit user provenance required to record a fill against an expired or
    # stale recommendation.  Expiry/staleness can never be silently ignored.
    override_provenance: str | None = None


@dataclass(frozen=True, slots=True)
class ManualOrderMetrics:
    order_id: str
    recommendation_id: str
    run_id: int
    status: ManualExecutionStatus
    approved_quantity: float
    filled_quantity: float
    fill_ratio: float
    weighted_average_fill_price: float | None
    recommended_reference_price: float
    signed_slippage_bps: float | None
    total_fees: float
    execution_delay_seconds: float | None
    idempotent_replay: bool = False


class ManualExecutionOrderService:
    """Apply only user-reported Schwab fills to the real ledger, one fill at a time."""

    def __init__(
        self, session: Session, *, calendar: MarketSessionCalendar | None = None
    ) -> None:
        self.session = session
        self.calendar = calendar or MarketSessionCalendar()

    def ensure_order(
        self, recommendation: QuantDecisionRecommendation
    ) -> ManualExecutionOrder:
        if recommendation.review_status != "accepted":
            raise ValueError("manual execution order requires an accepted recommendation")
        if recommendation.run.gate_status != "APPROVED":
            raise ValueError("manual execution order requires an approved decision run")
        action = recommendation.action.upper()
        if action not in {"BUY", "ADD", "SELL", "REDUCE"}:
            raise ValueError(f"{action} has no executable manual order")
        approved_quantity = abs(Decimal(str(recommendation.suggested_shares)))
        if approved_quantity <= 0:
            raise ValueError("recommendation has no approved executable quantity")
        existing = self.session.scalar(
            select(ManualExecutionOrder).where(
                ManualExecutionOrder.recommendation_record_id == recommendation.id
            )
        )
        if existing is not None:
            return existing
        side = "BUY" if action in {"BUY", "ADD"} else "SELL"
        expected_cost = Decimal(
            str(recommendation.component_scores.get("estimated_cost", 0.0))
        )
        order = ManualExecutionOrder(
            order_id=f"manual:{recommendation.run_id}:{recommendation.recommendation_id}",
            recommendation_record_id=recommendation.id,
            recommendation_id=recommendation.recommendation_id,
            run_id=recommendation.run_id,
            portfolio_id=recommendation.run.portfolio_id,
            stock_id=recommendation.stock_id,
            symbol=recommendation.stock.symbol,
            side=side,
            approved_quantity=approved_quantity,
            original_approved_quantity=approved_quantity,
            expected_price=recommendation.reference_price,
            expected_cost=expected_cost,
            status=ManualExecutionStatus.PENDING.value,
            status_reason="accepted recommendation awaiting manual execution",
            status_updated_at=datetime.now(UTC),
        )
        self.session.add(order)
        self.session.flush()
        return order

    def record_fill(self, submission: ManualFillSubmission) -> ManualOrderMetrics:
        self._validate_fill(submission)
        duplicate = self.session.scalar(
            select(ManualExecutionFill).where(
                ManualExecutionFill.fill_id == submission.fill_id
            )
        )
        if duplicate is not None:
            if not self._same_fill(duplicate, submission):
                raise ValueError("duplicate fill_id has a different payload")
            return self.metrics(duplicate.order_id, idempotent_replay=True)
        recommendation = self.session.scalar(
            select(QuantDecisionRecommendation).where(
                QuantDecisionRecommendation.recommendation_id
                == submission.recommendation_id
            )
        )
        if recommendation is None:
            raise ValueError("decision recommendation does not exist")
        latest_run_id = self.session.scalar(
            select(func.max(QuantDecisionRun.id)).where(
                QuantDecisionRun.portfolio_id == recommendation.run.portfolio_id,
                QuantDecisionRun.gate_status == "APPROVED",
            )
        )
        gate = evaluate_fill_gate(
            recommendation,
            executed_at=submission.executed_at,
            latest_approved_run_id=latest_run_id,
            override_provenance=submission.override_provenance,
        )
        if gate.decision in {
            FillGateDecision.BLOCKED_EXPIRED,
            FillGateDecision.BLOCKED_STALE,
        }:
            raise ValueError(f"manual fill blocked: {gate.reason}")
        order = self.ensure_order(recommendation)
        if order.status in {
            ManualExecutionStatus.FILLED.value,
            ManualExecutionStatus.CANCELLED.value,
        }:
            raise ValueError(f"manual execution order is {order.status}")
        already_filled = self._filled_quantity(order.id)
        quantity = Decimal(str(submission.quantity))
        if already_filled + quantity > order.approved_quantity:
            raise ValueError("cumulative fill quantity exceeds approved recommendation")
        earliest = _aware_utc(recommendation.earliest_execution_time)
        if submission.executed_at.astimezone(UTC) < earliest:
            raise ValueError("manual fill precedes the earliest permitted execution time")
        market_state = self.calendar.classify(submission.executed_at)
        if market_state.session in {MarketSession.CLOSED, MarketSession.MAINTENANCE}:
            raise ValueError("manual fill timestamp is outside an eligible US trading session")
        transaction_type = "buy" if order.side == "BUY" else "sell"
        trade_date = market_state.trade_date
        settlement_date = self.calendar.next_trading_day(trade_date)
        repository = PortfolioManagementRepository(self.session)
        draft = TransactionDraft(
            transaction_type=transaction_type,
            trade_date=trade_date,
            settlement_date=settlement_date,
            currency=recommendation.stock.currency,
            fx_rate_to_base=1.0,
            event_time=submission.executed_at,
            available_time=submission.executed_at,
            stock_id=recommendation.stock_id,
            quantity=submission.quantity,
            unit_price=submission.price,
            fee_amount=submission.fee,
            source="manual_charles_schwab_fill",
            external_id=f"fill:{submission.fill_id}",
            notes=(
                f"Manual Charles Schwab fill; recommendation={submission.recommendation_id}. "
                f"{submission.notes.strip()}"
            ).strip(),
        )
        transaction = repository.add_transaction(
            portfolio_id=order.portfolio_id, draft=draft
        )
        repository.apply_trade_to_current_snapshot(
            portfolio_id=order.portfolio_id,
            stock_id=order.stock_id,
            as_of_date=trade_date,
            transaction_type=transaction_type,
            quantity=quantity,
            unit_price=Decimal(str(submission.price)),
            fee_amount=Decimal(str(submission.fee)),
            currency=recommendation.stock.currency,
        )
        fill = ManualExecutionFill(
            fill_id=submission.fill_id,
            order_id=order.id,
            recommendation_id=order.recommendation_id,
            run_id=order.run_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=Decimal(str(submission.price)),
            fee=Decimal(str(submission.fee)),
            executed_at=submission.executed_at,
            recorded_at=datetime.now(UTC),
            external_reference=submission.external_reference,
            notes=submission.notes,
            ledger_transaction_id=transaction.id,
        )
        self.session.add(fill)
        self.session.flush()
        total = already_filled + quantity
        order.status = (
            ManualExecutionStatus.FILLED.value
            if total == order.approved_quantity
            else ManualExecutionStatus.PARTIAL.value
        )
        order.status_reason = (
            "approved quantity fully filled"
            if order.status == ManualExecutionStatus.FILLED.value
            else "approved quantity partially filled"
        )
        order.status_updated_at = datetime.now(UTC)
        self.session.flush()
        return self.metrics(order.id)

    def cancel(self, recommendation_id: str, *, reason: str) -> ManualOrderMetrics:
        order = self._order_for_recommendation(recommendation_id)
        if not reason.strip():
            raise ValueError("cancellation requires an audit reason")
        if order.status == ManualExecutionStatus.FILLED.value:
            raise ValueError("filled manual execution order cannot be cancelled")
        order.status = ManualExecutionStatus.CANCELLED.value
        order.status_reason = reason.strip()
        order.status_updated_at = datetime.now(UTC)
        self.session.flush()
        return self.metrics(order.id)

    def modify_quantity(
        self,
        recommendation_id: str,
        *,
        approved_quantity: float,
        reason: str,
    ) -> ManualOrderMetrics:
        order = self._order_for_recommendation(recommendation_id)
        if not isfinite(approved_quantity) or approved_quantity <= 0:
            raise ValueError("modified approved quantity must be finite and positive")
        if not reason.strip():
            raise ValueError("manual quantity modification requires an audit reason")
        proposed = Decimal(str(approved_quantity))
        filled = self._filled_quantity(order.id)
        if proposed < filled:
            raise ValueError("modified quantity cannot be below quantity already filled")
        if proposed > order.original_approved_quantity:
            raise ValueError("manual modification cannot exceed the original approved quantity")
        if order.status in {
            ManualExecutionStatus.FILLED.value,
            ManualExecutionStatus.CANCELLED.value,
        }:
            raise ValueError(f"manual execution order is {order.status}")
        order.approved_quantity = proposed
        order.status = (
            ManualExecutionStatus.FILLED.value
            if proposed == filled
            else ManualExecutionStatus.MODIFIED.value
        )
        order.status_reason = reason.strip()
        order.status_updated_at = datetime.now(UTC)
        self.session.flush()
        return self.metrics(order.id)

    def metrics(
        self, order_record_id: int, *, idempotent_replay: bool = False
    ) -> ManualOrderMetrics:
        order = self.session.get(ManualExecutionOrder, order_record_id)
        if order is None:
            raise ValueError("manual execution order does not exist")
        fills = tuple(
            self.session.scalars(
                select(ManualExecutionFill)
                .where(ManualExecutionFill.order_id == order.id)
                .order_by(ManualExecutionFill.executed_at, ManualExecutionFill.id)
            )
        )
        filled = sum((item.quantity for item in fills), Decimal("0"))
        notional = sum((item.quantity * item.price for item in fills), Decimal("0"))
        weighted_price = float(notional / filled) if filled > 0 else None
        expected_price = float(order.expected_price)
        direction = 1.0 if order.side == "BUY" else -1.0
        slippage_bps = (
            direction * (weighted_price - expected_price) / expected_price * 10000
            if weighted_price is not None
            else None
        )
        recommendation = self.session.get(
            QuantDecisionRecommendation, order.recommendation_record_id
        )
        delay = None
        if fills and recommendation is not None:
            delay = (
                _aware_utc(fills[0].executed_at)
                - _aware_utc(recommendation.earliest_execution_time)
            ).total_seconds()
        return ManualOrderMetrics(
            order_id=order.order_id,
            recommendation_id=order.recommendation_id,
            run_id=order.run_id,
            status=ManualExecutionStatus(order.status),
            approved_quantity=float(order.approved_quantity),
            filled_quantity=float(filled),
            fill_ratio=float(filled / order.approved_quantity),
            weighted_average_fill_price=weighted_price,
            recommended_reference_price=expected_price,
            signed_slippage_bps=slippage_bps,
            total_fees=float(sum((item.fee for item in fills), Decimal("0"))),
            execution_delay_seconds=delay,
            idempotent_replay=idempotent_replay,
        )

    def _order_for_recommendation(
        self, recommendation_id: str
    ) -> ManualExecutionOrder:
        order = self.session.scalar(
            select(ManualExecutionOrder).where(
                ManualExecutionOrder.recommendation_id == recommendation_id
            )
        )
        if order is None:
            recommendation = self.session.scalar(
                select(QuantDecisionRecommendation).where(
                    QuantDecisionRecommendation.recommendation_id == recommendation_id
                )
            )
            if recommendation is None:
                raise ValueError("decision recommendation does not exist")
            order = self.ensure_order(recommendation)
        return order

    def _filled_quantity(self, order_record_id: int) -> Decimal:
        value = self.session.scalar(
            select(func.coalesce(func.sum(ManualExecutionFill.quantity), 0)).where(
                ManualExecutionFill.order_id == order_record_id
            )
        )
        return Decimal(str(value))

    @staticmethod
    def _validate_fill(submission: ManualFillSubmission) -> None:
        if not submission.fill_id.strip() or not submission.recommendation_id.strip():
            raise ValueError("fill and recommendation identity are required")
        numeric = (submission.quantity, submission.price, submission.fee)
        if any(not isfinite(value) for value in numeric):
            raise ValueError("manual fill values must be finite")
        if submission.quantity <= 0 or submission.price <= 0 or submission.fee < 0:
            raise ValueError("manual fill quantity/price/fee are invalid")
        if submission.executed_at.tzinfo is None:
            raise ValueError("manual fill timestamp must be timezone-aware")

    @staticmethod
    def _same_fill(record: ManualExecutionFill, submission: ManualFillSubmission) -> bool:
        return (
            record.recommendation_id == submission.recommendation_id
            and record.quantity == Decimal(str(submission.quantity))
            and record.price == Decimal(str(submission.price))
            and record.fee == Decimal(str(submission.fee))
            and _aware_utc(record.executed_at) == submission.executed_at.astimezone(UTC)
        )


def _aware_utc(value: datetime) -> datetime:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).astimezone(UTC)
