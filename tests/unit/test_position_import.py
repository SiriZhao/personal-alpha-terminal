from datetime import date
from decimal import Decimal

from sqlalchemy import select

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import configure_database, init_database
from personal_alpha_terminal.models import Portfolio, PortfolioPosition, PortfolioTransaction, Stock
from personal_alpha_terminal.portfolio import PositionImportService, parse_position_csv


def test_schwab_snapshot_import_matches_security_master_and_never_creates_ledger() -> None:
    parsed = parse_position_csv(
        b"Symbol,Quantity,Market Value,Cost Basis,% of Account\n"
        b"AAPL,10,$2000,$1800,50%\n"
        b"UNKNOWN,5,$500,$400,10%\n"
    )
    settings = Settings(_env_file=None, database_url="sqlite://")
    engine, session_factory = configure_database(settings)
    init_database(engine)
    with session_factory() as session:
        stock = Stock(
            canonical_code="US:XNAS:AAPL",
            symbol="AAPL",
            name="Apple",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        portfolio = Portfolio(name="Core", base_currency="USD")
        session.add_all((stock, portfolio))
        session.flush()

        result = PositionImportService(session).import_snapshot(
            portfolio_id=portfolio.id,
            as_of_date=date(2026, 8, 1),
            parsed=parsed,
        )
        session.commit()

        position = session.scalar(select(PortfolioPosition))
        assert result.format_name == "charles_schwab_positions"
        assert result.imported_count == 1
        assert result.unmatched_symbols == ("UNKNOWN",)
        assert position is not None
        assert position.quantity == Decimal("10")
        assert position.average_cost == Decimal("180")
        assert session.scalar(select(PortfolioTransaction)) is None
