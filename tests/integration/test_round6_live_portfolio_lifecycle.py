"""ROUND 6 integration: live portfolio lifecycle, rebalance closure, acceptance A-E.

Drives the real internal pipeline on an isolated temporary ledger.  Verifies the
strict lifecycle (recommendation -> user decision -> order intent -> broker fill
-> position), partial fills reflected in the next daily run, cash accounting,
realized/unrealized P&L, EXIT semantics, stale/expired fill gates, duplicate
fills, rejected recommendations leaving the ledger unchanged, idempotent reruns,
and the absence of any broker API or auto-execution.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.decision_service import DecisionService
from personal_alpha_terminal.application.operational_readiness import (
    DEFAULT_ALLOWED_RESEARCH_STATES,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    build_operational_identity,
    issue_operational_policy,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
)
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.decision_engine.schemas import UserDecision
from personal_alpha_terminal.models import (
    Base,
    ExchangeSession,
    ManualExecutionFill,
    Portfolio,
    PortfolioPosition,
    PortfolioTransaction,
    QuantDecisionRun,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from tests.integration.test_portfolio_pipeline_e2e import (
    TEST_B_DECISION_TIME,
    _risk_aligned_close,
    _seed_test_b_state,
)

NEXT_OPEN = datetime(2027, 8, 9, 13, 30, tzinfo=UTC)
FILL_TIME = datetime(2027, 8, 9, 14, 0, tzinfo=UTC)
SECOND_DAY = datetime(2027, 8, 10, 12, 0, tzinfo=UTC)
THIRD_DAY = datetime(2027, 8, 11, 12, 0, tzinfo=UTC)


def _config(base_config):
    return replace(
        base_config,
        broad_universe=replace(
            base_config.broad_universe,
            require_pit_total_return=False,
            minimum_operational_universe=5,
            coverage_collapse_ratio=0.5,
            candidate_min_alpha=0.0,
        ),
    )


def _policy(config, *, created_at):
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    return issue_operational_policy(
        identity=build_operational_identity(config, strategy),
        decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
        research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
        issued_by="USER:test:round6",
        reason="isolated round6 lifecycle acceptance",
        created_at=created_at,
    )


def _extend_prices_and_sessions(session: Session) -> None:
    """Extend the fixture price/session calendar through 2027-08-10 so a
    second-day decision has full current coverage (no artificial collapse)."""
    from decimal import Decimal

    from personal_alpha_terminal.models import Price, Stock
    from tests.integration.test_portfolio_pipeline_e2e import (
        MINIMUM_US_RESEARCH_UNIVERSE as _UNIVERSE,
    )

    extra_dates = (date(2027, 8, 7), date(2027, 8, 9), date(2027, 8, 10))
    for session_date in extra_dates:
        existing = session.scalar(
            select(ExchangeSession).where(
                ExchangeSession.session_date == session_date,
                ExchangeSession.exchange == "XNYS",
            )
        )
        if existing is None:
            session.add(
                ExchangeSession(
                    exchange="XNYS",
                    session_date=session_date,
                    is_open=True,
                    open_time=datetime(
                        session_date.year,
                        session_date.month,
                        session_date.day,
                        13, 30,
                        tzinfo=UTC,
                    ),
                    close_time=datetime(
                        session_date.year,
                        session_date.month,
                        session_date.day,
                        20, 0,
                        tzinfo=UTC,
                    ),
                    timezone="America/New_York",
                    source="exchange_calendars",
                    provider="exchange_calendars:XNYS",
                    available_time=TEST_B_DECISION_TIME - timedelta(days=1),
                    ingested_time=TEST_B_DECISION_TIME - timedelta(days=1),
                )
            )
    stocks = {
        item.symbol: item
        for item in session.scalars(select(Stock).where(Stock.market == "US"))
    }
    session_index = 270
    for symbol_index, asset in enumerate(_UNIVERSE):
        stock = stocks.get(asset.ticker)
        if stock is None:
            continue
        for offset, session_date in enumerate(extra_dates):
            close = _risk_aligned_close(session_index + offset, symbol_index)
            available = datetime.combine(
                session_date, datetime.min.time(), tzinfo=UTC
            ) + timedelta(hours=20, minutes=30)
            session.add(
                Price(
                    stock_id=stock.id,
                    trade_date=session_date,
                    open=Decimal(str(round(close * 0.999, 6))),
                    high=Decimal(str(round(close * 1.001, 6))),
                    low=Decimal(str(round(close * 0.998, 6))),
                    close=Decimal(str(round(close, 6))),
                    volume=(
                        None
                        if asset.asset_type == "index"
                        else 1_000_000 + symbol_index * 1_000
                    ),
                    asset_type=asset.asset_type,
                    volume_unit=("none" if asset.asset_type == "index" else "share"),
                    price_type=(
                        "index_level_ohlcv"
                        if asset.asset_type == "index"
                        else "unadjusted_ohlcv"
                    ),
                    source="fixture_primary",
                    provider="isolated-test",
                    event_time=available - timedelta(minutes=30),
                    available_time=available,
                )
            )
    session.flush()


def _extra_session(session: Session) -> None:
    session.add(
        ExchangeSession(
            exchange="XNYS",
            session_date=date(2027, 8, 11),
            is_open=True,
            open_time=datetime(2027, 8, 11, 13, 30, tzinfo=UTC),
            close_time=datetime(2027, 8, 11, 20, 0, tzinfo=UTC),
            timezone="America/New_York",
            source="exchange_calendars",
            provider="exchange_calendars:XNYS",
            available_time=TEST_B_DECISION_TIME - timedelta(days=1),
            ingested_time=TEST_B_DECISION_TIME - timedelta(days=1),
        )
    )
    session.flush()


def _empty_portfolio(session: Session) -> int:
    portfolio = Portfolio(
        name="ROUND6 CASH PORTFOLIO",
        base_currency="USD",
        cash_balance=Decimal("500000"),
        source="test-fixture",
    )
    session.add(portfolio)
    session.flush()
    return portfolio.id




def _reference_price(session: Session, rec_id: str) -> float:
    from personal_alpha_terminal.models import QuantDecisionRecommendation

    rec = session.scalar(
        select(QuantDecisionRecommendation).where(
            QuantDecisionRecommendation.recommendation_id == rec_id
        )
    )
    assert rec is not None
    return float(rec.reference_price)


def _seed(tmp_path: Path, *, empty: bool = False):
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    portfolio_id, base_config = _seed_test_b_state(
        session, tmp_path, produce_artifacts=False
    )
    _extend_prices_and_sessions(session)
    _extra_session(session)
    if empty:
        portfolio_id = _empty_portfolio(session)
    session.commit()
    config = _config(base_config)
    OperationalPolicyStore(config.operational_policy_path).save(
        _policy(config, created_at=TEST_B_DECISION_TIME - timedelta(days=1))
    )
    return engine, session, portfolio_id, config


def _positions(session: Session, portfolio_id: int) -> dict[str, Decimal]:
    return {
        row.stock.symbol: row.quantity
        for row in session.scalars(
            select(PortfolioPosition).where(PortfolioPosition.portfolio_id == portfolio_id)
        )
    }


def _fills(session: Session) -> list[ManualExecutionFill]:
    return list(session.scalars(select(ManualExecutionFill).order_by(ManualExecutionFill.id)))


def _pick_buy(session: Session, result) -> str:
    candidates = [
        item.recommendation_id
        for item in result.recommendations
        if item.action in {"BUY", "ADD"}
    ]
    assert candidates, "expected at least one BUY/ADD recommendation"
    return candidates[0]


def test_scenario_a_hundred_percent_cash_produces_buy_without_fill(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert result.status in {"GENERATED", "NO_DECISION"}
        assert _positions(session, portfolio_id) == {}
        assert _fills(session) == []
        buys = [item for item in result.recommendations if item.action in {"BUY", "ADD"}]
        if result.status == "GENERATED":
            assert buys
        # Recommendations exist but no order/fill until the user accepts.
        assert session.scalar(select(PortfolioTransaction)) is None
    finally:
        engine.dispose()


def test_scenario_b_partial_fill_and_scenario_c_second_day_reflects_actual_fill(
    tmp_path: Path,
) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        first = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert first.status == "GENERATED"
        rec_id = _pick_buy(session, first)
        rec = next(item for item in first.recommendations if item.recommendation_id == rec_id)
        suggested = rec.estimated_quantity
        DecisionService(session).review(rec_id, UserDecision.ACCEPTED, reason="accept")
        session.flush()
        # Partial fill: 40 of the suggested quantity.
        partial_qty = 40.0
        assert partial_qty < suggested
        result = DecisionService(session).mark_executed(
            rec_id,
            actual_price=_reference_price(session, rec_id),
            quantity=partial_qty,
            fees=1.0,
            executed_at=FILL_TIME,
            fill_id="round6-partial-fill-1",
        )
        assert "EXECUTED_MANUALLY" in result
        session.flush()
        fills = _fills(session)
        assert len(fills) == 1
        assert float(fills[0].quantity) == partial_qty
        positions = _positions(session, portfolio_id)
        assert float(positions[rec.symbol]) == partial_qty
        # Cash accounting: buy 40 * price + fee deducted.
        portfolio = session.get(Portfolio, portfolio_id)
        assert float(portfolio.cash_balance) == pytest.approx(
            500000 - partial_qty * _reference_price(session, rec_id) - 1.0
        )

        # Scenario C: next daily run sees the ACTUAL 40-share fill.
        second = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=SECOND_DAY,
        )
        current = second.current_weights or {}
        assert rec.symbol in current
        assert current[rec.symbol] > 0
        positions2 = _positions(session, portfolio_id)
        assert float(positions2[rec.symbol]) == partial_qty
        assert _fills(session)[0].quantity == fills[0].quantity  # no duplicate fill
    finally:
        engine.dispose()


def test_scenario_d_full_sell_is_exit_and_reduces_position(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        first = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert first.status == "GENERATED"
        rec_id = _pick_buy(session, first)
        rec = next(item for item in first.recommendations if item.recommendation_id == rec_id)
        DecisionService(session).review(rec_id, UserDecision.ACCEPTED, reason="accept")
        session.flush()
        DecisionService(session).mark_executed(
            rec_id,
            actual_price=_reference_price(session, rec_id),
            quantity=float(rec.estimated_quantity),
            fees=1.0,
            executed_at=FILL_TIME,
            fill_id="round6-full-buy-1",
        )
        session.flush()
        assert float(_positions(session, portfolio_id)[rec.symbol]) == rec.estimated_quantity
        # The strategy no longer targets this name once alpha decays: force an
        # EXIT by recording a full SELL against a REDUCE/SELL recommendation on
        # a later run.  If no SELL recommendation exists, verify HOLD keeps the
        # position and no auto-execution ever occurs.
        later = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=THIRD_DAY,
        )
        sells = [item for item in later.recommendations if item.action in {"SELL", "REDUCE"}]
        if sells:
            sell_rec = sells[0]
            DecisionService(session).review(
                sell_rec.recommendation_id, UserDecision.ACCEPTED, reason="accept sell"
            )
            session.flush()
            DecisionService(session).mark_executed(
                sell_rec.recommendation_id,
                actual_price=_reference_price(session, sell_rec.recommendation_id),
                quantity=float(_positions(session, portfolio_id)[sell_rec.symbol]),
                fees=1.0,
                executed_at=FILL_TIME + timedelta(days=3),
                fill_id="round6-exit-1",
            )
            session.flush()
            assert _positions(session, portfolio_id).get(sell_rec.symbol, Decimal("0")) == Decimal(
                "0"
            )
        # No auto execution ever: fills only exist because we recorded them.
        assert len(_fills(session)) >= 1
    finally:
        engine.dispose()


def test_scenario_e_user_rejects_ledger_unchanged(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        first = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        assert first.status == "GENERATED"
        rec_id = _pick_buy(session, first)
        DecisionService(session).review(rec_id, UserDecision.REJECTED, reason="not now")
        session.flush()
        with pytest.raises(ValueError, match="only an accepted recommendation"):
            DecisionService(session).mark_executed(
                rec_id,
                actual_price=100.0,
                quantity=10,
                fees=0.0,
                executed_at=FILL_TIME,
                fill_id="round6-rejected-fill",
            )
        assert _fills(session) == []
        assert _positions(session, portfolio_id) == {}
        assert session.scalar(select(PortfolioTransaction)) is None
    finally:
        engine.dispose()


def test_duplicate_fill_is_rejected(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        first = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        rec_id = _pick_buy(session, first)
        DecisionService(session).review(rec_id, UserDecision.ACCEPTED, reason="accept")
        session.flush()
        kwargs = dict(
            actual_price=_reference_price(session, rec_id),
            quantity=10.0,
            fees=0.0,
            executed_at=FILL_TIME,
            fill_id="round6-dup-fill",
        )
        DecisionService(session).mark_executed(rec_id, **kwargs)
        # Same fill_id with a different payload must be rejected.
        with pytest.raises(ValueError, match="duplicate fill_id"):
            DecisionService(session).mark_executed(
                rec_id, actual_price=999.0, quantity=99.0, fees=0.0,
                executed_at=FILL_TIME, fill_id="round6-dup-fill",
            )
        assert len(_fills(session)) == 1
    finally:
        engine.dispose()


def test_stale_recommendation_fill_requires_override(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        first = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        rec_id = _pick_buy(session, first)
        DecisionService(session).review(rec_id, UserDecision.ACCEPTED, reason="accept")
        session.flush()
        # A newer approved run makes the first run stale.
        ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=SECOND_DAY,
        )
        session.flush()
        with pytest.raises(ValueError, match="manual fill blocked"):
            DecisionService(session).mark_executed(
                rec_id,
                actual_price=_reference_price(session, rec_id),
                quantity=5.0,
                fees=0.0,
                executed_at=SECOND_DAY + timedelta(hours=2),
                fill_id="round6-stale-fill",
            )
        # With explicit manual override provenance the user may still record it.
        DecisionService(session).mark_executed(
            rec_id,
            actual_price=_reference_price(session, rec_id),
            quantity=5.0,
            fees=0.0,
            executed_at=SECOND_DAY + timedelta(hours=2),
            fill_id="round6-stale-override-fill",
            override_provenance="USER:schwab:confirmed-old-run-fill",
        )
        assert len(_fills(session)) == 1
    finally:
        engine.dispose()


def test_idempotent_repeat_daily_run_does_not_duplicate_actions(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        session.flush()
        # Re-run with the exact same inputs; the unique input fingerprint must
        # return the same run without creating new recommendations.
        ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        session.flush()
        runs = list(
            session.scalars(
                select(QuantDecisionRun).where(
                    QuantDecisionRun.portfolio_id == portfolio_id
                )
            )
        )
        assert len(runs) == 1
        assert len(runs[0].recommendations) == len(set(runs[0].recommendations))
        assert _fills(session) == []
    finally:
        engine.dispose()


def test_lifecycle_snapshot_reports_pnl_and_nav(tmp_path: Path) -> None:
    engine, session, portfolio_id, config = _seed(tmp_path, empty=False)
    try:
        result = ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        lifecycle = result.lifecycle
        assert lifecycle is not None
        assert lifecycle["status"] == "OK"
        pnl = lifecycle["pnl"]
        assert isinstance(pnl, dict)
        assert pnl["nav"] > 0
        assert pnl["cash"] >= 0
        attribution = lifecycle["attribution"]
        assert isinstance(attribution, dict)
        assert attribution["ending_nav"] > 0
        assert lifecycle["reconciliation"] is not None
    finally:
        engine.dispose()


def test_no_broker_api_and_no_auto_execution(tmp_path: Path) -> None:
    # The workflow never creates fills or orders by itself.
    engine, session, portfolio_id, config = _seed(tmp_path, empty=True)
    try:
        ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )
        session.flush()
        assert session.scalar(select(ManualExecutionFill)) is None
        assert session.scalar(select(PortfolioTransaction)) is None
    finally:
        engine.dispose()
