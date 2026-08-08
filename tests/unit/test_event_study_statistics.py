from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.analysis.event_study.schemas import (
    EventMatch,
    EventOutcome,
    InstrumentOption,
    PriceBar,
)
from personal_alpha_terminal.analysis.event_study.statistics import (
    aggregate_outcomes,
    calculate_outcomes,
)


def test_outcomes_use_target_trading_days_and_exclude_incomplete_horizons() -> None:
    event = EventMatch(
        date=date(2026, 1, 2),
        trigger_value=0.1,
        reference_value=0.08,
        details={},
    )
    target = InstrumentOption(id=2, symbol="AMD", name="AMD", market="US")
    target_bars = (
        PriceBar(date=date(2026, 1, 2), close=100, volume=1),
        PriceBar(date=date(2026, 1, 5), close=110, volume=1),
        PriceBar(date=date(2026, 1, 6), close=99, volume=1),
    )

    outcomes = calculate_outcomes(
        [event],
        target,
        target_bars,
        trigger_market="US",
        horizons=(1, 2, 3),
        win_threshold=0.05,
    )

    assert len(outcomes) == 2
    assert outcomes[0].horizon_date == date(2026, 1, 5)
    assert outcomes[0].forward_return == pytest.approx(0.1)
    assert outcomes[1].forward_return == pytest.approx(-0.01)
    assert outcomes[1].max_upside == pytest.approx(0.1)
    assert outcomes[1].max_drawdown == pytest.approx(-0.1)
    assert not outcomes[1].is_win


def test_statistics_keep_positive_probability_distinct_from_win_rate() -> None:
    target = InstrumentOption(id=2, symbol="AMD", name="AMD", market="US")
    events = [
        EventMatch(
            date=date(2026, 1, 1) + timedelta(days=index),
            trigger_value=0.1,
            reference_value=0.08,
            details={},
        )
        for index in range(2)
    ]
    target_bars = tuple(
        PriceBar(
            date=date(2026, 1, 1) + timedelta(days=index),
            close=close,
            volume=1,
        )
        for index, close in enumerate((100, 103, 107, 108))
    )
    outcomes = calculate_outcomes(
        events,
        target,
        target_bars,
        trigger_market="US",
        horizons=(1,),
        win_threshold=0.035,
    )
    statistics = aggregate_outcomes(outcomes)

    assert statistics[0].sample_size == 2
    assert statistics[0].positive_probability == 1
    assert statistics[0].win_rate == 0.5
    assert not statistics[0].meets_minimum
    assert statistics[0].positive_probability_lower is None
    assert statistics[0].average_return_lower is None


def test_event_intervals_use_wilson_and_reproducible_block_bootstrap() -> None:
    target = InstrumentOption(id=2, symbol="AMD", name="AMD", market="US")
    outcomes = tuple(
        EventOutcome(
            event=EventMatch(
                date=date(2020, 1, 1) + timedelta(days=index),
                trigger_value=0.1,
                reference_value=0.08,
                details={},
            ),
            target=target,
            horizon_days=5,
            baseline_date=date(2020, 1, 1) + timedelta(days=index),
            horizon_date=date(2020, 1, 6) + timedelta(days=index),
            forward_return=0.02 if index % 3 else -0.01,
            max_upside=0.03,
            max_drawdown=-0.02,
            is_win=index % 3 != 0,
        )
        for index in range(40)
    )

    first = aggregate_outcomes(outcomes, bootstrap_resamples=1_000, random_seed=7)[0]
    second = aggregate_outcomes(outcomes, bootstrap_resamples=1_000, random_seed=7)[0]

    assert first.meets_minimum
    assert first.positive_probability_lower is not None
    assert first.positive_probability_lower < first.positive_probability
    assert first.positive_probability_upper is not None
    assert first.positive_probability_upper > first.positive_probability
    assert first.average_return_lower == second.average_return_lower
    assert first.average_return_upper == second.average_return_upper
    assert first.average_return_lower is not None
    assert first.average_return_lower < first.average_return < first.average_return_upper


def test_cross_market_event_uses_only_closes_available_when_trigger_is_known() -> None:
    event = EventMatch(
        date=date(2026, 1, 5),
        trigger_value=0.1,
        reference_value=0.08,
        details={},
    )
    us_target = InstrumentOption(
        id=2,
        symbol="AMD",
        name="AMD",
        market="US",
    )
    bars = (
        PriceBar(date=date(2026, 1, 2), close=100, volume=1),
        PriceBar(date=date(2026, 1, 5), close=110, volume=1),
        PriceBar(date=date(2026, 1, 6), close=121, volume=1),
    )

    outcomes = calculate_outcomes(
        [event],
        us_target,
        bars,
        trigger_market="A",
        horizons=(1,),
        win_threshold=0,
    )

    assert outcomes[0].baseline_date == date(2026, 1, 2)
    assert outcomes[0].horizon_date == date(2026, 1, 5)
    assert outcomes[0].forward_return == pytest.approx(0.1)


def test_event_availability_delay_prevents_using_an_already_closed_target() -> None:
    event = EventMatch(
        date=date(2026, 1, 5),
        trigger_value=0.1,
        reference_value=0.08,
        details={},
        available_time=datetime(2026, 1, 5, 22, 0, tzinfo=UTC),
    )
    target = InstrumentOption(id=2, symbol="AMD", name="AMD", market="US")
    bars = (
        PriceBar(
            date=date(2026, 1, 2),
            close=100,
            volume=1,
            available_time=datetime(2026, 1, 2, 21, 30, tzinfo=UTC),
        ),
        PriceBar(
            date=date(2026, 1, 5),
            close=110,
            volume=1,
            available_time=datetime(2026, 1, 5, 21, 30, tzinfo=UTC),
        ),
        PriceBar(
            date=date(2026, 1, 6),
            close=121,
            volume=1,
            available_time=datetime(2026, 1, 6, 21, 30, tzinfo=UTC),
        ),
    )

    outcomes = calculate_outcomes(
        [event],
        target,
        bars,
        trigger_market="A",
        horizons=(1,),
        win_threshold=0,
    )

    assert outcomes[0].baseline_date == date(2026, 1, 5)
    assert outcomes[0].horizon_date == date(2026, 1, 6)
    assert outcomes[0].forward_return == pytest.approx(0.1)
