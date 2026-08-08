from datetime import UTC, date, datetime

from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc


def test_market_close_utc_accounts_for_us_daylight_saving() -> None:
    winter = market_close_utc(date(2026, 1, 5), "US")
    summer = market_close_utc(date(2026, 7, 6), "US")

    assert winter.hour == 21
    assert summer.hour == 20


def test_naive_legacy_timestamp_is_interpreted_as_utc() -> None:
    value = datetime(2026, 1, 5, 12)
    assert normalize_utc(value) == datetime(2026, 1, 5, 12, tzinfo=UTC)
