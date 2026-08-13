from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import MethodType

from sqlalchemy import func, select

from personal_alpha_terminal.application.broad_universe_service import BroadUSUniverseService
from personal_alpha_terminal.data.broad_market.batch_provider import (
    BatchDownloadReport,
    YahooBatchStockProvider,
)
from personal_alpha_terminal.data.broad_market.service import BroadUniverseDataService
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.schemas import StockPriceBar
from personal_alpha_terminal.data.us_market.broad_universe import (
    EligibilityRules,
    parse_symbol_directories,
    write_directory_snapshot,
)
from personal_alpha_terminal.models import Price, Stock

DECISION = datetime(2026, 8, 12, 12, tzinfo=UTC)
NASDAQ = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
    "Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N\n"
    "File Creation Time: 0811202621:31|||||||\n"
)
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
File Creation Time: 0811202621:31|||||||
"""


def _bar(symbol: str, day: date) -> StockPriceBar:
    return StockPriceBar(
        symbol=symbol,
        market="US",
        date=day,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        adjusted_close=Decimal("101"),
        volume=1_000_000,
        event_time=datetime(2026, 8, 11, 20, tzinfo=UTC),
        available_time=datetime(2026, 8, 11, 21, tzinfo=UTC),
        ingested_time=DECISION,
        adjustment_method="yahoo_provider_total_return_current_snapshot",
        price_currency="USD",
    )


def _stock(symbol: str = "AAPL") -> Stock:
    return Stock(
        canonical_code=f"US:XNAS:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
        list_date=date(2000, 1, 1),
        is_active=True,
        source="TEST_FIXTURE",
        provider="TEST_FIXTURE",
        available_time=DECISION,
        ingested_time=DECISION,
    )


def test_batch_provider_isolates_a_failed_chunk(monkeypatch) -> None:
    provider = YahooBatchStockProvider(chunk_size=2)
    monkeypatch.setattr(provider, "_load_library", lambda: object())
    calls = 0

    def fake_chunk(
        _self,
        _library,
        symbols,
        *,
        start_date,
        end_date,
        bars,
        ingested_at,
    ):
        nonlocal calls
        del start_date, end_date, ingested_at
        calls += 1
        if calls == 1:
            raise ProviderRequestError("isolated provider failure")
        bars.append(_bar(symbols[0], date(2026, 8, 11)))
        return set(symbols[1:])

    monkeypatch.setattr(provider, "_download_chunk", MethodType(fake_chunk, provider))
    result = provider.download(
        ("A", "B", "C", "D"),
        start_date=date(2026, 8, 11),
        end_date=date(2026, 8, 11),
        ingested_at=DECISION,
    )

    assert result.received_symbols == ("C",)
    assert result.failed_symbols == ("A", "B", "D")
    assert result.chunk_count == 2
    assert result.coverage == 0.25


def test_batch_provider_maps_yahoo_share_class_tickers_back(monkeypatch) -> None:
    provider = YahooBatchStockProvider(chunk_size=10)
    monkeypatch.setattr(provider, "_load_library", lambda: object())

    def fake_chunk(
        _self,
        _library,
        symbols,
        *,
        start_date,
        end_date,
        bars,
        ingested_at,
    ):
        del start_date, end_date, ingested_at
        bars.append(_bar(symbols[0], date(2026, 8, 11)))
        return set(symbols[1:])

    monkeypatch.setattr(provider, "_download_chunk", MethodType(fake_chunk, provider))
    result = provider.download(
        ("BRK.A", "BRK.B", "BF.A"),
        start_date=date(2026, 8, 11),
        end_date=date(2026, 8, 11),
        ingested_at=DECISION,
    )
    assert result.received_symbols == ("BRK.A",)
    assert result.failed_symbols == ("BF.A", "BRK.B")
    assert result.bars[0].symbol == "BRK.A"


def test_bulk_insert_is_idempotent_and_reports_actual_rows(session_factory, tmp_path) -> None:
    with session_factory.begin() as session:
        stock = _stock()
        session.add(stock)
        session.flush()
        service = BroadUniverseDataService(session, cache_root=tmp_path)
        report = BatchDownloadReport(
            requested_symbols=("AAPL",),
            received_symbols=("AAPL",),
            failed_symbols=(),
            quarantined_symbols=(),
            bar_count=1,
            chunk_count=1,
            bars=(_bar("AAPL", date(2026, 8, 11)),),
        )

        first = service._bulk_upsert_bars({"AAPL": stock}, report=report)
        second = service._bulk_upsert_bars({"AAPL": stock}, report=report)
        count = session.scalar(select(func.count()).select_from(Price))

    assert first == (1, 0)
    assert second == (0, 0)
    assert count == 1


def test_stock_batch_sync_ignores_same_symbol_etf_master_row(
    session_factory, tmp_path, monkeypatch
) -> None:
    stock = _stock("DUP")
    etf = _stock("DUP")
    etf.canonical_code = "US:ARCX:DUP"
    etf.exchange = "ARCX"
    etf.asset_type = "etf"
    provider = YahooBatchStockProvider(chunk_size=10)
    monkeypatch.setattr(
        provider,
        "download",
        lambda symbols, **_kwargs: BatchDownloadReport(
            requested_symbols=symbols,
            received_symbols=(),
            failed_symbols=symbols,
            quarantined_symbols=(),
            bar_count=0,
            chunk_count=1,
        ),
    )
    with session_factory.begin() as session:
        session.add_all((stock, etf))
        session.flush()
        service = BroadUniverseDataService(
            session,
            cache_root=tmp_path,
            provider=provider,
        )
        result = service.sync_symbols(
            symbols=("DUP",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 12),
            decision_time=DECISION,
        )

    assert result.total_registered == 1
    assert result.report.requested_symbols == ("DUP",)


def test_current_directory_registration_excludes_etfs(session_factory, tmp_path) -> None:
    snapshot = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=DECISION)
    directory = tmp_path / "us-current-directory"
    write_directory_snapshot(snapshot, directory)
    with session_factory.begin() as session:
        service = BroadUniverseDataService(
            session,
            cache_root=tmp_path,
            directory_root=directory,
        )
        report = service.register_current_directory(decision_time=DECISION)
        symbols = set(session.scalars(select(Stock.symbol)))

    assert report.directory_securities == 3
    assert report.registered == 2
    assert symbols == {"AAPL", "IBM"}


def test_relaxed_price_diagnostic_does_not_mutate_strict_service_rules(
    session_factory, tmp_path
) -> None:
    snapshot = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=DECISION)
    write_directory_snapshot(snapshot, tmp_path)
    rules = EligibilityRules(minimum_trading_sessions=2)
    with session_factory() as session:
        service = BroadUSUniverseService(session, cache_root=tmp_path, rules=rules)
        service.select(
            universe_date=date(2026, 8, 12),
            decision_time=DECISION,
            reference_symbols=("QQQ",),
            require_pit_total_return=False,
        )

    assert service.rules.require_pit_total_return is True
    assert service.rules.fingerprint == rules.fingerprint
