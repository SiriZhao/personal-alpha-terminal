from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.core.data_timestamps import (
    DataTimestamps,
    daily_bar_timestamps,
)
from personal_alpha_terminal.core.market_time import market_close_utc


def test_three_time_contract_rejects_future_availability_and_ingestion() -> None:
    event_time = datetime(2026, 7, 31, 8, tzinfo=UTC)
    with pytest.raises(ValueError, match="available_time"):
        DataTimestamps(
            event_time=event_time,
            available_time=event_time - timedelta(seconds=1),
            ingested_time=event_time,
        )
    with pytest.raises(ValueError, match="ingested_time"):
        DataTimestamps(
            event_time=event_time,
            available_time=event_time + timedelta(minutes=1),
            ingested_time=event_time,
        )


def test_daily_bar_availability_is_after_market_close_and_cutoff_is_enforced() -> None:
    timestamps = daily_bar_timestamps(date(2026, 7, 31), "A")

    assert timestamps.available_time > timestamps.event_time
    with pytest.raises(ValueError, match="not available"):
        timestamps.assert_available(timestamps.event_time)
    timestamps.assert_available(timestamps.available_time)


def test_hk_daily_event_time_waits_for_latest_closing_auction_endpoint() -> None:
    close = market_close_utc(date(2026, 7, 31), "HK")

    assert close.hour == 8
    assert close.minute == 10
