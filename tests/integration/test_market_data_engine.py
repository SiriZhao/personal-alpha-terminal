from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBar,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.schemas import Market, PriceBar
from personal_alpha_terminal.data.market_data.service import MarketDataEngine
from personal_alpha_terminal.models import Price, Stock


class FakeProvider:
    source = "fake"
    provider_id = "fake.test_adapter"
    capabilities = tuple(
        ProviderCapability(
            provider="fake",
            market=market,
            asset_type=asset_type,
            endpoint=f"fake_{asset_type}",
            raw_volume_unit=("none" if asset_type == "index" else "share"),
            volume_unit=("none" if asset_type == "index" else "share"),
            price_type=("index_level_ohlcv" if asset_type == "index" else "unadjusted_ohlcv"),
            supported=asset_type in {"stock", "index", "etf"},
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        )
        for market in ("A", "HK", "US")
        for asset_type in ("stock", "etf", "index")
    ) + tuple(
        ProviderCapability(
            provider="fake",
            market=market,
            asset_type="bond",
            endpoint="fake_bond",
            raw_volume_unit="unknown",
            volume_unit="face_value",
            price_type="clean_price_ohlcv",
            supported=False,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        )
        for market in ("A", "HK", "US")
    )

    def __init__(self, bars: dict[str, list[PriceBar]]) -> None:
        self.bars = bars
        self.calls: list[tuple[str, date, date, bool]] = []
        self.failures_remaining = 0

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        self.calls.append(
            (request.symbol, request.start_date, request.end_date, request.asset_type == "index")
        )
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise ProviderRequestError("temporary failure")
        capability = next(
            item
            for item in self.capabilities
            if item.market == request.market and item.asset_type == request.asset_type
        )
        rows = tuple(
            ProviderRawBar(
                symbol=request.symbol,
                market=request.market,
                asset_type=request.asset_type,
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=(
                    None
                    if capability.raw_volume_unit == "none" or bar.volume is None
                    else Decimal(bar.volume)
                ),
                raw_volume_unit=capability.raw_volume_unit,
                price_currency=request.price_currency,
                raw_share_unit=capability.raw_share_unit,
                price_type=capability.price_type,
                adjusted_close=bar.adjusted_close,
                forward_adjusted_close=bar.forward_adjusted_close,
                backward_adjusted_close=bar.backward_adjusted_close,
                adjustment_method=bar.adjustment_method,
                open_tradable=bar.open_tradable,
            )
            for bar in self.bars.get(request.symbol, [])
            if request.start_date <= bar.date <= request.end_date
        )
        return ProviderRawBatch(capability, request, rows)


def make_bar(symbol: str, market: Market, day: int, close: str) -> PriceBar:
    value = Decimal(close)
    trade_date = date(2026, 7, day)
    timestamps = daily_bar_timestamps(trade_date, market)
    return PriceBar(
        symbol=symbol,
        market=market,
        date=trade_date,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=1000,
        event_time=timestamps.event_time,
        available_time=timestamps.available_time,
        ingested_time=timestamps.ingested_time,
    )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        market_data_default_start=date(2026, 7, 1),
        market_data_overlap_days=2,
        market_data_max_retries=2,
        market_data_retry_backoff_seconds=0,
    )


def add_stock(session: Session, symbol: str, market: Market, *, asset_type: str = "stock") -> Stock:
    stock = Stock(
        canonical_code=f"{market}:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market=market,
        exchange="TEST",
        asset_type=asset_type,
        currency="CNY" if market == "A" else "USD",
        timezone="Asia/Shanghai" if market == "A" else "America/New_York",
    )
    session.add(stock)
    session.commit()
    return stock


def test_incremental_update_uses_missing_sessions_and_explicit_refresh_revises_history(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        add_stock(session, "000001", "A")
        provider = FakeProvider(
            {
                "000001": [
                    make_bar("000001", "A", 1, "10"),
                    make_bar("000001", "A", 2, "11"),
                    make_bar("000001", "A", 3, "12"),
                ]
            }
        )
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _: None,
        )

        first = engine.update_daily_data(markets={"A"}, end_date=date(2026, 7, 3))
        session.commit()
        assert first.inserted_count == 3

        provider.bars["000001"] = [
            make_bar("000001", "A", 2, "11.5"),
            make_bar("000001", "A", 3, "12"),
            make_bar("000001", "A", 6, "13.12345678"),
            make_bar("000001", "A", 6, "13.12345678"),
        ]
        second = engine.update_daily_data(markets={"A"}, end_date=date(2026, 7, 6))
        session.commit()

        # Ordinary warm refreshes must fetch only legally missing sessions.
        # Historical corrections are not silently requested as overlapping
        # data: that requires an explicit operator-provenance request below.
        assert provider.calls[-1][1] == date(2026, 7, 4)
        assert second.failure_count == 0
        assert second.cached_count == 1
        assert "data-quality errors" in (second.results[0].error or "")
        assert second.inserted_count == 0
        assert second.updated_count == 0
        assert session.scalar(select(func.count()).select_from(Price)) == 3

        provider.bars["000001"] = [
            make_bar("000001", "A", 2, "11.5"),
            make_bar("000001", "A", 3, "12"),
            make_bar("000001", "A", 6, "13.12345678"),
        ]
        third = engine.update_daily_data(
            markets={"A"},
            end_date=date(2026, 7, 6),
        )
        session.commit()
        assert third.inserted_count == 1
        assert third.updated_count == 0
        assert session.scalar(select(func.count()).select_from(Price)) == 4
        revised = session.scalar(select(Price).where(Price.trade_date == date(2026, 7, 2)))
        assert revised is not None
        assert revised.close == Decimal("11.000000")

        explicit_revision = engine.update_daily_data(
            markets={"A"},
            start_date=date(2026, 7, 2),
            end_date=date(2026, 7, 6),
        )
        session.commit()
        assert provider.calls[-1][1] == date(2026, 7, 2)
        assert explicit_revision.inserted_count == 0
        assert explicit_revision.updated_count == 1
        revised = session.scalar(select(Price).where(Price.trade_date == date(2026, 7, 2)))
        assert revised is not None
        assert revised.close == Decimal("11.500000")

        fourth = engine.update_daily_data(
            markets={"A"},
            end_date=date(2026, 7, 6),
        )
        session.commit()
        assert fourth.inserted_count == 0
        assert fourth.updated_count == 0

        refreshed = engine.update_daily_data(
            markets={"A"},
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 6),
        )
        assert refreshed.analysis_safe
        assert provider.calls[-1][1] == date(2026, 7, 1)


