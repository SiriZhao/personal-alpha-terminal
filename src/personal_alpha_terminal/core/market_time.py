from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

MARKET_CLOSES: dict[str, tuple[str, time]] = {
    "A": ("Asia/Shanghai", time(15, 0)),
    # HKEX's closing auction ends randomly between 16:08 and 16:10.
    # Use the latest possible close so no daily bar is treated as known early.
    "HK": ("Asia/Hong_Kong", time(16, 10)),
    "US": ("America/New_York", time(16, 0)),
}


def market_close_utc(trade_date: date, market: str) -> datetime:
    """Return the normal cash-market close in UTC for an exchange trading date."""
    try:
        timezone_name, close_time = MARKET_CLOSES[market]
    except KeyError as error:
        raise ValueError(f"unsupported market close calendar: {market}") from error
    local_close = datetime.combine(
        trade_date,
        close_time,
        tzinfo=ZoneInfo(timezone_name),
    )
    return local_close.astimezone(UTC)


def normalize_utc(value: datetime) -> datetime:
    """Normalize provider/database timestamps; legacy naive values are UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
