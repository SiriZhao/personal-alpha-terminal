from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    FxRate,
    Industry,
    Portfolio,
    PortfolioPosition,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    PortfolioStressResult,
    Price,
    Stock,
)
from personal_alpha_terminal.portfolio.repository import PortfolioRiskRepository
from personal_alpha_terminal.portfolio.schemas import StressScenario
from personal_alpha_terminal.portfolio.service import PortfolioRiskService


def add_price(session: Session, stock: Stock, day: date, close: float) -> None:
    value = Decimal(str(close))
    session.add(
        Price(
            stock=stock,
            trade_date=day,
            open=value,
            high=value,
            low=value,
            close=value,
            adjusted_close=value,
            volume=1_000_000,
            source=("akshare" if stock.market == "A" else "yahoo_finance"),
        )
    )


def test_portfolio_risk_and_stress_are_persisted_and_restored(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        technology = Industry(taxonomy="GICS", code="45", name="Technology")
        stock = Stock(
            canonical_code="US:TEST:NVDA",
            symbol="NVDA",
            name="NVIDIA",
            market="US",
            exchange="TEST",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
            industry=technology,
        )
        etf = Stock(
            canonical_code="A:TEST:510300",
            symbol="510300",
            name="CSI 300 ETF",
            market="A",
            exchange="TEST",
            asset_type="etf",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        benchmark = Stock(
            canonical_code="US:TEST:NDX",
            symbol="NDX",
            name="NASDAQ 100",
            market="US",
            exchange="TEST",
            asset_type="index",
            currency="USD",
            timezone="America/New_York",
        )
        session.add_all([stock, etf, benchmark])
        portfolio = Portfolio(
            name="Cross Currency",
            base_currency="CNY",
            cash_balance=Decimal("10000"),
        )
        session.add(portfolio)
        session.flush()
        start = date(2025, 1, 1)
        stock_close = 100.0
        etf_close = 4.0
        benchmark_close = 1000.0
        for offset in range(100):
            day = start + timedelta(days=offset)
            benchmark_return = 0.006 if offset % 2 else -0.002
            if offset:
                benchmark_close *= 1 + benchmark_return
                stock_close *= 1 + 1.3 * benchmark_return
                etf_close *= 1 + 0.4 * benchmark_return
            add_price(session, stock, day, stock_close)
            add_price(session, etf, day, etf_close)
            add_price(session, benchmark, day, benchmark_close)
            session.add(
                FxRate(
                    base_currency="USD",
                    quote_currency="CNY",
                    rate_date=day,
                    rate=Decimal("7.2"),
                    source="test",
                )
            )
        as_of = start + timedelta(days=99)
        session.add_all(
            [
                PortfolioPosition(
                    portfolio=portfolio,
                    stock=stock,
                    as_of_date=as_of,
                    quantity=Decimal("10"),
                    average_cost=Decimal("80"),
                ),
                PortfolioPosition(
                    portfolio=portfolio,
                    stock=etf,
                    as_of_date=as_of,
                    quantity=Decimal("1000"),
                    average_cost=Decimal("3.5"),
                ),
            ]
        )
        session.commit()

        settings = Settings(
            _env_file=None,
            portfolio_risk_minimum_observations=60,
            portfolio_fx_max_staleness_days=3,
        )
        service = PortfolioRiskService(PortfolioRiskRepository(session), settings)
        analysis = service.run(
            portfolio_id=portfolio.id,
            benchmark_stock_id=benchmark.id,
            start_date=start,
            end_date=as_of,
            scenarios=(
                StressScenario(
                    name="NASDAQ -30 / USD +20",
                    benchmark_shock=-0.30,
                    currency_shocks={"USD": 0.20},
                ),
            ),
        )
        session.commit()

        restored = service.latest(portfolio.id)
        assert restored is not None
        assert restored.risk.run_id == analysis.risk.run_id
        assert restored.risk.total_value == pytest.approx(analysis.risk.total_value)
        assert len(restored.risk.positions) == 2
        assert restored.stress_tests[0].pnl_percent == pytest.approx(
            analysis.stress_tests[0].pnl_percent
        )
        assert session.scalar(select(func.count(PortfolioRiskRun.id))) == 1
        assert session.scalar(select(func.count(PortfolioRiskMetric.id))) == 1
        assert session.scalar(select(func.count(PortfolioStressResult.id))) == 1
