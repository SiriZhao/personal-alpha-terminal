from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    Portfolio,
    PortfolioTransaction,
    Price,
    ResearchReport,
    Stock,
)
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)
from personal_alpha_terminal.portfolio.management_schemas import TransactionDraft
from personal_alpha_terminal.portfolio.management_service import PortfolioManagementService
from personal_alpha_terminal.reports.service import ResearchReportService


def timestamp(day: date, hour: int = 20) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=UTC)


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
            source="yahoo_finance",
            provider="test",
            event_time=timestamp(day),
            available_time=timestamp(day, 21),
        )
    )


def draft(
    kind: str,
    day: date,
    *,
    stock_id: int | None = None,
    quantity: float | None = None,
    price: float | None = None,
    cash: float | None = None,
    fee: float = 0,
    external_id: str,
) -> TransactionDraft:
    return TransactionDraft(
        transaction_type=kind,
        trade_date=day,
        settlement_date=day,
        currency="USD",
        fx_rate_to_base=1,
        event_time=timestamp(day, 15),
        available_time=timestamp(day, 16),
        stock_id=stock_id,
        quantity=quantity,
        unit_price=price,
        cash_amount=cash,
        fee_amount=fee,
        source="broker_test",
        external_id=external_id,
    )


def test_transaction_to_report_flow_is_idempotent_and_auditable(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    start = date(2025, 1, 2)
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:TEST:EQ",
            symbol="EQ",
            name="Equity",
            market="US",
            exchange="TEST",
            asset_type="stock",
            currency="USD",
            timezone="America/New_York",
        )
        bond = Stock(
            canonical_code="US:TEST:BOND",
            symbol="BOND",
            name="Treasury Bond",
            market="US",
            exchange="TEST",
            asset_type="bond",
            currency="USD",
            timezone="America/New_York",
        )
        benchmark = Stock(
            canonical_code="US:TEST:SPY",
            symbol="SPY",
            name="S&P 500 ETF",
            market="US",
            exchange="TEST",
            asset_type="etf",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Real Ledger", base_currency="USD")
        session.add_all([stock, bond, benchmark, portfolio])
        session.flush()
        stock_price = 100.0
        bond_price = 100.0
        benchmark_price = 100.0
        for offset in range(90):
            day = start + timedelta(days=offset)
            if offset:
                market_return = 0.003 if offset % 2 else -0.001
                benchmark_price *= 1 + market_return
                stock_price *= 1 + market_return * 1.1
                bond_price *= 1 + market_return * 0.15
            add_price(session, stock, day, stock_price)
            add_price(session, bond, day, bond_price)
            add_price(session, benchmark, day, benchmark_price)
        settings = Settings(
            _env_file=None,
            portfolio_risk_minimum_observations=60,
            portfolio_price_max_staleness_days=2,
            portfolio_rebalance_drift_threshold=0.01,
            portfolio_minimum_rebalance_value=10,
        )
        service = PortfolioManagementService(
            PortfolioManagementRepository(session),
            ResearchReportService(session),
            settings,
        )
        deposit = draft("deposit", start, cash=10_000, external_id="cash-1")
        first = service.record_transaction(portfolio_id=portfolio.id, draft=deposit)
        session.commit()
        repeated = service.record_transaction(portfolio_id=portfolio.id, draft=deposit)
        assert first.id == repeated.id
        with pytest.raises(ValueError, match="different payload"):
            service.record_transaction(
                portfolio_id=portfolio.id,
                draft=draft("deposit", start, cash=9_999, external_id="cash-1"),
            )
        service.record_transaction(
            portfolio_id=portfolio.id,
            draft=draft(
                "buy",
                start,
                stock_id=stock.id,
                quantity=40,
                price=100,
                fee=4,
                external_id="buy-eq",
            ),
        )
        service.record_transaction(
            portfolio_id=portfolio.id,
            draft=draft(
                "buy",
                start,
                stock_id=bond.id,
                quantity=20,
                price=100,
                fee=2,
                external_id="buy-bond",
            ),
        )
        service.record_transaction(
            portfolio_id=portfolio.id,
            draft=draft(
                "dividend",
                start + timedelta(days=30),
                stock_id=stock.id,
                cash=40,
                external_id="dividend-eq",
            ),
        )
        service.set_allocation_targets(
            portfolio_id=portfolio.id,
            effective_date=start,
            targets=(
                (stock.id, None, 0.50, "Core equity"),
                (bond.id, None, 0.30, "Defensive"),
                (None, "USD", 0.20, "Liquidity"),
            ),
        )
        output = tmp_path / "PORTFOLIO_REPORT.md"
        result, report = service.generate_report(
            portfolio_id=portfolio.id,
            benchmark_stock_id=benchmark.id,
            start_date=start,
            end_date=start + timedelta(days=89),
            output_path=output,
        )
        session.commit()

        assert result.total_value > 0
        assert result.asset_class_exposure["bond"] > 0
        assert result.beta is not None
        assert result.alpha is not None
        assert report.report_type == "portfolio_management"
        markdown = output.read_text(encoding="utf-8")
        assert "不会自动交易" in markdown
        assert "data_fingerprint:" in markdown
        assert "Jensen Alpha" in markdown
        assert session.scalar(select(func.count(PortfolioTransaction.id))) == 4
        assert session.scalar(select(func.count(ResearchReport.id))) == 1


def test_transaction_validation_rejects_future_availability(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        portfolio = Portfolio(name="Validation", base_currency="USD")
        session.add(portfolio)
        session.flush()
        service = PortfolioManagementService(
            PortfolioManagementRepository(session),
            ResearchReportService(session),
            Settings(_env_file=None),
        )
        day = date(2025, 1, 2)
        invalid = TransactionDraft(
            transaction_type="deposit",
            trade_date=day,
            settlement_date=day,
            currency="USD",
            fx_rate_to_base=1,
            event_time=timestamp(day, 16),
            available_time=timestamp(day, 15),
            cash_amount=100,
        )

        with pytest.raises(ValueError, match="available_time"):
            service.record_transaction(portfolio_id=portfolio.id, draft=invalid)
