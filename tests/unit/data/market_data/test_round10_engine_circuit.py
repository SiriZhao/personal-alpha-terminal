"""ROUND 10: MarketDataEngine circuit breaker + batch-first refresh tests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.market_data.circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitState,
)
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.schemas import InstrumentUpdateResult, PriceBar
from personal_alpha_terminal.data.market_data.service import MarketDataEngine
from personal_alpha_terminal.models import Base, Price, Stock

START = date(2026, 7, 1)
END = date(2026, 7, 3)


@dataclass(frozen=True, slots=True)
class _FakeProvider:
    source: str
    provider_id: str
    capabilities: tuple[ProviderCapability, ...]
    failure: str | None = None
    calls: int = 0

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        object.__setattr__(self, "calls", self.calls + 1)
        if self.failure == "challenge":
            raise ProviderRequestError(
                "Stooq is unavailable: HTML/JavaScript browser challenge returned"
            )
        capability = self.capabilities[0]
        return ProviderRawBatch(capability, request, ())


def _capability(source: str) -> ProviderCapability:
    return ProviderCapability(
        provider=source,
        market="US",
        asset_type="stock",
        endpoint=f"{source}.daily",
        raw_volume_unit="share",
        volume_unit="share",
        price_type="unadjusted_ohlcv",
        supported=True,
        volume_multiplier=Decimal("1"),
        raw_share_unit=Decimal("1"),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        market_data_max_retries=0,
        market_data_retry_backoff_seconds=0.0,
        market_data_provider_cache_dir=tmp_path / "cache",
        market_data_timeout_seconds=10,
        market_data_default_start=START,
        market_data_overlap_days=2,
    )


def test_open_circuit_suppresses_requests_and_classifies_challenge(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    breaker = ProviderCircuitBreaker(tmp_path / "circuit", trip_threshold=2)
    provider = _FakeProvider(
        source="stooq",
        provider_id="stooq.daily_csv.stock",
        capabilities=(_capability("stooq"),),
        failure="challenge",
    )
    with Session(engine) as session:
        repository = PriceRepository(session)
        market_engine = MarketDataEngine(
            providers=[provider],
            repository=repository,
            settings=_settings(tmp_path),
            circuit_breaker=breaker,
            batch_threshold=100,
        )
        # First two calls trip the circuit with BOT_CHALLENGE.
        with pytest.raises(ProviderRequestError, match="BOT_CHALLENGE"):
            market_engine.get_stock_price("AFRM", "US", START, END)
        with pytest.raises(ProviderRequestError, match="BOT_CHALLENGE"):
            market_engine.get_stock_price("AFRM", "US", START, END)
        assert breaker.state("stooq") is ProviderCircuitState.OPEN_CIRCUIT
        calls_after_trip = provider.calls
        # The third request must be suppressed entirely (no provider call).
        with pytest.raises(ProviderRequestError, match="All providers failed"):
            market_engine.get_stock_price("AFRM", "US", START, END)
        assert provider.calls == calls_after_trip


def test_batch_first_refresh_persists_successes_and_records_failures(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)

    @dataclass(frozen=True, slots=True)
    class _Report:
        requested_symbols: tuple[str, ...]
        received_symbols: tuple[str, ...]
        failed_symbols: tuple[str, ...]
        bar_count: int
        chunk_count: int
        bars: tuple[PriceBar, ...] = ()

    class _Batch:
        source = "yahoo_finance"
        provider_id = "yahoo_finance.broad_universe_batch"
        chunk_size = 100

        def download(self, symbols, *, start_date, end_date):
            received = tuple(symbols)
            failed = ()
            event = datetime(2026, 7, 3, 20, 0, tzinfo=__import__("datetime").timezone.utc)
            available = datetime(2026, 7, 3, 20, 30, tzinfo=__import__("datetime").timezone.utc)
            bars = tuple(
                PriceBar(
                    symbol=symbol,
                    market="US",
                    date=END,
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100.5"),
                    volume=1000,
                    event_time=event,
                    available_time=available,
                    ingested_time=available,
                    asset_type="stock",
                    volume_unit="share",
                    price_type="unadjusted_ohlcv",
                )
                for symbol in symbols
            )
            return _Report(received, received, failed, len(bars), 1, bars)

    breaker = ProviderCircuitBreaker(tmp_path / "circuit", trip_threshold=2)
    with Session(engine) as session:
        for symbol in ("A", "B", "C"):
            session.add(
                Stock(
                    canonical_code=f"US:XNAS:{symbol}",
                    symbol=symbol,
                    name=symbol,
                    market="US",
                    exchange="XNAS",
                    asset_type="stock",
                    currency="USD",
                    timezone="America/New_York",
                    list_date=date(2020, 1, 1),
                    is_active=True,
                    source="fixture",
                    provider="fixture",
                    available_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
                    ingested_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
                )
            )
        session.flush()
        repository = PriceRepository(session)
        engine_service = MarketDataEngine(
            providers=[],
            repository=repository,
            settings=_settings(tmp_path),
            circuit_breaker=breaker,
            batch_provider=_Batch(),
            batch_threshold=2,  # 3 stocks > 2 -> batch path
        )
        report = engine_service.update_daily_data(markets={"US"}, end_date=END)
        statuses = {item.symbol: item.status for item in report.results}
        assert statuses["A"] == "success"
        assert statuses["B"] == "success"
        assert statuses["C"] == "success"
        from personal_alpha_terminal.models import Price

        stored = session.query(Price).count()
        assert stored == 3
    engine.dispose()


def test_batch_refresh_routes_non_stock_assets_outside_stock_batch(
    tmp_path: Path, monkeypatch
) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)

    class _Batch:
        source = "yahoo_finance"
        provider_id = "yahoo_finance.broad_universe_batch"
        chunk_size = 100

        def __init__(self) -> None:
            self.symbols: tuple[str, ...] = ()

        def download(self, symbols, *, start_date, end_date):
            del start_date, end_date
            self.symbols = tuple(symbols)
            return type(
                "Report",
                (),
                {
                    "received_symbols": (),
                    "failed_symbols": tuple(symbols),
                    "bars": (),
                },
            )()

    batch = _Batch()
    with Session(engine) as session:
        for symbol in ("A", "B", "C"):
            session.add(
                Stock(
                    canonical_code=f"US:XNAS:{symbol}",
                    symbol=symbol,
                    name=symbol,
                    market="US",
                    exchange="XNAS",
                    asset_type="stock",
                    currency="USD",
                    timezone="America/New_York",
                    list_date=date(2020, 1, 1),
                    is_active=True,
                    source="fixture",
                    provider="fixture",
                    available_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
                    ingested_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
                )
            )
        session.add(
            Stock(
                canonical_code="US:ARCX:SPY",
                symbol="SPY",
                name="SPY",
                market="US",
                exchange="ARCX",
                asset_type="etf",
                currency="USD",
                timezone="America/New_York",
                list_date=date(2020, 1, 1),
                is_active=True,
                source="fixture",
                provider="fixture",
                available_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
                ingested_time=datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            )
        )
        session.flush()
        service = MarketDataEngine(
            providers=[],
            repository=PriceRepository(session),
            settings=_settings(tmp_path),
            batch_provider=batch,
            batch_threshold=2,
        )
        routed: list[str] = []

        def fake_update(stock, end_date, *, forced_start_date):
            del end_date, forced_start_date
            routed.append(stock.asset_type)
            return InstrumentUpdateResult(
                symbol=stock.symbol,
                market="US",
                source="fixture",
                provider="fixture",
                status="no_data",
                start_date=START,
                end_date=END,
            )

        monkeypatch.setattr(service, "_update_stock", fake_update)
        service.update_daily_data(markets={"US"}, end_date=END)

    assert batch.symbols == ("A", "B", "C")
    assert routed == ["etf"]
    engine.dispose()


def test_warm_non_stock_refresh_does_not_re_request_a_persisted_session(tmp_path: Path) -> None:
    """ETFs/indices used to receive the forced bootstrap range on every run."""

    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)

    @dataclass(frozen=True, slots=True)
    class _EtfProvider:
        source: str = "fixture"
        provider_id: str = "fixture.etf"
        calls: int = 0

        @property
        def capabilities(self) -> tuple[ProviderCapability, ...]:
            return (
                ProviderCapability(
                    provider=self.source,
                    market="US",
                    asset_type="etf",
                    endpoint="fixture",
                    raw_volume_unit="share",
                    volume_unit="share",
                    price_type="unadjusted_ohlcv",
                    supported=True,
                    volume_multiplier=Decimal("1"),
                    raw_share_unit=Decimal("1"),
                ),
            )

        def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
            del request
            object.__setattr__(self, "calls", self.calls + 1)
            raise AssertionError("a current ETF must not call the provider")

    available = datetime(2026, 7, 3, 20, 30, tzinfo=__import__("datetime").timezone.utc)
    provider = _EtfProvider()
    with Session(engine) as session:
        stock = Stock(
            canonical_code="US:ARCX:WARM",
            symbol="WARM",
            name="Warm ETF",
            market="US",
            exchange="ARCX",
            asset_type="etf",
            currency="USD",
            timezone="America/New_York",
            list_date=None,
            is_active=True,
            source="fixture",
            provider="fixture",
            available_time=available,
            ingested_time=available,
        )
        session.add(stock)
        session.flush()
        session.add(
            Price(
                stock_id=stock.id,
                trade_date=END,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=1000,
                asset_type="etf",
                volume_unit="share",
                price_type="unadjusted_ohlcv",
                source="fixture",
                provider="fixture.etf",
                event_time=available,
                available_time=available,
                ingested_at=available,
            )
        )
        session.flush()
        service = MarketDataEngine(
            providers=[provider],
            repository=PriceRepository(session),
            settings=_settings(tmp_path),
        )
        outcome = service._update_stock(stock, END, forced_start_date=None)

    assert outcome.status == "cached"
    assert outcome.refresh_class == "CACHED_UP_TO_DATE"
    assert provider.calls == 0
    engine.dispose()


def test_batch_cache_reuse_requires_full_request_window(tmp_path: Path) -> None:
    """A cache with only the latest bar must not count as reusable history."""
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)

    class _Batch:
        source = "yahoo_finance"
        provider_id = "yahoo_finance.broad_universe_batch"
        chunk_size = 100

        def __init__(self) -> None:
            self.calls = 0

        def download(self, symbols, *, start_date, end_date):
            del symbols, start_date, end_date
            self.calls += 1
            return type(
                "Report",
                (),
                {"received_symbols": (), "failed_symbols": (), "bars": ()},
            )()

    batch = _Batch()
    available = datetime(2026, 7, 3, 20, 30, tzinfo=__import__("datetime").timezone.utc)
    with Session(engine) as session:
        stock = Stock(
            canonical_code="US:XNAS:CACHE",
            symbol="CACHE",
            name="Cache Test",
            market="US",
            exchange="XNAS",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            list_date=date(2020, 1, 1),
            is_active=True,
            source="fixture",
            provider="fixture",
            available_time=available,
            ingested_time=available,
        )
        session.add(stock)
        session.flush()
        session.add(
            __import__("personal_alpha_terminal.models", fromlist=["Price"]).Price(
                stock_id=stock.id,
                trade_date=END,
                open=__import__("decimal").Decimal("100"),
                high=__import__("decimal").Decimal("101"),
                low=__import__("decimal").Decimal("99"),
                close=__import__("decimal").Decimal("100"),
                volume=1000,
                asset_type="stock",
                volume_unit="share",
                price_type="unadjusted_ohlcv",
                source="yahoo_finance",
                provider="yahoo_finance.broad_universe_batch",
                event_time=available - __import__("datetime").timedelta(minutes=30),
                available_time=available,
                ingested_at=available,
            )
        )
        session.flush()
        service = MarketDataEngine(
            providers=[],
            repository=PriceRepository(session),
            settings=_settings(tmp_path),
            batch_provider=batch,
            batch_threshold=1,
        )
        service._run_batch_refresh([stock], END, forced_start_date=None)
        assert batch.calls == 1
        session.add(
            __import__("personal_alpha_terminal.models", fromlist=["Price"]).Price(
                stock_id=stock.id,
                trade_date=date(2024, 6, 1),
                open=__import__("decimal").Decimal("100"),
                high=__import__("decimal").Decimal("101"),
                low=__import__("decimal").Decimal("99"),
                close=__import__("decimal").Decimal("100"),
                volume=1000,
                asset_type="stock",
                volume_unit="share",
                price_type="unadjusted_ohlcv",
                source="yahoo_finance",
                provider="yahoo_finance.broad_universe_batch",
                event_time=available - __import__("datetime").timedelta(minutes=30),
                available_time=available,
                ingested_at=available,
            )
        )
        session.flush()
        service._run_batch_refresh([stock], END, forced_start_date=None)
        assert batch.calls == 1
    engine.dispose()
