from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    CalendarSession,
    CorporateActionRecord,
    CorporateActionType,
    ListingAgeBucket,
    MarketSegment,
    SizeBucket,
    UniverseCandidate,
)
from personal_alpha_terminal.models import (
    CorporateAction,
    ExchangeSession,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Stock,
)


def test_quality_input_repository_preserves_source_provider_and_timestamps(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:XNAS:TEST",
            symbol="TEST",
            name="Test",
            market="US",
            exchange="NASDAQ",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            list_date=date(2026, 1, 1),
        )
        session.add(stock)
        session.flush()
        timestamp = datetime(2026, 7, 31, 20, tzinfo=UTC)
        announced_at = datetime(2026, 7, 20, 12, tzinfo=UTC)
        repository = MarketDataQualityRepository(session)
        candidate = UniverseCandidate(
            stock_id=stock.id,
            symbol=stock.symbol,
            market="US",
            exchange=stock.exchange,
            segment=MarketSegment.NASDAQ,
            asset_type="stock",
            size_bucket=SizeBucket.MID_SMALL,
            listing_age_bucket=ListingAgeBucket.NEW,
            list_date=stock.list_date,
            delist_date=None,
            market_cap=Decimal("1000000"),
        )

        snapshot_id = repository.store_universe_snapshot(
            market="US",
            as_of_date=date(2026, 7, 31),
            source="nasdaq_trader",
            provider="symbol_directory_import",
            available_time=timestamp,
            ingested_time=timestamp,
            members=[candidate],
        )
        assert (
            repository.store_calendar_sessions(
                [
                    CalendarSession(
                        exchange="NASDAQ",
                        session_date=date(2026, 7, 31),
                        is_open=True,
                        open_time=datetime(2026, 7, 31, 13, 30, tzinfo=UTC),
                        close_time=datetime(2026, 7, 31, 20, 0, tzinfo=UTC),
                        timezone="America/New_York",
                        source="nasdaq_official",
                        provider="official_calendar_import",
                        available_time=announced_at,
                        ingested_time=timestamp,
                    )
                ]
            )
            == 1
        )
        assert (
            repository.store_corporate_actions(
                [
                    CorporateActionRecord(
                        stock_id=stock.id,
                        action_type=CorporateActionType.CASH_DIVIDEND,
                        effective_date=date(2026, 7, 31),
                        announcement_date=date(2026, 7, 20),
                        available_date=date(2026, 7, 20),
                        event_time=timestamp,
                        available_time=timestamp,
                        ingested_time=timestamp,
                        source="nasdaq_daily_list",
                        provider="official_action_import",
                        cash_amount=Decimal("0.25"),
                        currency="USD",
                    )
                ]
            )
            == 1
        )
        session.commit()

        snapshot = session.get(MarketUniverseSnapshot, snapshot_id)
        assert snapshot is not None
        assert snapshot.source == "nasdaq_trader"
        assert snapshot.provider == "symbol_directory_import"
        assert session.scalar(select(func.count()).select_from(MarketUniverseMember)) == 1
        assert session.scalar(select(func.count()).select_from(ExchangeSession)) == 1
        action = session.scalar(select(CorporateAction))
        assert action is not None
        assert action.source == "nasdaq_daily_list"
        assert action.provider == "official_action_import"


def test_snapshot_selection_respects_when_universe_was_available(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:NASDAQ:TIME",
            symbol="TIME",
            name="Temporal Test",
            market="US",
            exchange="NASDAQ",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
        )
        session.add(stock)
        session.flush()
        candidate = UniverseCandidate(
            stock_id=stock.id,
            symbol=stock.symbol,
            market="US",
            exchange="NASDAQ",
            segment=MarketSegment.NASDAQ,
            asset_type="stock",
            size_bucket=SizeBucket.UNKNOWN,
            listing_age_bucket=ListingAgeBucket.UNKNOWN,
            list_date=None,
            delist_date=None,
        )
        published = datetime(2026, 8, 1, 1, tzinfo=UTC)
        repository = MarketDataQualityRepository(session)
        repository.store_universe_snapshot(
            market="US",
            as_of_date=date(2026, 7, 31),
            source="official",
            provider="archived_snapshot",
            available_time=published,
            ingested_time=published,
            members=[candidate],
        )
        session.commit()

        assert repository.latest_snapshot_ids(
            date(2026, 7, 31),
            available_by=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        ) == {}
        assert repository.latest_snapshot_ids(
            date(2026, 7, 31),
            available_by=published,
        )["US"] > 0


def test_quality_input_repository_rejects_duplicate_universe_members(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = Stock(
            canonical_code="A:SSE:600000",
            symbol="600000",
            name="Test",
            market="A",
            exchange="SSE",
            asset_type="stock",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        session.add(stock)
        session.flush()
        candidate = UniverseCandidate(
            stock_id=stock.id,
            symbol=stock.symbol,
            market="A",
            exchange="SSE",
            segment=MarketSegment.SSE_MAIN,
            asset_type="stock",
            size_bucket=SizeBucket.LARGE,
            listing_age_bucket=ListingAgeBucket.ESTABLISHED,
            list_date=None,
            delist_date=None,
        )
        timestamp = datetime(2026, 7, 31, tzinfo=UTC)

        with pytest.raises(ValueError, match="duplicate stock ids"):
            MarketDataQualityRepository(session).store_universe_snapshot(
                market="A",
                as_of_date=date(2026, 7, 31),
                source="sse",
                provider="official_import",
                available_time=timestamp,
                ingested_time=timestamp,
                members=[candidate, candidate],
            )
