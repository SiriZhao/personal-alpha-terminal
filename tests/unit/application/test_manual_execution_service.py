from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.manual_execution_service import (
    ManualExecutionAuditService,
    ManualExecutionStatus,
    ManualExecutionSubmission,
)
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.models import (
    Base,
    ManualExecutionRecord,
    ManualRebalanceTicketRecord,
    Portfolio,
    PortfolioPosition,
    SecurityMaster,
)


def _seed(session: Session) -> tuple[ManualRebalanceTicketRecord, SecurityMaster]:
    now = datetime(2026, 8, 7, 20, tzinfo=UTC)
    portfolio = Portfolio(name="Real Schwab", base_currency="USD", cash_balance=Decimal("10000"))
    security = SecurityMaster(
        canonical_code="US:XNAS:AAPL",
        symbol="AAPL",
        name="Apple",
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
        list_date=date(1980, 12, 12),
        source="fixture",
        provider="fixture",
        available_time=now,
        ingested_time=now,
    )
    session.add_all((portfolio, security))
    session.flush()
    ticket = ManualRebalanceTicketRecord(
        ticket_id="MR-20260807-AAPL",
        portfolio_id=portfolio.id,
        status="reviewed",
        signal_as_of=now,
        decision_time=now,
        earliest_execution_time=datetime(2026, 8, 10, 13, 30, tzinfo=UTC),
        authorization_id="auth-1",
        data_version="data-v1",
        payload={"manual_review": "ACCEPTED"},
    )
    session.add(ticket)
    session.flush()
    return ticket, security


def test_partial_manual_execution_is_audited_without_changing_holdings() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            ticket, security = _seed(session)
            submission = ManualExecutionSubmission(
                execution_id="schwab-fill-1",
                ticket_record_id=ticket.id,
                stock_id=security.id,
                status=ManualExecutionStatus.PARTIAL,
                requested_shares=10,
                actual_shares=4,
                expected_price=100.0,
                actual_price=101.0,
                expected_cost=2.0,
                actual_fee=0.25,
                reported_at=datetime(2026, 8, 10, 14, tzinfo=UTC),
            )
            service = ManualExecutionAuditService(session)
            audit = service.record(submission)
            repeated = service.record(submission)

            assert audit.status is ManualExecutionStatus.PARTIAL
            assert audit.slippage == pytest.approx(1.0)
            assert audit.execution_deviation == pytest.approx(3.45)
            assert audit.completion_rate == pytest.approx(0.4)
            assert not audit.holdings_changed
            assert repeated == audit
            assert ticket.status == "partially_filled"
            assert session.scalar(select(PortfolioPosition)) is None
            assert len(tuple(session.scalars(select(ManualExecutionRecord)))) == 1
    finally:
        engine.dispose()


def test_cancelled_execution_has_no_price_or_fill() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            ticket, security = _seed(session)
            audit = ManualExecutionAuditService(session).record(
                ManualExecutionSubmission(
                    execution_id="schwab-cancel-1",
                    ticket_record_id=ticket.id,
                    stock_id=security.id,
                    status=ManualExecutionStatus.CANCELLED,
                    requested_shares=10,
                    actual_shares=0,
                    expected_price=100.0,
                    actual_price=None,
                    expected_cost=2.0,
                    actual_fee=0.0,
                    reported_at=datetime(2026, 8, 10, 14, tzinfo=UTC),
                )
            )
            assert audit.execution_deviation is None
            assert audit.completion_rate == 0
            assert ticket.status == "cancelled"
    finally:
        engine.dispose()
