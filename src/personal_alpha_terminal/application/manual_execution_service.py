from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import ManualExecutionRecord, ManualRebalanceTicketRecord


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
