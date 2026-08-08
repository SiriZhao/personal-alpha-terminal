from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.database_transfer import (
    DatabaseTransferError,
    copy_database_contents,
)
from personal_alpha_terminal.models import Base, Price, Stock


def _seed_source(session: Session) -> None:
    stock = Stock(
        canonical_code="US:XNAS:NVDA",
        symbol="NVDA",
        name="NVIDIA Corporation",
        market="US",
        exchange="XNAS",
        currency="USD",
        timezone="America/New_York",
    )
    stock.prices.append(
        Price(
            trade_date=date(2026, 7, 31),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("104"),
            adjusted_close=Decimal("104"),
            volume=1_000_000,
            source="transfer-test",
        )
    )
    session.add(stock)


def test_database_transfer_copies_and_validates_all_tables_atomically() -> None:
    source = build_engine("sqlite://")
    target = build_engine("sqlite://")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)
    try:
        with Session(source) as session:
            _seed_source(session)
            session.commit()

        result = copy_database_contents(source, target, batch_size=1)

        with target.connect() as connection:
            stock_count = connection.scalar(select(func.count()).select_from(Stock))
            price_count = connection.scalar(select(func.count()).select_from(Price))
        assert result.total_rows == 2
        assert stock_count == 1
        assert price_count == 1
        assert all(len(item.sha256) == 64 for item in result.tables)
    finally:
        source.dispose()
        target.dispose()


def test_database_transfer_refuses_nonempty_target_without_partial_copy() -> None:
    source = build_engine("sqlite://")
    target = build_engine("sqlite://")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)
    try:
        with Session(source) as session:
            _seed_source(session)
            session.commit()
        with Session(target) as session:
            session.add(
                Stock(
                    canonical_code="US:XNYS:IBM",
                    symbol="IBM",
                    name="IBM",
                    market="US",
                    exchange="XNYS",
                    currency="USD",
                    timezone="America/New_York",
                )
            )
            session.commit()

        with pytest.raises(DatabaseTransferError, match="must be empty"):
            copy_database_contents(source, target)

        with target.connect() as connection:
            symbols = set(connection.scalars(select(Stock.symbol)))
            price_count = connection.scalar(select(func.count()).select_from(Price))
        assert symbols == {"IBM"}
        assert price_count == 0
    finally:
        source.dispose()
        target.dispose()
