from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.conditional_probability.repository import (
    ConditionalProbabilityRepository,
)
from personal_alpha_terminal.analysis.conditional_probability.service import (
    ConditionalProbabilityService,
)
from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.models import (
    ConditionalProbabilityResult,
    ConditionalProbabilityRun,
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
) -> None:
    start = date(2026, 1, 1)
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


def make_settings(minimum_sample_size: int) -> Settings:
    return Settings(
        _env_file=None,
        event_study_horizons="1,5,20",
        conditional_probability_horizons="1,5,20",
        conditional_probability_minimum_sample_size=minimum_sample_size,
        conditional_probability_confidence_level=0.95,
    )


def test_conditional_probability_reuses_event_samples_and_persists_inference(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        trigger = add_stock(session, "NVDA")
        target = add_stock(session, "AMD")
        add_prices(
            session,
            trigger,
            [100, 110, 110, 121, 121, 133.1, 133.1, 146.41, 146.41, 146.41],
        )
        add_prices(
            session,
            target,
            [100, 100, 101, 100, 101, 100, 101, 100, 99, 99],
        )
        session.commit()

        settings = make_settings(3)
        event_service = EventStudyService(EventStudyRepository(session), settings)
        definition = event_service.create_definition(
            name="NVDA jump",
            description=None,
            rule_type="price_return",
            parameters={"threshold": 0.08, "direction": "above"},
        )
        service = ConditionalProbabilityService(
            ConditionalProbabilityRepository(session),
            settings,
        )
        study = service.run(
            definition_id=definition.id,
            trigger_stock_id=trigger.id,
            target_stock_ids=(target.id,),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 14),
            outcome_direction="up",
            horizons=(1,),
            cooldown_days=1,
        )
        session.commit()

        assert study.event_count == 4
        assert len(study.results) == 1
        estimate = study.results[0]
        assert estimate.sample_size == 4
        assert estimate.success_count == 3
        assert estimate.meets_minimum
        assert estimate.raw_probability == 0.75
        assert estimate.probability == pytest.approx(4 / 6)
        assert estimate.confidence_lower is not None
        assert estimate.confidence_upper is not None
        assert estimate.confidence_lower < estimate.probability
        assert estimate.confidence_upper > estimate.probability
        assert session.scalar(select(func.count(ConditionalProbabilityRun.id))) == 1
        assert session.scalar(select(func.count(ConditionalProbabilityResult.id))) == 1

        restored = service.latest()
        assert restored is not None
        assert restored.run_id == study.run_id
        assert restored.results[0].raw_probability == 0.75
        assert restored.results[0].probability == pytest.approx(4 / 6)

        stored_run = session.get(ConditionalProbabilityRun, study.run_id)
        assert stored_run is not None
        stored_run.parameters = {}
        session.commit()
        assert service.latest() is None


def test_minimum_sample_safeguard_persists_only_counts(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        trigger = add_stock(session, "TRIGGER")
        target = add_stock(session, "TARGET")
        add_prices(session, trigger, [100, 110, 110, 121, 121, 121])
        add_prices(session, target, [100, 100, 101, 100, 101, 101])
        session.commit()

        settings = make_settings(5)
        event_service = EventStudyService(EventStudyRepository(session), settings)
        definition = event_service.create_definition(
            name="Jump",
            description=None,
            rule_type="price_return",
            parameters={"threshold": 0.08, "direction": "above"},
        )
        service = ConditionalProbabilityService(
            ConditionalProbabilityRepository(session),
            settings,
        )
        study = service.run(
            definition_id=definition.id,
            trigger_stock_id=trigger.id,
            target_stock_ids=(target.id,),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 8),
            outcome_direction="up",
            horizons=(1,),
            cooldown_days=1,
        )
        session.commit()

        estimate = study.results[0]
        assert estimate.sample_size == 2
        assert not estimate.meets_minimum
        assert estimate.probability is None
        assert estimate.average_return is None
        stored = session.scalar(select(ConditionalProbabilityResult))
        assert stored is not None
        assert stored.success_count == 2
        assert stored.probability is None
        assert stored.confidence_lower is None
