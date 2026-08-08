from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.market_data.capabilities import PROVIDER_CAPABILITIES
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.models import Price, ProviderCapabilityRecord, Stock


def _stock(session: Session) -> Stock:
    stock = Stock(
        canonical_code="A:SSE:600000",
        symbol="600000",
        name="contract-test",
        market="A",
        exchange="SSE",
        asset_type="stock",
        currency="CNY",
        timezone="Asia/Shanghai",
    )
    session.add(stock)
    session.flush()
    return stock


def test_capability_registry_is_persisted_without_market_data_import(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = PriceRepository(session)
        repository.sync_provider_capabilities()

        assert session.scalar(select(func.count()).select_from(ProviderCapabilityRecord)) == len(
            PROVIDER_CAPABILITIES
        )
        assert session.scalar(select(func.count()).select_from(Price)) == 0


def test_database_schema_rejects_provider_hand_unit(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = _stock(session)
        session.add(
            Price(
                stock_id=stock.id,
                trade_date=date(2026, 7, 29),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=100,
                asset_type="stock",
                volume_unit="hand",
                price_currency="CNY",
                share_unit=Decimal("1"),
                price_type="unadjusted_ohlcv",
                data_contract_version="market-data-v1",
                source="contract_test",
                provider="contract_test.stock",
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()
