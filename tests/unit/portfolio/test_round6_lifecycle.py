"""ROUND 6: live lifecycle unit tests (actions, fill gates, PnL, attribution)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.manual_execution_service import (
    ManualExecutionOrderService,
    ManualFillSubmission,
)
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.models import (
    Base,
    CorporateAction,
    Portfolio,
    PortfolioPosition,
    PortfolioTransaction,
    Price,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    Stock,
)
from personal_alpha_terminal.portfolio.lifecycle import (
    DailyAttribution,
    FillGateDecision,
    PortfolioLifecycleService,
    PositionReconciliation,
    evaluate_fill_gate,
    semantic_action,
)

DECISION = datetime(2026, 8, 12, 12, tzinfo=UTC)
EARLIEST = datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
EXPIRY = datetime(2026, 8, 20, 13, 30, tzinfo=UTC)


def _seed(session: Session, *, cash: Decimal = Decimal("100000")):
    portfolio = Portfolio(
        name="LIFECYCLE TEST", base_currency="USD", cash_balance=cash
    )
    stock = Stock(
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
        available_time=DECISION - timedelta(days=400),
        ingested_time=DECISION - timedelta(days=400),
    )
    session.add_all((portfolio, stock))
    session.flush()
    for day_index, price in enumerate((100.0, 101.0, 102.0)):
        trade_date = date(2026, 8, 10) + timedelta(days=day_index)
        session.add(
            Price(
                stock_id=stock.id,
                trade_date=trade_date,
                open=Decimal(str(price)),
                high=Decimal(str(price)),
                low=Decimal(str(price)),
                close=Decimal(str(price)),
                volume=1_000_000,
                asset_type="stock",
                volume_unit="share",
                price_type="unadjusted_ohlcv",
                source="fixture",
                provider="fixture",
                event_time=datetime.combine(trade_date, datetime.min.time(), tzinfo=UTC)
                + timedelta(hours=20),
                available_time=datetime.combine(trade_date, datetime.min.time(), tzinfo=UTC)
                + timedelta(hours=20),
            )
        )
    run = QuantDecisionRun(
        portfolio_id=portfolio.id,
        as_of_time=DECISION,
        status="generated",
        gate_status="APPROVED",
        authorization_id="auth",
        data_version="dv1",
        model_version="m1",
        input_fingerprint="fp1",
        source_ids=["s"],
        blockers=[],
    )
    session.add(run)
    session.flush()
    session.flush()
    return portfolio, stock, run


def _recommendation(
    session: Session,
    run: QuantDecisionRun,
    stock: Stock,
    *,
    action: str = "BUY",
    current_weight: float = 0.0,
    target_weight: float = 0.1,
    suggested_shares: int = 100,
) -> QuantDecisionRecommendation:
    rec = QuantDecisionRecommendation(
        recommendation_id=f"rec-{run.id}-{stock.symbol}",
        run_id=run.id,
        stock_id=stock.id,
        action=action,
        current_weight=Decimal(str(current_weight)),
        target_weight=Decimal(str(target_weight)),
        quant_score=Decimal("60"),
        confidence_score=Decimal("70"),
        component_scores={"estimated_cost": 2.0, "expected_alpha": 0.02, "risk_contribution": 0.1},
        rationale=["fixture"],
        risk_factors=[],
        evidence_grade="MODEL_APPROVED",
        sample_size=100,
        source_ids=["s"],
        reference_price=Decimal("100"),
        suggested_shares=suggested_shares,
        earliest_execution_time=EARLIEST,
        expires_at=EXPIRY,
        review_status="accepted",
    )
    session.add(rec)
    session.flush()
    return rec


def test_semantic_action_maps_full_sell_to_exit_and_no_action() -> None:
    assert semantic_action("SELL", current_weight=0.1, target_weight=0.0) == "EXIT"
    assert semantic_action("SELL", current_weight=0.1, target_weight=0.05) == "SELL"
    assert semantic_action("BUY", current_weight=0.0, target_weight=0.1) == "BUY"
    assert semantic_action("ADD", current_weight=0.1, target_weight=0.2) == "ADD"
    assert semantic_action("REDUCE", current_weight=0.2, target_weight=0.1) == "REDUCE"
    assert semantic_action("HOLD", current_weight=0.1, target_weight=0.1) == "HOLD"
    assert semantic_action("UNKNOWN", current_weight=0.1, target_weight=0.1) == "NO_ACTION"


def test_fill_gate_allows_invalidity_fill() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _portfolio, stock, run = _seed(session)
            rec = _recommendation(session, run, stock)
            gate = evaluate_fill_gate(
                rec, executed_at=EARLIEST + timedelta(days=1), latest_approved_run_id=run.id
            )
            assert gate.decision is FillGateDecision.ALLOWED
    finally:
        engine.dispose()


def test_fill_gate_blocks_expired_without_override_and_allows_with_override() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _portfolio, stock, run = _seed(session)
            rec = _recommendation(session, run, stock)
            blocked = evaluate_fill_gate(
                rec, executed_at=EXPIRY + timedelta(days=1), latest_approved_run_id=run.id
            )
            assert blocked.decision is FillGateDecision.BLOCKED_EXPIRED
            assert blocked.override_required
            allowed = evaluate_fill_gate(
                rec,
                executed_at=EXPIRY + timedelta(days=1),
                latest_approved_run_id=run.id,
                override_provenance="USER:manual:schwab-confirmed-after-expiry",
            )
            assert allowed.decision is FillGateDecision.ALLOWED_WITH_OVERRIDE
    finally:
        engine.dispose()


def test_fill_gate_blocks_stale_recommendation() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _portfolio, stock, run = _seed(session)
            rec = _recommendation(session, run, stock)
            stale = evaluate_fill_gate(
                rec, executed_at=EARLIEST + timedelta(days=1), latest_approved_run_id=run.id + 5
            )
            assert stale.decision is FillGateDecision.BLOCKED_STALE
            allowed = evaluate_fill_gate(
                rec,
                executed_at=EARLIEST + timedelta(days=1),
                latest_approved_run_id=run.id + 5,
                override_provenance="USER:manual:stale-run-accepted",
            )
            assert allowed.decision is FillGateDecision.ALLOWED_WITH_OVERRIDE
    finally:
        engine.dispose()


def test_expired_fill_is_blocked_in_record_fill_without_override() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            _portfolio, stock, run = _seed(session)
            rec = _recommendation(session, run, stock)
            service = ManualExecutionOrderService(session)
            with pytest.raises(ValueError, match="manual fill blocked"):
                service.record_fill(
                    ManualFillSubmission(
                        fill_id="fill-expired",
                        recommendation_id=rec.recommendation_id,
                        quantity=10,
                        price=100.0,
                        fee=1.0,
                        executed_at=EXPIRY + timedelta(days=1),
                    )
                )
    finally:
        engine.dispose()


def test_pnl_reports_cost_basis_unrealized_realized_and_nav() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            portfolio, stock, _run = _seed(session, cash=Decimal("100000"))
            # Buy 10 @ 100 + fee 5 -> avg cost 100.5; later price 102
            session.add(
                PortfolioPosition(
                    portfolio_id=portfolio.id,
                    stock_id=stock.id,
                    as_of_date=date(2026, 8, 11),
                    quantity=Decimal("10"),
                    average_cost=Decimal("100.5"),
                )
            )
            session.add(
                PortfolioTransaction(
                    portfolio_id=portfolio.id,
                    stock_id=stock.id,
                    transaction_type="buy",
                    trade_date=date(2026, 8, 11),
                    settlement_date=date(2026, 8, 13),
                    quantity=Decimal("10"),
                    unit_price=Decimal("100"),
                    fee_amount=Decimal("5"),
                    currency="USD",
                    fx_rate_to_base=Decimal("1"),
                    source="fixture",
                    external_id="buy-1",
                    notes=None,
                    event_time=EARLIEST,
                    available_time=EARLIEST,
                )
            )
            # Sell 4 @ 105 - fee 2 on 2026-08-12
            session.add(
                PortfolioTransaction(
                    portfolio_id=portfolio.id,
                    stock_id=stock.id,
                    transaction_type="sell",
                    trade_date=date(2026, 8, 12),
                    settlement_date=date(2026, 8, 14),
                    quantity=Decimal("4"),
                    unit_price=Decimal("105"),
                    fee_amount=Decimal("2"),
                    currency="USD",
                    fx_rate_to_base=Decimal("1"),
                    source="fixture",
                    external_id="sell-1",
                    notes=None,
                    event_time=datetime(2026, 8, 12, 14, tzinfo=UTC),
                    available_time=datetime(2026, 8, 12, 14, tzinfo=UTC),
                )
            )
            session.flush()
            service = PortfolioLifecycleService(session)
            # At 2026-08-12 15:00 UTC the latest PIT-available close is 101
            # (the 08-12 bar is available only at 20:30 UTC).  The fixture keeps
            # the cash balance at 100000 and the position snapshot at 10 shares;
            # realized P&L is read from the immutable sell ledger separately.
            pnl = service.portfolio_pnl(portfolio.id, as_of=datetime(2026, 8, 12, 15, tzinfo=UTC))
            assert pnl.nav == pytest.approx(100000 + 10 * 101)
            assert pnl.unrealized_pnl == pytest.approx(10 * 101 - 10 * 100.5)
            # realized: proceeds 4*105 - 2 = 418 ; allocated 4*100.5 = 402 -> +16
            assert pnl.realized_pnl == pytest.approx(16.0)
            assert pnl.cash == pytest.approx(100000.0)
            position = pnl.positions[0]
            assert position.symbol == "AAPL"
            assert position.quantity == 10
            assert position.average_cost == pytest.approx(100.5)
            assert position.market_price == pytest.approx(101.0)
    finally:
        engine.dispose()


def test_daily_attribution_decomposes_pnl() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            portfolio, stock, _run = _seed(session, cash=Decimal("100000"))
            session.add(
                PortfolioPosition(
                    portfolio_id=portfolio.id,
                    stock_id=stock.id,
                    as_of_date=date(2026, 8, 11),
                    quantity=Decimal("10"),
                    average_cost=Decimal("100"),
                )
            )
            session.flush()
            service = PortfolioLifecycleService(session)
            attribution = service.daily_attribution(
                portfolio.id,
                as_of=datetime(2026, 8, 12, 15, tzinfo=UTC),
                previous_as_of=datetime(2026, 8, 11, 15, tzinfo=UTC),
                benchmark_return=0.005,
            )
            assert isinstance(attribution, DailyAttribution)
            assert attribution.beginning_nav is not None
            assert attribution.ending_nav > 0
            assert attribution.total_pnl is not None
            assert attribution.fees == 0.0
            assert attribution.trading_pnl == pytest.approx(0.0)
    finally:
        engine.dispose()


def test_corporate_action_reconciliation_flags_unreconciled_split() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            portfolio, stock, _run = _seed(session)
            session.add(
                PortfolioPosition(
                    portfolio_id=portfolio.id,
                    stock_id=stock.id,
                    as_of_date=date(2026, 8, 10),
                    quantity=Decimal("10"),
                    average_cost=Decimal("100"),
                )
            )
            session.add(
                CorporateAction(
                    stock_id=stock.id,
                    action_id="split-1",
                    revision_id="r1",
                    action_type="split",
                    effective_date=date(2026, 8, 11),
                    announcement_date=date(2026, 8, 1),
                    available_date=date(2026, 8, 1),
                    event_time=DECISION,
                    available_time=DECISION,
                    ingested_time=DECISION,
                    split_ratio=Decimal("2"),
                    source="fixture",
                    provider="fixture",
                    details={},
                )
            )
            session.flush()
            service = PortfolioLifecycleService(session)
            reconciliations = service.corporate_action_reconciliation(
                portfolio.id, as_of=datetime(2026, 8, 12, 15, tzinfo=UTC)
            )
            assert reconciliations
            entry = reconciliations[0]
            assert isinstance(entry, PositionReconciliation)
            assert entry.status == "RECONCILIATION_REQUIRED"
            assert entry.actions[0]["action_type"] == "split"
    finally:
        engine.dispose()