def test_provider_errors_are_retried_without_duplicate_writes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        add_stock(session, "AAPL", "US")
        provider = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "200")]})
        provider.failures_remaining = 2
        delays: list[float] = []
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=delays.append,
        )

        report = engine.update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))
        session.commit()

        assert report.success_count == 1
        assert len(provider.calls) == 3
        assert delays == [0.0, 0.0]
        assert session.scalar(select(func.count()).select_from(Price)) == 1


def test_network_outage_exhausts_retries_and_preserves_existing_prices(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = add_stock(session, "AAPL", "US")
        existing = make_bar("AAPL", "US", 28, "199")
        PriceRepository(session).upsert_bars(
            stock=stock,
            bars=[existing],
            source="fake",
            provider="fake.test_adapter",
        )
        session.commit()
        provider = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "200")]})
        provider.failures_remaining = 99
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _delay: None,
        )

        report = engine.update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))
        session.commit()

        assert report.failure_count == 0
        assert report.cached_count == 1
        assert not report.analysis_safe
        assert len(provider.calls) == 3
        stored = tuple(session.scalars(select(Price).order_by(Price.trade_date)))
        assert len(stored) == 1
        assert stored[0].close == Decimal("199.000000")


def test_primary_outage_falls_back_to_secondary_provider(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        add_stock(session, "AAPL", "US")
        primary = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "199")]})
        primary.source = "primary"
        primary.provider_id = "primary.fixture"
        primary.failures_remaining = 99
        secondary = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "200")]})
        secondary.source = "secondary"
        secondary.provider_id = "secondary.fixture"
        engine = MarketDataEngine(
            providers=[primary, secondary],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _delay: None,
        )

        report = engine.update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))
        session.commit()

        assert report.success_count == 1
        assert report.results[0].source == "secondary"
        assert report.results[0].provider == "secondary.fixture"
        assert len(primary.calls) == 3
        assert len(secondary.calls) == 1
        stored = session.scalar(select(Price))
        assert stored is not None
        assert stored.source == "secondary"


def test_successful_primary_does_not_request_secondary_provider(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        add_stock(session, "AAPL", "US")
        primary = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "199")]})
        primary.source = "yahoo_finance"
        primary.provider_id = "primary.fixture"
        secondary = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "200")]})
        secondary.source = "optional_fallback"
        secondary.provider_id = "secondary.fixture"
        report = MarketDataEngine(
            providers=[primary, secondary],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _delay: None,
        ).update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))

    assert report.success_count == 1
    assert len(primary.calls) == 1
    assert secondary.calls == []


def test_registered_index_uses_index_provider_method(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        add_stock(session, "^GSPC", "US", asset_type="index")
        provider = FakeProvider({"^GSPC": [make_bar("^GSPC", "US", 29, "6000")]})
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _: None,
        )

        report = engine.update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))

        assert report.success_count == 1
        assert provider.calls[0][3] is True


def test_unknown_symbol_is_reported_without_network_call(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        provider = FakeProvider({})
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _: None,
        )

        report = engine.update_daily_data(
            markets={"US"},
            symbols={"MISSING"},
            end_date=date(2026, 7, 29),
        )

        assert report.failure_count == 1
        assert "not registered" in (report.results[0].error or "")
        assert not provider.calls


def test_invalid_currency_and_timezone_metadata_fail_closed_before_fetch(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        stock = add_stock(session, "AAPL", "US")
        stock.currency = "CNY"
        stock.timezone = "Asia/Shanghai"
        session.commit()
        provider = FakeProvider({"AAPL": [make_bar("AAPL", "US", 29, "200")]})
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _delay: None,
        )

        report = engine.update_daily_data(markets={"US"}, end_date=date(2026, 7, 29))

        assert report.failure_count == 1
        assert not report.analysis_safe
        assert "currency" in (report.results[0].error or "")
        assert provider.calls == []


@pytest.mark.parametrize(
    ("market", "symbol", "asset_type", "expected"),
    (
        ("US", "CORP-BOND", "bond", "not certified"),
    ),
)
def test_uncertified_asset_endpoint_mapping_fails_closed_before_fetch(
    session_factory: sessionmaker[Session],
    market: Market,
    symbol: str,
    asset_type: str,
    expected: str,
) -> None:
    with session_factory() as session:
        add_stock(session, symbol, market, asset_type=asset_type)
        provider = FakeProvider({symbol: [make_bar(symbol, market, 29, "100")]})
        engine = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=settings(),
            sleep=lambda _delay: None,
        )

        report = engine.update_daily_data(markets={market}, end_date=date(2026, 7, 29))

        assert report.failure_count == 1
        assert not report.analysis_safe
        assert expected in (report.results[0].error or "")
        assert provider.calls == []
