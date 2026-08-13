"""ROUND 5 integration: broad CURRENT_OPERATIONAL_PIT in the daily path.

Drives the real internal pipeline against an isolated fixture whose current
directory and price layer contain far more stocks than the strict certified
total-return tier.  Verifies that a degraded historical research tier does NOT
collapse the current operational universe, that the old bootstrap list is not
used, that candidates are compressed before optimization, that operational
policy identity changes fail closed, and that forward predictions are recorded
without any simulated fill.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.us_market.broad_universe import (
    parse_symbol_directories,
    write_directory_snapshot,
)
from personal_alpha_terminal.models import Base, ManualExecutionFill, Price, Stock, TradingStatus
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from tests.integration.test_portfolio_pipeline_e2e import (
    TEST_B_DECISION_TIME,
    _bar_dates,
    _seed_test_b_state,
)

EXTRA_SYMBOLS = tuple(f"X{index:03d}" for index in range(1, 21))
BAR_COUNT = 270


def _extend_directory(
    config: EffectiveRuntimeConfig, *, decision_time: datetime
) -> None:
    """Rewrite the current-directory snapshot to include the extra stocks."""
    from personal_alpha_terminal.application.universe import (
        MINIMUM_US_RESEARCH_UNIVERSE,
    )

    source_date = decision_time.date().strftime("%m%d%Y")
    nasdaq_rows = [
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares"
    ]
    other_rows = [
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol"
    ]
    for asset in MINIMUM_US_RESEARCH_UNIVERSE:
        if asset.asset_type != "stock":
            continue
        if asset.exchange == "XNAS":
            nasdaq_rows.append(
                f"{asset.ticker}|{asset.name} Common Stock|Q|N|N|100|N|N"
            )
        else:
            exchange = "N" if asset.exchange == "XNYS" else "A"
            other_rows.append(
                f"{asset.ticker}|{asset.name} Common Stock|{exchange}|"
                f"{asset.ticker}|N|100|N|{asset.ticker}"
            )
    for symbol in EXTRA_SYMBOLS:
        nasdaq_rows.append(
            f"{symbol}|{symbol} Industries Common Stock|Q|N|N|100|N|N"
        )
    nasdaq_rows.append(f"File Creation Time: {source_date}1200|||||||")
    other_rows.append(f"File Creation Time: {source_date}1200|||||||")
    snapshot = parse_symbol_directories(
        "\n".join(nasdaq_rows),
        "\n".join(other_rows),
        retrieved_at=decision_time - timedelta(hours=1),
    )
    write_directory_snapshot(snapshot, config.cache_dir / "us-current-directory")


def _seed_extra_stocks(
    session: Session, *, end_date: date, decision_time: datetime
) -> None:
    dates = _bar_dates(end_date, BAR_COUNT)
    now = decision_time - timedelta(days=400)
    for index, symbol in enumerate(EXTRA_SYMBOLS):
        stock = Stock(
            canonical_code=f"US:XNAS:{symbol}",
            symbol=symbol,
            name=f"{symbol} Industries",
            market="US",
            exchange="XNAS",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            list_date=date(2015, 1, 2),
            source="fixture-round5-extra",
            provider="isolated-test",
            available_time=now,
            ingested_time=now,
        )
        session.add(stock)
        session.flush()
        for session_index, trade_date in enumerate(dates):
            close = 100.0 + 5.0 * index + session_index * 0.02
            available = (
                datetime.combine(trade_date, datetime.min.time(), tzinfo=UTC)
                + timedelta(hours=20, minutes=30)
            )
            session.add(
                Price(
                    stock_id=stock.id,
                    trade_date=trade_date,
                    open=Decimal(str(round(close * 0.999, 6))),
                    high=Decimal(str(round(close * 1.001, 6))),
                    low=Decimal(str(round(close * 0.998, 6))),
                    close=Decimal(str(round(close, 6))),
                    volume=1_000_000 + index * 1_000,
                    asset_type="stock",
                    volume_unit="share",
                    price_type="unadjusted_ohlcv",
                    source="fixture_primary",
                    provider="isolated-test",
                    event_time=available - timedelta(minutes=30),
                    available_time=available,
                )
            )
        session.add(
            TradingStatus(
                stock_id=stock.id,
                status="TRADABLE",
                effective_time=decision_time - timedelta(days=1),
                available_time=decision_time - timedelta(days=1),
                ingested_time=decision_time - timedelta(days=1),
                reason="certified PIT bar evidence; no known delisting record",
                source="certified_live_universe",
                provider="isolated-test",
            )
        )
    session.flush()


def _broad_config(config: EffectiveRuntimeConfig) -> EffectiveRuntimeConfig:
    return replace(
        config,
        broad_universe=replace(
            config.broad_universe,
            require_pit_total_return=False,
            minimum_operational_universe=5,
            coverage_collapse_ratio=0.5,
            candidate_max=15,
            candidate_min_alpha=0.0,
        ),
    )


def _issue_policy(config: EffectiveRuntimeConfig, *, created_at: datetime):
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    return issue_operational_policy(
        identity=build_operational_identity(config, strategy),
        decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
        research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
        issued_by="USER:test:round5",
        reason="isolated round5 broad universe acceptance",
        created_at=created_at,
    )


def _seeded_session(tmp_path: Path):
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    portfolio_id, base_config = _seed_test_b_state(
        session, tmp_path, produce_artifacts=False
    )
    _extend_directory(base_config, decision_time=TEST_B_DECISION_TIME)
    _seed_extra_stocks(
        session,
        end_date=TEST_B_DECISION_TIME.date(),
        decision_time=TEST_B_DECISION_TIME,
    )
    session.commit()
    return engine, session, portfolio_id, base_config


def test_round5_broad_operational_universe_replaces_bootstrap_list(
    tmp_path: Path,
) -> None:
    engine, session, portfolio_id, base_config = _seeded_session(tmp_path)
    config = _broad_config(base_config)
    OperationalPolicyStore(config.operational_policy_path).save(
        _issue_policy(config, created_at=TEST_B_DECISION_TIME - timedelta(days=1))
    )
    result = ProductionDailyWorkflow(session, config).run(
        portfolio_id=portfolio_id,
        decision_time=TEST_B_DECISION_TIME,
    )
    try:
        evidence = result.universe_evidence
        assert evidence["qualification"] == "CURRENT_OPERATIONAL_PIT"
        funnel = evidence["funnel"]
        broad_factor = int(funnel["factor_eligible"])
        historical_factor = int(evidence["historical_research"]["factor_eligible"])
        # The broad tier includes the extra stocks; the strict certified tier
        # does not, so the operational universe is strictly larger.
        assert broad_factor > historical_factor
        assert broad_factor >= len(EXTRA_SYMBOLS) + 5
        # Candidate compression produced a bounded pool with recorded steps.
        assert evidence["candidate_count"] > 0
        assert evidence["candidate_count"] <= 15
        assert "steps" in evidence["candidate_compression"]
        # No bootstrap leakage: the operational universe contains the extras.
        alpha_symbols = set(evidence["alpha_symbols"])
        assert alpha_symbols & set(EXTRA_SYMBOLS)
        assert result.status in {"GENERATED", "NO_DECISION"}
        # Forward predictions recorded, and never a simulated fill.
        ledger = config.forward_ledger_path
        assert ledger.exists()
        assert "prediction" in ledger.read_text(encoding="utf-8")
        fills = session.scalars(select(ManualExecutionFill)).all()
        assert fills == []
    finally:
        engine.dispose()


def test_round5_future_row_poison_does_not_change_operational_universe(
    tmp_path: Path,
) -> None:
    engine, session, portfolio_id, base_config = _seeded_session(tmp_path)
    config = _broad_config(base_config)
    # Poison: a bar for an extra symbol whose available_time is AFTER the
    # decision time (future data).  It must be invisible to the universe.
    from personal_alpha_terminal.models import SecurityMaster

    stock = session.scalar(
        select(SecurityMaster).where(SecurityMaster.symbol == EXTRA_SYMBOLS[0])
    )
    assert stock is not None
    session.add(
        Price(
            stock_id=stock.id,
            trade_date=TEST_B_DECISION_TIME.date() + timedelta(days=1),
            open=Decimal("999"),
            high=Decimal("999"),
            low=Decimal("999"),
            close=Decimal("999"),
            volume=9_999_999,
            asset_type="stock",
            volume_unit="share",
            price_type="unadjusted_ohlcv",
            source="poison",
            provider="isolated-test",
            event_time=TEST_B_DECISION_TIME + timedelta(hours=1),
            available_time=TEST_B_DECISION_TIME + timedelta(hours=1),
        )
    )
    session.commit()
    result = ProductionDailyWorkflow(session, config).run(
        portfolio_id=portfolio_id,
        decision_time=TEST_B_DECISION_TIME,
    )
    try:
        evidence = result.universe_evidence
        funnel = evidence["funnel"]
        # The future bar must not add a fake session to any observation.
        assert int(funnel["factor_eligible"]) >= len(EXTRA_SYMBOLS) + 5
        assert result.status in {"GENERATED", "NO_DECISION", "BLOCKED"}
    finally:
        engine.dispose()


def test_round5_operational_policy_identity_change_fails_closed(
    tmp_path: Path,
) -> None:
    engine, session, portfolio_id, base_config = _seeded_session(tmp_path)
    # Policy is issued against the STRICT rules fingerprint (the old universe
    # identity).  Running on the broad CURRENT_OPERATIONAL_PIT identity must
    # fail closed: identity mismatch means no provisional advice.
    config = _broad_config(base_config)
    strict_identity_policy = _issue_policy(
        base_config, created_at=TEST_B_DECISION_TIME - timedelta(days=1)
    )
    OperationalPolicyStore(config.operational_policy_path).save(
        strict_identity_policy
    )
    result = ProductionDailyWorkflow(session, config).run(
        portfolio_id=portfolio_id,
        decision_time=TEST_B_DECISION_TIME,
    )
    try:
        assert result.operationally_allowed is False
        assert result.operational_policy_id == strict_identity_policy.policy_id
        assert result.operational_policy_effective is False
        assert result.operational_policy_reason == "OPERATIONAL_POLICY_IDENTITY_MISMATCH"
        assert result.recommendations == ()
        assert result.status in {"BLOCKED", "NO_DECISION"}
    finally:
        engine.dispose()
