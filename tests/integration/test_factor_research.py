from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.analysis.factors.service import FactorResearchService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    FactorResearchRun,
    FactorScore,
    FundamentalVintage,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


def add_factor_stock(session: Session, rank: int) -> Stock:
    symbol = f"S{rank}"
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    session.flush()
    close = 100.0
    daily_return = 0.004 - rank * 0.0008
    for index in range(120):
        close *= 1 + daily_return + ((index % 3) - 1) / 10000
        trade_date = date(2025, 1, 1) + timedelta(days=index)
        value = Decimal(str(close))
        session.add(
            Price(
                stock=stock,
                trade_date=trade_date,
                open=value,
                high=value,
                low=value,
                close=value,
                adjusted_close=value,
                adjustment_method="point_in_time_total_return",
                volume=1_000_000,
                source="yahoo_finance",
            )
        )
    for year, available_year, revenue, eps in (
        (2023, 2024, 100.0, 2.0),
        (2024, 2025, 100.0 * (1.3 - rank * 0.04), 2.0 * (1.3 - rank * 0.04)),
    ):
        available_at = datetime(available_year, 1, 15, tzinfo=UTC)
        session.add(FundamentalVintage(
            stock_id=stock.id,
            fiscal_period_end=date(year, 12, 31),
            period_type="annual",
            filing_id=f"{symbol}-{year}-10K",
            filing_date=date(available_year, 1, 15),
            publication_time=available_at,
            available_at=available_at,
            revision_id="original",
            is_restatement=False,
            original_values={
                "revenue": revenue,
                "free_cash_flow": 20 - rank,
                "roe": 0.25 - rank * 0.03,
                "roic": 0.22 - rank * 0.03,
                "pe": 10 + rank * 4,
                "pb": 1.5 + rank * 0.4,
                "diluted_eps": eps,
                "shares_outstanding": 10,
            },
            restated_values=None,
            currency="USD",
            unit_scale=1,
            accounting_standard="US_GAAP",
            source="test",
            provider="deterministic_fixture",
            ingested_at=available_at,
        ))
    return stock


def add_universe_snapshot(
    session: Session, stocks: list[Stock], as_of_date: date
) -> MarketUniverseSnapshot:
    snapshot = MarketUniverseSnapshot(
        market="US",
        as_of_date=as_of_date,
        source="fixture",
        provider="deterministic_fixture",
        available_time=datetime.combine(as_of_date, datetime.min.time(), UTC),
        ingested_time=datetime.combine(as_of_date, datetime.min.time(), UTC),
    )
    snapshot.members.extend(
        MarketUniverseMember(
            stock_id=stock.id,
            segment="test",
            size_bucket="large",
            listing_age_bucket="seasoned",
            market_cap=None,
            reason="PIT test universe",
        )
        for stock in stocks
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def test_factor_snapshot_is_point_in_time_and_legacy_backtest_is_blocked(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stocks = [add_factor_stock(session, rank) for rank in range(5)]
        session.flush()
        universe = add_universe_snapshot(session, stocks, date(2025, 3, 14))
        session.commit()
        settings = Settings(
            _env_file=None,
            factor_momentum_lookback=20,
            factor_momentum_skip=2,
            factor_volatility_window=10,
            factor_minimum_categories=3,
            factor_minimum_scored_stocks=3,
            factor_maximum_universe_size=10,
            factor_selection_quantile=0.4,
            factor_rebalance_interval=10,
            factor_holding_period=10,
        )
        service = FactorResearchService(FactorResearchRepository(session), settings)
        snapshot = service.run_snapshot(
            market="US",
            as_of_date=date(2025, 3, 15),
            universe_snapshot_id=universe.id,
        )
        with pytest.raises(ValueError, match="legacy close-to-close"):
            service.run_backtest(
                market="US",
                start_date=date(2025, 2, 15),
                end_date=date(2025, 4, 20),
            )
        session.commit()

        assert len(snapshot.scores) == 5
        assert snapshot.scores[0].instrument.id == stocks[0].id
        assert session.scalar(select(func.count(FactorResearchRun.id))) == 1
        assert session.scalar(select(func.count(FactorScore.id))) == 5

        restored_snapshot = service.latest_snapshot()
        restored_backtest = service.latest_backtest()
        assert restored_snapshot is not None
        assert restored_snapshot.scores[0].instrument.id == stocks[0].id
        assert restored_backtest is None


def test_factor_research_rejects_provider_current_snapshot_adjustment(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = add_factor_stock(session, 0)
        session.flush()
        price = session.scalar(select(Price).where(Price.stock == stock))
        assert price is not None
        price.adjustment_method = "yahoo_provider_total_return_current_snapshot"
        universe = add_universe_snapshot(session, [stock], date(2025, 4, 29))
        session.commit()

        with pytest.raises(ValueError, match="leak later corporate actions"):
            FactorResearchRepository(session).load_dataset(
                market="US",
                query_start_date=date(2025, 1, 1),
                end_date=date(2025, 4, 30),
                include_inactive=True,
                maximum_universe_size=10,
                universe_snapshot_id=universe.id,
            )


def test_financial_timestamp_inversion_blocks_factor_dataset(
    session_factory: sessionmaker[Session],
) -> None:
    # Financial facts may not be used if the recorded ingestion predates
    # public availability; this indicates corrupted provenance.
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:TEST:BADTIME",
            symbol="BADTIME",
            name="Bad timestamp",
            market="US",
            exchange="TEST",
            currency="USD",
            timezone="America/New_York",
        )
        session.add(stock)
        session.flush()
        session.add(
            FundamentalVintage(
                stock_id=stock.id,
                fiscal_period_end=date(2025, 12, 31),
                period_type="annual",
                filing_id="BADTIME-2025-10K",
                filing_date=date(2026, 2, 1),
                publication_time=datetime(2026, 2, 1, tzinfo=UTC),
                available_at=datetime(2026, 2, 1, tzinfo=UTC),
                revision_id="original",
                is_restatement=False,
                original_values={},
                restated_values=None,
                currency="USD",
                unit_scale=1,
                accounting_standard="US_GAAP",
                ingested_at=datetime(2026, 1, 31, tzinfo=UTC),
                source="filing_fixture",
                provider="deterministic_fixture",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
