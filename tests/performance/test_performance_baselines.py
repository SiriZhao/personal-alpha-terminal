from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter

import pytest

from personal_alpha_terminal.analysis.conditional_probability.statistics import (
    estimate_conditional_probability,
)
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.quality import DataQualityChecker
from personal_alpha_terminal.data.market_data.schemas import PriceBar


@pytest.mark.performance
def test_daily_bar_quality_gate_handles_five_thousand_rows_within_budget() -> None:
    bars: list[PriceBar] = []
    current = date(2000, 1, 3)
    while len(bars) < 5_000:
        if current.weekday() < 5:
            timestamps = daily_bar_timestamps(current, "US")
            bars.append(
                PriceBar(
                    symbol="PERF",
                    market="US",
                    date=current,
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100"),
                    volume=1_000_000,
                    event_time=timestamps.event_time,
                    available_time=timestamps.available_time,
                    ingested_time=timestamps.ingested_time,
                    open_tradable=True,
                )
            )
        current += timedelta(days=1)

    started = perf_counter()
    result = DataQualityChecker().validate(
        bars,
        expected_symbol="PERF",
        expected_market="US",
        start_date=bars[0].date,
        end_date=bars[-1].date,
    )
    elapsed = perf_counter() - started

    assert not result.has_errors
    assert len(result.bars) == 5_000
    assert elapsed < 10.0


@pytest.mark.performance
def test_bayesian_probability_estimator_handles_large_sample_within_budget() -> None:
    returns = tuple(0.01 if index % 3 else -0.01 for index in range(250_000))

    started = perf_counter()
    result = estimate_conditional_probability(
        returns,
        outcome_direction="up",
        outcome_threshold=0,
        minimum_sample_size=30,
        confidence_level=0.95,
    )
    elapsed = perf_counter() - started

    assert result.sample_size == 250_000
    assert result.posterior_probability is not None
    assert elapsed < 10.0
