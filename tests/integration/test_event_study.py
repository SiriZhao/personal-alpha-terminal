from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.models import (
    EventDefinition,
    EventOccurrence,
    EventStudyObservation,
    EventStudyRun,
    EventStudyStatistic,
    Price,
    Stock,
)


def add_stock(session: Session, symbol: str) -> Stock:
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    return stock


def add_prices(
    session: Session,
    stock: Stock,
    closes: list[float],
    *,
    start: date,
) -> None:
    trade_dates: list[date] = []
    candidate = start
    while len(trade_dates) < len(closes):
        if candidate.weekday() < 5:
            trade_dates.append(candidate)
        candidate += timedelta(days=1)
    for trade_date, close in zip(trade_dates, closes, strict=True):
        value = Decimal(str(close))
        timestamps = daily_bar_timestamps(trade_date, "US")
        session.add(
            Price(
                stock=stock,
                trade_date=trade_date,
                open=value,
                high=value,
                low=value,
                close=value,
                adjusted_close=value,
                adjustment_method="point_in_time_total_return",
                volume=1_000_000,
                source="yahoo_finance",
                event_time=timestamps.event_time,
                available_time=timestamps.available_time,
                ingested_at=timestamps.ingested_time,
            )
        )


def make_service(session: Session) -> EventStudyService:
    return EventStudyService(
        EventStudyRepository(session),
        Settings(
            _env_file=None,
            event_study_horizons="1,3,5,10,20",
            event_study_max_targets=10,
        ),
    )


def test_event_study_persists_cross_asset_outcomes_and_statistics(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        trigger = add_stock(session, "NVDA")
        rising = add_stock(session, "AMD")
        falling = add_stock(session, "TSM")
        trigger_closes = [100.0] * 35
        trigger_closes[5:] = [110.0] * 30
        trigger_closes[15:] = [121.0] * 20
        add_prices(session, trigger, trigger_closes, start=date(2026, 1, 1))
        add_prices(
            session,
            rising,
            [100 * (1.01**index) for index in range(35)],
            start=date(2026, 1, 1),
        )
        add_prices(
            session,
            falling,
            [100 * (0.99**index) for index in range(35)],
            start=date(2026, 1, 1),
        )
        session.commit()

        service = make_service(session)
        definition = service.create_definition(
            name="Single-day gain",
            description="Daily return above 8%",
            rule_type="price_return",
            parameters={"threshold": 0.08, "direction": "above"},
        )
        result = service.run(
            definition_id=definition.id,
            trigger_stock_id=trigger.id,
            target_stock_ids=(rising.id, falling.id),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 2, 18),
        )
        session.commit()

        assert len(result.occurrences) == 2
        assert len(result.statistics) == 10
        five_day = {
            item.target.symbol: item for item in result.statistics if item.horizon_days == 5
        }
        assert five_day["AMD"].sample_size == 2
        assert five_day["AMD"].positive_probability == 1
        assert five_day["TSM"].positive_probability == 0
        twenty_day = [item for item in result.statistics if item.horizon_days == 20]
        assert {item.sample_size for item in twenty_day} == {1}

        assert session.scalar(select(func.count(EventOccurrence.id))) == 2
        assert session.scalar(select(func.count(EventStudyObservation.id))) == 18
        assert session.scalar(select(func.count(EventStudyStatistic.id))) == 10
        stored_run = session.get(EventStudyRun, result.run_id)
        assert stored_run is not None
        assert stored_run.status == "completed"
        assert stored_run.parameters["right_censoring"] == ("exclude_incomplete_horizon")
        assert stored_run.parameters["deduplication_method"] == (
            "candidate_episode_cooldown"
        )
        assert stored_run.parameters["probability_interval_method"] == "wilson_score"
        assert stored_run.parameters["price_adjustment_policy"] == (
            "point_in_time_total_return"
        )
        stored_statistics = list(session.scalars(select(EventStudyStatistic)))
        assert all(not item.meets_minimum for item in stored_statistics)
        assert all(item.positive_probability_lower is None for item in stored_statistics)

        restored = service.latest()
        assert restored is not None
        assert restored.run_id == result.run_id
        assert len(restored.statistics) == 10


def test_event_study_rejects_provider_current_snapshot_adjustment(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        trigger = add_stock(session, "LEAK")
        add_prices(session, trigger, [100.0, 110.0], start=date(2026, 1, 5))
        session.flush()
        price = session.scalar(select(Price).where(Price.stock == trigger))
        assert price is not None
        price.adjustment_method = "yahoo_provider_total_return_current_snapshot"
        session.commit()

        with pytest.raises(ValueError, match="corporate-action leakage"):
            EventStudyRepository(session).load_bars(
                trigger.id,
                end_date=date(2026, 1, 9),
            )


def test_event_definition_is_versioned_without_mutating_history(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = make_service(session)
        first = service.create_definition(
            name="Volume event",
            description=None,
            rule_type="volume_spike",
            parameters={"lookback_days": 20, "multiplier": 2.0},
        )
        second = service.create_definition(
            name="Volume event",
            description=None,
            rule_type="volume_spike",
            parameters={"lookback_days": 20, "multiplier": 3.0},
        )
        session.commit()

        first_model = session.get(EventDefinition, first.id)
        assert first.version == 1
        assert second.version == 2
        assert first_model is not None
        assert not first_model.is_active
        assert [item.id for item in service.list_definitions()] == [second.id]
