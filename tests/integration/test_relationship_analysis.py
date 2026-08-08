from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.relationships.repository import RelationshipRepository
from personal_alpha_terminal.analysis.relationships.service import RelationshipAnalysisService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    Industry,
    Price,
    RelationshipAnalysisRun,
    RelationshipAnomaly,
    RelationshipCorrelation,
    Stock,
)


def add_instrument(
    session: Session,
    *,
    symbol: str,
    asset_type: str = "stock",
    industry: Industry | None = None,
) -> Stock:
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        asset_type=asset_type,
        currency="USD",
        timezone="America/New_York",
        industry=industry,
    )
    session.add(stock)
    return stock


def add_return_history(
    session: Session,
    stock: Stock,
    returns: list[float],
    *,
    start: date,
) -> None:
    price = 100.0
    prices = [price]
    for daily_return in returns:
        price *= 1 + daily_return
        prices.append(price)
    for index, close in enumerate(prices):
        value = Decimal(str(close))
        trade_date = start + timedelta(days=index)
        session.add(
            Price(
                stock=stock,
                trade_date=trade_date,
                open=value,
                high=value,
                low=value,
                close=value,
                adjusted_close=value,
                volume=1_000_000,
                source="yahoo_finance",
                ingested_at=datetime.combine(trade_date, datetime.min.time(), UTC),
            )
        )


def make_service(session: Session) -> RelationshipAnalysisService:
    return RelationshipAnalysisService(
        RelationshipRepository(session),
        Settings(
            _env_file=None,
            relationship_rolling_windows="30,90,180",
            relationship_min_observations=20,
            relationship_baseline_window=90,
            relationship_current_window=30,
            relationship_change_threshold=0.35,
        ),
    )


def test_relationship_run_persists_matrix_rolling_and_anomaly(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        left = add_instrument(session, symbol="LEFT")
        right = add_instrument(session, symbol="RIGHT")
        alternating = [0.01 if index % 2 == 0 else -0.01 for index in range(120)]
        changed = [*alternating[:90], *[-value for value in alternating[90:]]]
        start = date(2026, 1, 1)
        add_return_history(session, left, alternating, start=start)
        add_return_history(session, right, changed, start=start)
        session.commit()

        service = make_service(session)
        result = service.run(
            universe_type="stock",
            entity_ids=(left.id, right.id),
            method="pearson",
            start_date=start + timedelta(days=1),
            end_date=start + timedelta(days=120),
        )
        session.commit()

        assert len(result.matrix) == 1
        assert {item.window_days for item in result.rolling} == {30, 90}
        assert len(result.anomalies) == 1
        assert result.anomalies[0].direction == "sign_flip"
        assert session.scalar(select(func.count(RelationshipCorrelation.id))) == (1 + 91 + 31)
        assert session.scalar(select(func.count(RelationshipAnomaly.id))) == 1
        stored_run = session.get(RelationshipAnalysisRun, result.run_id)
        assert stored_run is not None
        assert stored_run.status == "completed"
        assert stored_run.parameters["missing_data"] == ("pairwise_complete_no_forward_fill")

        restored = service.latest("stock", "pearson")
        assert restored is not None
        assert restored.run_id == result.run_id
        assert restored.anomalies[0].absolute_change == pytest.approx(2)


def test_industry_returns_are_equal_weighted(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        software = Industry(taxonomy="GICS", code="4510", name="Software")
        semis = Industry(taxonomy="GICS", code="4530", name="Semiconductors")
        software_a = add_instrument(session, symbol="SWA", industry=software)
        software_b = add_instrument(session, symbol="SWB", industry=software)
        semi = add_instrument(session, symbol="SEMI", industry=semis)
        start = date(2026, 1, 1)
        returns_a = [0.01 if index % 2 == 0 else -0.01 for index in range(30)]
        returns_b = [0.03 if index % 2 == 0 else -0.03 for index in range(30)]
        returns_semi = [0.02 if index % 2 == 0 else -0.02 for index in range(30)]
        add_return_history(session, software_a, returns_a, start=start)
        add_return_history(session, software_b, returns_b, start=start)
        add_return_history(session, semi, returns_semi, start=start)
        session.commit()

        repository = RelationshipRepository(session)
        series = repository.load_returns(
            "industry",
            (software.id, semis.id),
            start_date=start + timedelta(days=1),
            end_date=start + timedelta(days=30),
        )

        assert len(series) == 2
        assert series[0].values[0][1] == pytest.approx(0.02)
        assert series[1].values[0][1] == pytest.approx(0.02)
