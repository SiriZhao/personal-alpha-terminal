from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.application.data_lineage_certification import (
    ActionEvidence,
    DataLineageCertifier,
    EvidenceStatus,
)
from personal_alpha_terminal.application.universe import ResearchAsset
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.providers import stooq as stooq_module
from personal_alpha_terminal.data.market_data.providers.stooq import StooqStockAdapter
from personal_alpha_terminal.models import CorporateAction, Price, Stock

ASSET = ResearchAsset("TEST", "Test", "XNAS", "stock", "test", True)
NOW = datetime(2026, 1, 12, 14, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        runtime_profile="TEST",
        database_url="sqlite://",
        market_data_reconciliation_minimum_coverage=0.8,
        market_data_reconciliation_maximum_blocking_ratio=0.01,
    )


def _add_prices(session: Session, dates: list[date]) -> Stock:
    stock = Stock(
        canonical_code="US:XNAS:TEST",
        symbol="TEST",
        name="Test",
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    session.flush()
    for index, trade_date in enumerate(dates):
        close = Decimal(str(100 + index))
        event = datetime.combine(trade_date, datetime.min.time(), UTC).replace(hour=21)
        session.add(
            Price(
                stock_id=stock.id,
                trade_date=trade_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                adjusted_close=close,
                volume=1_000_000,
                asset_type="stock",
                volume_unit="share",
                price_currency="USD",
                share_unit=Decimal("1"),
                price_type="unadjusted_ohlcv",
                source="yahoo_finance",
                provider="yfinance.download.stock",
                adjustment_method="raw_ohlcv",
                event_time=event,
                available_time=event + timedelta(minutes=30),
            )
        )
    session.flush()
    return stock


def test_reconciliation_uses_returns_not_absolute_price(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        certifier = DataLineageCertifier(session, _settings())
        dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        primary = dict(zip(dates, (100.0, 101.0, 102.0), strict=True))
        secondary = dict(zip(dates, (50.0, 50.5, 51.0), strict=True))
        result = certifier._compare("TEST", primary, secondary)
    assert result.status is EvidenceStatus.PASS
    assert result.coverage == 1.0


def test_reconciliation_blocks_large_return_disagreement(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        certifier = DataLineageCertifier(session, _settings())
        dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        result = certifier._compare(
            "TEST",
            dict(zip(dates, (100.0, 101.0, 102.0), strict=True)),
            dict(zip(dates, (100.0, 130.0, 131.0), strict=True)),
        )
    assert result.status is EvidenceStatus.FAIL_BLOCKING
    assert result.blocking_divergences == 1


def test_latest_session_price_divergence_is_blocking_even_when_sparse(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        certifier = DataLineageCertifier(session, _settings())
        dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(102)]
        primary = {observed: 100.0 + offset for offset, observed in enumerate(dates)}
        secondary = dict(primary)
        secondary[dates[-1]] = 100.0
        result = certifier._compare("TEST", primary, secondary)
    assert result.status is EvidenceStatus.FAIL_BLOCKING
    assert result.blocking_divergences == 1
    assert result.failure_category == "LATEST_PRICE_DIVERGENCE"


def test_received_greater_than_expected_is_not_capped_or_hidden(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        certifier = DataLineageCertifier(session, _settings())
        expected = {date(2026, 1, 5), date(2026, 1, 6)}
        rows = tuple(
            SimpleNamespace(trade_date=item)
            for item in (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
        )
        import personal_alpha_terminal.application.data_lineage_certification as module

        original = module._xnys_dates
        module._xnys_dates = lambda _start, _end: expected
        try:
            evidence = certifier._coverage(
                (ASSET,), {"TEST": rows}, {}, date(2026, 1, 5), date(2026, 1, 7)
            )[0]
        finally:
            module._xnys_dates = original
    assert evidence.expected == 2
    assert evidence.matched == 2
    assert evidence.unexpected == 1
    assert evidence.rejected == 1
    assert evidence.valid == 2
    assert evidence.unexpected_dates == (date(2026, 1, 7),)


def test_corporate_actions_persist_without_fake_announcement(
    session_factory: sessionmaker[Session],
) -> None:
    dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]

    def actions(*_args):
        return (
            ActionEvidence(
                "cash_dividend",
                date(2026, 1, 6),
                0.25,
                None,
                datetime(2026, 1, 6, 21, 30, tzinfo=UTC),
                "fixture.actions",
            ),
            ActionEvidence(
                "split",
                date(2026, 1, 7),
                2.0,
                None,
                datetime(2026, 1, 7, 21, 30, tzinfo=UTC),
                "fixture.actions",
            ),
            ActionEvidence(
                "reverse_split",
                date(2026, 1, 7),
                0.5,
                None,
                datetime(2026, 1, 7, 21, 30, tzinfo=UTC),
                "fixture.actions",
            ),
        )

    with session_factory.begin() as session:
        _add_prices(session, dates)
        primary = dict(zip(dates, (100.0, 101.0, 102.0), strict=True))
        certifier = DataLineageCertifier(
            session,
            _settings(),
            action_fetcher=actions,
            secondary_fetcher=lambda *_args: primary,
        )
        bundle = certifier.certify(
            assets=(ASSET,),
            start_date=dates[0],
            analysis_date=dates[-1],
            decision_time=NOW,
            include_optional_reconciliation=True,
        )
        persisted = tuple(session.scalars(select(CorporateAction)))
    assert bundle.corporate_actions.status is EvidenceStatus.PASS
    assert bundle.reconciliation.status is EvidenceStatus.PASS
    assert len(persisted) == 3
    assert {item.action_type for item in persisted} == {
        "cash_dividend",
        "split",
        "reverse_split",
    }
    assert all(item.announcement_date is None for item in persisted)
    assert bundle.data_cutoff is not None and bundle.data_cutoff <= NOW


def test_daily_lineage_does_not_request_optional_secondary(
    session_factory: sessionmaker[Session],
) -> None:
    dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    calls = 0

    def secondary(*_args):
        nonlocal calls
        calls += 1
        return {item: 100.0 for item in dates}

    with session_factory.begin() as session:
        _add_prices(session, dates)
        bundle = DataLineageCertifier(
            session,
            _settings(),
            action_fetcher=lambda *_args: (),
            secondary_fetcher=secondary,
        ).certify(
            assets=(ASSET,),
            start_date=dates[0],
            analysis_date=dates[-1],
            decision_time=NOW,
        )
    assert calls == 0
    assert bundle.reconciliation.status is EvidenceStatus.NOT_RUN_OPTIONAL


def test_optional_reconciliation_window_is_not_limited_by_incremental_refresh(
    session_factory: sessionmaker[Session],
) -> None:
    import personal_alpha_terminal.application.data_lineage_certification as module

    settings = _settings()
    with session_factory() as session:
        start = DataLineageCertifier(session, settings)._reconciliation_start(
            date(2026, 8, 7)
        )
    assert len(module._xnys_dates(start, date(2026, 8, 7))) >= (
        settings.market_data_reconciliation_preferred_overlap_sessions
    )


def test_future_action_availability_fails_closed(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        _add_prices(session, [date(2026, 1, 5), date(2026, 1, 6)])
        certifier = DataLineageCertifier(
            session,
            _settings(),
            action_fetcher=lambda *_args: (
                ActionEvidence(
                    "cash_dividend",
                    date(2026, 1, 6),
                    0.2,
                    None,
                    NOW + timedelta(days=1),
                    "fixture.actions",
                ),
            ),
            secondary_fetcher=lambda *_args: {
                date(2026, 1, 5): 100.0,
                date(2026, 1, 6): 101.0,
            },
        )
        bundle = certifier.certify(
            assets=(ASSET,),
            start_date=date(2026, 1, 5),
            analysis_date=date(2026, 1, 6),
            decision_time=NOW,
        )
    assert bundle.corporate_actions.status is EvidenceStatus.FAIL_BLOCKING


def test_stooq_html_challenge_is_rejected_before_csv_parse(monkeypatch) -> None:
    class Response:
        headers = {"Content-Type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"<!doctype html><p>This site requires JavaScript to verify your browser</p>"

    monkeypatch.setattr(stooq_module, "urlopen", lambda *_args, **_kwargs: Response())
    request = AssetPriceRequest(
        symbol="AAPL",
        market="US",
        asset_type="stock",
        price_currency="USD",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
    )
    with pytest.raises(ProviderRequestError, match="HTML/JavaScript browser challenge"):
        StooqStockAdapter().fetch_raw(request)


def test_corporate_action_insert_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        stock = _add_prices(session, [date(2026, 1, 5), date(2026, 1, 6)])
        event = ActionEvidence(
            "cash_dividend",
            date(2026, 1, 6),
            0.2,
            None,
            datetime(2026, 1, 6, 21, 30, tzinfo=UTC),
            "fixture.actions",
        )
        certifier = DataLineageCertifier(session, _settings())
        certifier._persist_action(stock, event, NOW)
        session.flush()
        certifier._persist_action(stock, event, NOW)
        session.flush()
        count = session.scalar(select(func.count()).select_from(CorporateAction))
    assert count == 1
