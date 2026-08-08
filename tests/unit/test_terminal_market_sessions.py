from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from personal_alpha_terminal.terminal.market_sessions import (
    MarketSession,
    MarketSessionCalendar,
    MarketStructureVersion,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
def calendar() -> MarketSessionCalendar:
    return MarketSessionCalendar(
        nasdaq_23h_enabled=True,
        nasdaq_23h_effective_date=date(2026, 1, 1),
    )


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        ((4, 0), MarketSession.PREMARKET),
        ((9, 30), MarketSession.REGULAR),
        ((16, 0), MarketSession.POSTMARKET),
        ((20, 0), MarketSession.MAINTENANCE),
        ((21, 0), MarketSession.NIGHT),
        ((23, 0), MarketSession.NIGHT),
        ((0, 30), MarketSession.NIGHT),
    ],
)
def test_23h_session_boundaries(calendar: MarketSessionCalendar, clock, expected) -> None:
    value = datetime(2026, 8, 10, *clock, tzinfo=ET)
    assert calendar.classify(value).session is expected


def test_21_et_belongs_to_next_trade_date(calendar: MarketSessionCalendar) -> None:
    state = calendar.classify(datetime(2026, 8, 7, 23, 0, tzinfo=ET))
    assert state.trade_date == date(2026, 8, 10)
    assert state.session is MarketSession.CLOSED
    assert not state.is_execution_session


def test_sunday_night_opens_for_monday_trade_date(calendar: MarketSessionCalendar) -> None:
    state = calendar.classify(datetime(2026, 8, 9, 23, 0, tzinfo=ET))
    assert state.session is MarketSession.NIGHT
    assert state.trade_date == date(2026, 8, 10)


def test_saturday_night_is_closed(calendar: MarketSessionCalendar) -> None:
    state = calendar.classify(datetime(2026, 8, 8, 23, 0, tzinfo=ET))
    assert state.session is MarketSession.CLOSED


def test_after_midnight_keeps_calendar_trade_date(calendar: MarketSessionCalendar) -> None:
    state = calendar.classify(datetime(2026, 8, 10, 0, 30, tzinfo=ET))
    assert state.calendar_date == date(2026, 8, 10)
    assert state.trade_date == date(2026, 8, 10)


def test_legacy_structure_does_not_invent_night_session() -> None:
    calendar = MarketSessionCalendar(nasdaq_23h_enabled=False)
    state = calendar.classify(datetime(2026, 8, 10, 23, 0, tzinfo=ET))
    assert state.structure_version is MarketStructureVersion.LEGACY_US_EQUITY
    assert state.session is MarketSession.CLOSED


def test_dst_conversion_uses_zoneinfo_not_fixed_offsets(calendar: MarketSessionCalendar) -> None:
    winter = calendar.classify(datetime(2026, 1, 15, 9, 30, tzinfo=ET))
    summer = calendar.classify(datetime(2026, 7, 15, 9, 30, tzinfo=ET))
    assert winter.timestamp_utc.hour == 14
    assert summer.timestamp_utc.hour == 13


def test_holiday_is_not_a_trading_day(calendar: MarketSessionCalendar) -> None:
    assert not calendar.is_trading_day(date(2026, 7, 4))


def test_observed_holiday_does_not_become_regular_session(
    calendar: MarketSessionCalendar,
) -> None:
    state = calendar.classify(datetime(2026, 7, 3, 10, 0, tzinfo=ET))
    assert state.session is MarketSession.CLOSED


def test_early_close_uses_exchange_calendar(calendar: MarketSessionCalendar) -> None:
    # US Thanksgiving Friday closes at 13:00 ET.
    state = calendar.classify(datetime(2026, 11, 27, 13, 30, tzinfo=ET))
    assert state.session is MarketSession.POSTMARKET
