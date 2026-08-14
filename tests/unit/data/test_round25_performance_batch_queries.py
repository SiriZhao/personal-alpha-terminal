"""ROUND25 PHASE 13: N+1 query-count regression tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.models import Base, Price, Stock


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed(engine) -> None:
    with Session(engine) as session:
        stocks = [
            Stock(
                symbol=symbol,
                name=symbol,
                market="US",
                exchange="XNYS",
                currency="USD",
                timezone="America/New_York",
                canonical_code=symbol,
                available_time=datetime(2026, 8, 1, tzinfo=UTC),
            )
            for symbol in ("AAA", "BBB", "CCC")
        ]
        session.add_all(stocks)
        session.flush()
        timestamps = daily_bar_timestamps(date(2026, 7, 1), "US")
        for stock in stocks:
            for offset in range(5):
                trade_date = date(2026, 6, 29) + timedelta(days=offset)
                session.add(
                    Price(
                        stock=stock,
                        trade_date=trade_date,
                        open=100.0,
                        high=101.0,
                        low=99.0,
                        close=100.0 + offset,
                        adjusted_close=100.0 + offset,
                        adjustment_method="point_in_time_total_return",
                        volume=1000,
                        source="test-provider",
                        event_time=timestamps.event_time,
                        available_time=timestamps.available_time,
                        ingested_at=timestamps.ingested_time,
                    )
                )
        session.commit()


def test_batch_bounds_is_single_query() -> None:
    engine = _engine()
    _seed(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    counts: list[int] = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(_conn, _cursor, _statement, _parameters, _context, _many):  # noqa: ANN001
        counts.append(1)

    with factory() as session:
        repository = PriceRepository(session)
        ids = [stock.id for stock in session.query(Stock).all()]
        before = len(counts)
        bounds = repository.price_date_bounds_batch(ids, "test-provider")
        statements = len(counts) - before
        assert statements == 1
        assert len(bounds) == 3
        assert all(bounds[stock_id][1] is not None for stock_id in ids)


def test_per_symbol_bounds_would_scale_linearly() -> None:
    """Document the regression: the old per-symbol path is O(N) queries."""

    engine = _engine()
    _seed(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    counts: list[int] = []

    @event.listens_for(engine, "before_cursor_execute")
    def count(_conn, _cursor, _statement, _parameters, _context, _many):  # noqa: ANN001
        counts.append(1)

    with factory() as session:
        repository = PriceRepository(session)
        ids = [stock.id for stock in session.query(Stock).all()]
        before = len(counts)
        for stock_id in ids:
            repository.price_date_bounds(stock_id, "test-provider")
        statements = len(counts) - before
        assert statements == 3  # one query per symbol (the N+1 we eliminated)
