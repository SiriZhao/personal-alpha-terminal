from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.schemas import PriceBar
from personal_alpha_terminal.data.market_data_quality.adjustments import (
    UnsafeAdjustmentError,
    assert_adjustment_safe,
    price_for_mode,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    AdjustmentMode,
    PriceUseCase,
)


def make_bar() -> PriceBar:
    timestamps = daily_bar_timestamps(date(2026, 7, 30), "A")
    return PriceBar(
        symbol="000001",
        market="A",
        date=date(2026, 7, 30),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=100,
        event_time=timestamps.event_time,
        available_time=timestamps.available_time,
        ingested_time=timestamps.ingested_time,
        adjusted_close=Decimal("9"),
        forward_adjusted_close=Decimal("9"),
        backward_adjusted_close=Decimal("12"),
    )


def test_adjustment_modes_select_explicit_series() -> None:
    source = make_bar()

    assert price_for_mode(source, AdjustmentMode.RAW) == Decimal("10")
    assert price_for_mode(source, AdjustmentMode.FORWARD) == Decimal("9")
    assert price_for_mode(source, AdjustmentMode.BACKWARD) == Decimal("12")
    assert price_for_mode(source, AdjustmentMode.PROVIDER_TOTAL_RETURN) == Decimal("9")


def test_backtest_rejects_current_provider_adjusted_history() -> None:
    with pytest.raises(UnsafeAdjustmentError, match="not safe for backtest"):
        assert_adjustment_safe(PriceUseCase.BACKTEST, AdjustmentMode.FORWARD)
    with pytest.raises(UnsafeAdjustmentError, match="not safe for backtest"):
        assert_adjustment_safe(
            PriceUseCase.BACKTEST,
            AdjustmentMode.PROVIDER_TOTAL_RETURN,
        )

    assert_adjustment_safe(
        PriceUseCase.BACKTEST,
        AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN,
    )


def test_missing_adjusted_series_fails_closed() -> None:
    with pytest.raises(UnsafeAdjustmentError, match="unavailable"):
        price_for_mode(
            replace(make_bar(), backward_adjusted_close=None),
            AdjustmentMode.BACKWARD,
        )
