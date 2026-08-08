from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from personal_alpha_terminal.application.decision_service import (
    DecisionService as ApplicationDecisionService,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import configure_database, init_database
from personal_alpha_terminal.decision_engine import (
    DecisionBatch,
    DecisionBatchStatus,
    DecisionRecommendation,
    DecisionRepository,
    DecisionService,
    UserDecision,
)
from personal_alpha_terminal.decision_engine.schemas import DecisionAction
from personal_alpha_terminal.models import (
    Portfolio,
    PortfolioPosition,
    PortfolioTransaction,
    Stock,
)
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)


def test_accepting_quant_decision_records_manual_review_without_execution() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    now = datetime(2026, 8, 1, 1, tzinfo=UTC)
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Core", base_currency="USD", cash_balance=Decimal("50000"))
        session.add_all((stock, portfolio))
        session.flush()
        batch = DecisionBatch(
            portfolio_id=portfolio.id,
            as_of_time=now,
            status=DecisionBatchStatus.GENERATED,
            gate_status="APPROVED",
            authorization_id="auth-1",
            data_version="data-v1",
            model_version="decision-v1",
            input_fingerprint="f" * 64,
            source_ids=("factor:1", "risk:1"),
            blockers=(),
            recommendations=(
                DecisionRecommendation(
                    recommendation_id="QD-test",
                    stock_id=stock.id,
                    ticker="AAPL",
                    permanent_security_id="FIGI-AAPL",
                    action=DecisionAction.BUY,
                    current_weight=0.0,
                    target_weight=0.1,
                    quant_score=75,
                    confidence_score=80,
                    component_scores={"factor": 20.0},
                    rationale=("factor evidence",),
                    risk_factors=("equity risk",),
                    evidence_grade="OOS_CALIBRATED",
                    sample_size=100,
                    source_ids=("factor:1", "risk:1"),
                    reference_price=200,
                    suggested_shares=25,
                    earliest_execution_time=now + timedelta(hours=14),
                    expires_at=now + timedelta(days=3),
                ),
            ),
        )
        service = DecisionService(DecisionRepository(session))
        service.repository.save_batch(batch)
        history = service.review(
            recommendation_id="QD-test",
            decision=UserDecision.ACCEPTED,
            decided_at=now + timedelta(minutes=1),
            reason="manual review complete",
        )
        session.commit()

        assert history.decision == "accepted"
        assert session.scalar(select(PortfolioPosition)) is None
        assert session.scalar(select(PortfolioTransaction)) is None

        with pytest.raises(ValueError, match="immutable"):
            service.review(
                recommendation_id="QD-test",
                decision=UserDecision.REJECTED,
                decided_at=now + timedelta(minutes=2),
            )


def test_accepted_candidate_can_record_manual_schwab_fill_once() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    now = datetime(2026, 8, 3, 1, tzinfo=UTC)
    with session_factory.begin() as session:
        stock = Stock(
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Core", base_currency="USD", cash_balance=Decimal("50000"))
        session.add_all((stock, portfolio))
        session.flush()
        batch = DecisionBatch(
            portfolio_id=portfolio.id,
            as_of_time=now,
            status=DecisionBatchStatus.GENERATED,
            gate_status="APPROVED",
            authorization_id="auth-1",
            data_version="data-v1",
            model_version="decision-v1",
            input_fingerprint="a" * 64,
            source_ids=("factor:1", "risk:1"),
            blockers=(),
            recommendations=(
                DecisionRecommendation(
                    recommendation_id="QD-manual-fill",
                    stock_id=stock.id,
                    ticker="AAPL",
                    permanent_security_id="FIGI-AAPL",
                    action=DecisionAction.BUY,
                    current_weight=0.0,
                    target_weight=0.1,
                    quant_score=75,
                    confidence_score=80,
                    component_scores={"factor": 20.0},
                    rationale=("factor evidence",),
                    risk_factors=("equity risk",),
                    evidence_grade="PRODUCTION_APPROVED",
                    sample_size=100,
                    source_ids=("factor:1", "risk:1"),
                    reference_price=200,
                    suggested_shares=25,
                    earliest_execution_time=now + timedelta(hours=13),
                    expires_at=now + timedelta(days=3),
                ),
            ),
        )
        repository = DecisionRepository(session)
        repository.save_batch(batch)
        repository.review(
            recommendation_id="QD-manual-fill",
            decision=UserDecision.ACCEPTED,
            decided_at=now + timedelta(minutes=1),
            reason="manual review complete",
        )

    with session_factory.begin() as session:
        service = ApplicationDecisionService(session)
        message = service.mark_executed(
            "QD-manual-fill",
            actual_price=201.25,
            quantity=10,
            fees=0.50,
            executed_at=now + timedelta(hours=14),
            notes="entered manually in Schwab",
        )
        assert message.startswith("EXECUTED_MANUALLY")

    with session_factory() as session:
        transaction = session.scalar(select(PortfolioTransaction))
        position = session.scalar(select(PortfolioPosition))
        portfolio = session.scalar(select(Portfolio))
        assert transaction is not None
        assert position is not None
        assert portfolio is not None
        assert transaction.source == "manual_charles_schwab"
        assert transaction.external_id == "decision:QD-manual-fill"
        assert transaction.quantity == Decimal("10.00000000")
        assert transaction.unit_price == Decimal("201.250000")
        assert position.quantity == Decimal("10.00000000")
        assert position.average_cost == Decimal("201.300000")
        assert portfolio.cash_balance == Decimal("47987.0000")

    with session_factory.begin() as session:
        message = ApplicationDecisionService(session).mark_executed(
            "QD-manual-fill",
            actual_price=201.25,
            quantity=10,
            fees=0.50,
            executed_at=now + timedelta(hours=14),
        )
        assert "already recorded" in message

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PortfolioTransaction)) == 1
        portfolio = session.scalar(select(Portfolio))
        assert portfolio is not None
        assert portfolio.cash_balance == Decimal("47987.0000")


