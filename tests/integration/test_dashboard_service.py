from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.dashboard.repository import DashboardRepository
from personal_alpha_terminal.dashboard.service import DashboardService
from personal_alpha_terminal.models import (
    Industry,
    Portfolio,
    PortfolioPosition,
    Price,
    Stock,
)


def make_service(session: Session) -> DashboardService:
    return DashboardService(
        DashboardRepository(session),
        Settings(
            _env_file=None,
            dashboard_major_indices="A:sh000001,US:^GSPC",
            dashboard_annual_risk_free_rate=0,
        ),
    )


def add_price(
    session: Session,
    stock: Stock,
    day: int,
    close: str,
    *,
    source: str = "yahoo_finance",
) -> None:
    value = Decimal(close)
    session.add(
        Price(
            stock=stock,
            trade_date=date(2026, 7, day),
            open=value,
            high=value + 1,
            low=value - 1,
            close=value,
            adjusted_close=value,
            volume=1_000_000 + day,
            source=source,
            ingested_at=datetime(2026, 7, day, tzinfo=UTC),
        )
    )


def add_stock(
    session: Session,
    *,
    canonical_code: str,
    symbol: str,
    name: str,
    market: str,
    asset_type: str = "stock",
    currency: str = "USD",
    industry: Industry | None = None,
) -> Stock:
    stock = Stock(
        canonical_code=canonical_code,
        symbol=symbol,
        name=name,
        market=market,
        exchange="TEST",
        asset_type=asset_type,
        currency=currency,
        timezone="America/New_York",
        industry=industry,
    )
    session.add(stock)
    return stock


def test_market_overview_and_stock_detail(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        industry = Industry(taxonomy="GICS", code="45", name="Technology")
        index = add_stock(
            session,
            canonical_code="US:INDEX:^GSPC",
            symbol="^GSPC",
            name="S&P 500",
            market="US",
            asset_type="index",
        )
        stock = add_stock(
            session,
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            industry=industry,
        )
        add_price(session, index, 23, "6000")
        add_price(session, index, 24, "6060")
        add_price(session, stock, 23, "200")
        add_price(session, stock, 24, "204")
        session.commit()

        service = make_service(session)
        overview = service.market_overview()
        detail = service.stock_detail(
            stock.id,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 30),
        )

        assert len(overview) == 1
        assert overview[0].date == date(2026, 7, 24)
        assert overview[0].change_pct == 0.01
        assert detail is not None
        assert detail.industry == "Technology"
        assert detail.latest is not None
        assert detail.latest.close == Decimal("204.000000")
        assert detail.period_change_pct == 0.02


def test_portfolio_snapshot_and_risk(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        industry = Industry(taxonomy="GICS", code="45", name="Technology")
        apple = add_stock(
            session,
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            industry=industry,
        )
        microsoft = add_stock(
            session,
            canonical_code="US:XNAS:MSFT",
            symbol="MSFT",
            name="Microsoft",
            market="US",
            industry=industry,
        )
        for day, apple_close, microsoft_close in (
            (20, "200", "500"),
            (21, "202", "505"),
            (22, "201", "510"),
            (23, "205", "508"),
            (24, "208", "515"),
        ):
            add_price(session, apple, day, apple_close)
            add_price(session, microsoft, day, microsoft_close)
        portfolio = Portfolio(
            name="Core",
            base_currency="USD",
            cash_balance=Decimal("1000"),
        )
        session.add(portfolio)
        session.flush()
        session.add_all(
            [
                PortfolioPosition(
                    portfolio=portfolio,
                    stock=apple,
                    as_of_date=date(2026, 7, 24),
                    quantity=Decimal("10"),
                    average_cost=Decimal("190"),
                ),
                PortfolioPosition(
                    portfolio=portfolio,
                    stock=microsoft,
                    as_of_date=date(2026, 7, 24),
                    quantity=Decimal("2"),
                    average_cost=Decimal("480"),
                ),
            ]
        )
        session.commit()

        service = make_service(session)
        snapshot = service.portfolio_snapshot(portfolio.id)
        risk = service.portfolio_risk(
            portfolio.id,
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 24),
        )

        assert snapshot is not None
        assert snapshot.valuation_complete
        assert snapshot.invested_value == Decimal("3110.00000000000000")
        assert snapshot.total_value == Decimal("4110.00000000000000")
        assert len(snapshot.positions) == 2
        assert risk is not None
        assert risk.available
        assert risk.metrics is not None
        assert risk.metrics.observations == 4


def test_multicurrency_portfolio_refuses_cross_currency_risk(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        tencent = add_stock(
            session,
            canonical_code="HK:XHKG:00700",
            symbol="00700",
            name="Tencent",
            market="HK",
            currency="HKD",
        )
        add_price(session, tencent, 24, "500")
        portfolio = Portfolio(
            name="Global",
            base_currency="USD",
            cash_balance=Decimal("1000"),
        )
        session.add(portfolio)
        session.flush()
        session.add(
            PortfolioPosition(
                portfolio=portfolio,
                stock=tencent,
                as_of_date=date(2026, 7, 24),
                quantity=Decimal("10"),
            )
        )
        session.commit()

        service = make_service(session)
        snapshot = service.portfolio_snapshot(portfolio.id)
        risk = service.portfolio_risk(
            portfolio.id,
            start_date=date(2026, 7, 20),
            end_date=date(2026, 7, 24),
        )

        assert snapshot is not None
        assert not snapshot.valuation_complete
        assert {total.currency for total in snapshot.currency_totals} == {"HKD", "USD"}
        assert risk is not None
        assert not risk.available
        assert "汇率" in (risk.reason or "")
