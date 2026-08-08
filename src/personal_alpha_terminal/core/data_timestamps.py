from dataclasses import dataclass
from datetime import UTC, date, datetime

from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc
from personal_alpha_terminal.data.market_data.policies import policy_for_market


@dataclass(frozen=True, slots=True)
class DataTimestamps:
    """Three-time contract for point-in-time research inputs."""

    event_time: datetime
    available_time: datetime
    ingested_time: datetime

    def __post_init__(self) -> None:
        event = normalize_utc(self.event_time)
        available = normalize_utc(self.available_time)
        ingested = normalize_utc(self.ingested_time)
        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "available_time", available)
        object.__setattr__(self, "ingested_time", ingested)
        if available < event:
            raise ValueError("available_time cannot precede event_time")
        if ingested < available:
            raise ValueError("ingested_time cannot precede available_time")

    def assert_available(self, cutoff: datetime) -> None:
        if self.available_time > normalize_utc(cutoff):
            raise ValueError("data was not available at the research cutoff")


def daily_bar_timestamps(
    trade_date: date,
    market: str,
    *,
    ingested_time: datetime | None = None,
) -> DataTimestamps:
    policy = policy_for_market(market)
    event_time = market_close_utc(trade_date, market)
    available_time = event_time + policy.daily_bar_publication_delay
    effective_ingested = normalize_utc(ingested_time or datetime.now(UTC))
    if effective_ingested < available_time:
        effective_ingested = available_time
    return DataTimestamps(
        event_time=event_time,
        available_time=available_time,
        ingested_time=effective_ingested,
    )