def test_manual_fill_outside_us_session_is_rejected() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    now = datetime(2026, 8, 3, 1, tzinfo=UTC)
    with session_factory.begin() as session:
        stock = Stock(
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Core", base_currency="USD", cash_balance=50000)
        session.add_all((stock, portfolio))
        session.flush()
        DecisionRepository(session).save_batch(
            DecisionBatch(
                portfolio_id=portfolio.id,
                as_of_time=now,
                status=DecisionBatchStatus.GENERATED,
                gate_status="APPROVED",
                authorization_id="auth-closed",
                data_version="data-v1",
                model_version="decision-v1",
                input_fingerprint="b" * 64,
                source_ids=("factor:1",),
                blockers=(),
                recommendations=(
                    DecisionRecommendation(
                        recommendation_id="QD-closed-fill",
                        stock_id=stock.id,
                        ticker="AAPL",
                        permanent_security_id="FIGI-AAPL",
                        action=DecisionAction.BUY,
                        current_weight=0,
                        target_weight=0.1,
                        quant_score=75,
                        confidence_score=80,
                        component_scores={"factor": 20.0},
                        rationale=("factor evidence",),
                        risk_factors=("equity risk",),
                        evidence_grade="PRODUCTION_APPROVED",
                        sample_size=100,
                        source_ids=("factor:1",),
                        reference_price=200,
                        suggested_shares=25,
                        earliest_execution_time=now,
                        expires_at=now + timedelta(days=3),
                    ),
                ),
            )
        )
        DecisionRepository(session).review(
            recommendation_id="QD-closed-fill",
            decision=UserDecision.ACCEPTED,
            decided_at=now,
            reason="manual review complete",
        )
    with session_factory.begin() as session:
        with pytest.raises(ValueError, match="outside an eligible US trading session"):
            ApplicationDecisionService(session).mark_executed(
                "QD-closed-fill",
                actual_price=201.25,
                quantity=10,
                # Monday 22:00 ET is closed in the legacy market structure.
                executed_at=datetime(2026, 8, 4, 2, tzinfo=UTC),
            )


def test_rejected_candidate_cannot_be_marked_executed() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    with session_factory.begin() as session:
        with pytest.raises(ValueError, match="does not exist"):
            ApplicationDecisionService(session).mark_executed(
                "missing",
                actual_price=100,
                quantity=1,
            )


def test_manual_sell_updates_cash_and_snapshot_without_allowing_oversell() -> None:
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    with session_factory.begin() as session:
        stock = Stock(
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Core", base_currency="USD", cash_balance=1000)
        session.add_all((stock, portfolio))
        session.flush()
        session.add(
            PortfolioPosition(
                portfolio_id=portfolio.id,
                stock_id=stock.id,
                as_of_date=datetime(2026, 8, 3, tzinfo=UTC).date(),
                quantity=10,
                average_cost=100,
            )
        )
        session.flush()
        PortfolioManagementRepository(session).apply_trade_to_current_snapshot(
            portfolio_id=portfolio.id,
            stock_id=stock.id,
            as_of_date=datetime(2026, 8, 4, tzinfo=UTC).date(),
            transaction_type="sell",
            quantity=Decimal("4"),
            unit_price=Decimal("110"),
            fee_amount=Decimal("1"),
            currency="USD",
        )

    with session_factory() as session:
        portfolio = session.scalar(select(Portfolio))
        latest = session.scalar(
            select(PortfolioPosition)
            .where(PortfolioPosition.as_of_date == datetime(2026, 8, 4, tzinfo=UTC).date())
        )
        assert portfolio is not None
        assert latest is not None
        assert portfolio.cash_balance == Decimal("1439.0000")
        assert latest.quantity == Decimal("6.00000000")
        assert latest.average_cost == Decimal("100.000000")

    with session_factory.begin() as session:
        with pytest.raises(ValueError, match="exceeds the recorded position"):
            PortfolioManagementRepository(session).apply_trade_to_current_snapshot(
                portfolio_id=1,
                stock_id=1,
                as_of_date=datetime(2026, 8, 4, tzinfo=UTC).date(),
                transaction_type="sell",
                quantity=Decimal("7"),
                unit_price=Decimal("110"),
                fee_amount=Decimal("0"),
                currency="USD",
            )
