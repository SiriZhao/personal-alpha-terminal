"""Lifecycle tests for the real portfolio ledger.

Covers Part 2 requirements 2/5/11: interactive-init service entry, atomic
persistence, restart recovery, and rejection of invalid user input.  All tests
use an isolated in-memory (or temporary file) SQLite database; they never touch
the production database.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import build_engine, build_session_factory
from personal_alpha_terminal.models import Base, Portfolio, PortfolioPosition, Stock
from personal_alpha_terminal.portfolio.portfolio_validation import (
    PortfolioValidationError,
    ValidatedPosition,
    validate_positions,
)


def _seed_stock(session: Session, symbol: str) -> Stock:
    stock = Stock(
        canonical_code=f"US:XNAS:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    session.flush()
    return stock


def test_create_portfolio_with_positions_persists_and_recovers(tmp_path: Path) -> None:
    db_path = tmp_path / "portfolio.db"
    engine = build_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory.begin() as session:
        _seed_stock(session, "AAPL")
        _seed_stock(session, "MSFT")

    service = ApplicationService(factory, Settings(database_url="sqlite://"))
    portfolio_id, warnings = service.create_portfolio_with_positions(
        name="Part 2 Ledger",
        cash_balance=Decimal("50000"),
        positions=(
            ValidatedPosition("AAPL", Decimal("10"), Decimal("150")),
            ValidatedPosition("MSFT", Decimal("5"), None),
        ),
        as_of_date=date(2026, 8, 7),
    )
    assert warnings == ()
    engine.dispose()

    # Restart: reopen the database from disk and verify the ledger survived.
    reopened = build_engine(f"sqlite:///{db_path}")
    with Session(reopened) as session:
        portfolio = session.get(Portfolio, portfolio_id)
        assert portfolio is not None
        assert portfolio.cash_balance == Decimal("50000")
        assert portfolio.source == "cli-manual"
        assert portfolio.schema_version == "portfolio-v1"
        positions = session.scalars(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_id == portfolio_id
            )
        ).all()
        assert {(p.quantity, p.average_cost) for p in positions} == {
            (Decimal("10"), Decimal("150")),
            (Decimal("5"), None),
        }
    reopened.dispose()


def test_create_portfolio_rejects_negative_cash(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    service = ApplicationService(factory, Settings(database_url="sqlite://"))
    with pytest.raises(PortfolioValidationError):
        service.create_portfolio_with_positions(name="Bad", cash_balance=-1)
    with Session(engine) as session:
        assert session.scalar(select(Portfolio)) is None
    engine.dispose()


def test_create_portfolio_rejects_nan_and_inf_cash(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    service = ApplicationService(factory, Settings(database_url="sqlite://"))
    for bad in (float("nan"), float("inf")):
        with pytest.raises(PortfolioValidationError):
            service.create_portfolio_with_positions(name="Bad", cash_balance=bad)
    with Session(engine) as session:
        assert session.scalar(select(Portfolio)) is None
    engine.dispose()


def test_position_batch_rejects_invalid_entries_before_any_write() -> None:
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "-5", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "nan", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "inf", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("AAPL", "1", None), ("aapl", "2", None)])
    with pytest.raises(PortfolioValidationError):
        validate_positions([("", "1", None)])


def test_duplicate_portfolio_name_is_rejected(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    service = ApplicationService(factory, Settings(database_url="sqlite://"))
    service.create_portfolio_with_positions(name="Core", cash_balance=0)
    with pytest.raises(ValueError):
        service.create_portfolio_with_positions(name="Core", cash_balance=10)
    engine.dispose()


def test_import_csv_rejects_negative_and_non_finite_shares(tmp_path: Path) -> None:
    csv_path = tmp_path / "positions.csv"
    csv_path.write_text("ticker,shares\nAAPL,-5\n", encoding="utf-8")
    service = ApplicationService(
        build_session_factory(build_engine("sqlite://")),
        Settings(database_url="sqlite://"),
    )
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)

    csv_path.write_text("ticker,shares\nAAPL,nan\n", encoding="utf-8")
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)

    csv_path.write_text("ticker,shares\nAAPL,inf\n", encoding="utf-8")
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)


def test_import_csv_rejects_duplicate_and_empty_ticker(tmp_path: Path) -> None:
    csv_path = tmp_path / "positions.csv"
    csv_path.write_text("ticker,shares\nAAPL,5\nAAPL,3\n", encoding="utf-8")
    service = ApplicationService(
        build_session_factory(build_engine("sqlite://")),
        Settings(database_url="sqlite://"),
    )
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)


def test_import_csv_rejects_corrupt_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "positions.csv"
    csv_path.write_bytes(b"\xff\xfe\x00\x01not-a-csv")
    service = ApplicationService(
        build_session_factory(build_engine("sqlite://")),
        Settings(database_url="sqlite://"),
    )
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)


def test_import_csv_requires_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "positions.csv"
    csv_path.write_text("", encoding="utf-8")
    service = ApplicationService(
        build_session_factory(build_engine("sqlite://")),
        Settings(database_url="sqlite://"),
    )
    with pytest.raises(ValueError):
        service.preview_portfolio_csv(source=csv_path)
