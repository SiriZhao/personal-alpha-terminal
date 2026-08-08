from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pandas as pd


class SessionPhase(StrEnum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    AT_CLOSE = "AT_CLOSE"
    AFTER_HOURS = "AFTER_HOURS"
    NON_TRADING_DAY = "NON_TRADING_DAY"


@dataclass(frozen=True, slots=True)
class EventSessionMapping:
    observed_at: datetime
    phase: SessionPhase
    last_completed_session: pd.Timestamp | None
    event_session: pd.Timestamp
    first_tradable_session: pd.Timestamp
    same_close_eligible: bool


class EventTradingClock:
    """Maps observable event time to exchange sessions without same-bar leakage."""

    def __init__(self, calendar_name: str = "XNYS") -> None:
        self.calendar = xcals.get_calendar(calendar_name)

    def map(self, observed_at: datetime) -> EventSessionMapping:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        minute = pd.Timestamp(observed_at).tz_convert("UTC")
        day = minute.normalize().tz_localize(None)
        if self.calendar.is_session(day):
            session = self.calendar.date_to_session(day)
            opened = self.calendar.session_open(session)
            closed = self.calendar.session_close(session)
            if minute < opened:
                phase = SessionPhase.PRE_MARKET
                last_completed = self.calendar.previous_session(session)
                first_tradable = session
                same_close = True
            elif minute < closed:
                phase = SessionPhase.REGULAR
                last_completed = self.calendar.previous_session(session)
                first_tradable = self.calendar.next_session(session)
                same_close = True
            elif minute == closed:
                phase = SessionPhase.AT_CLOSE
                last_completed = session
                first_tradable = self.calendar.next_session(session)
                same_close = False
            else:
                phase = SessionPhase.AFTER_HOURS
                last_completed = session
                first_tradable = self.calendar.next_session(session)
                same_close = False
            return EventSessionMapping(
                observed_at.astimezone(UTC), phase, last_completed, session, first_tradable,
                same_close,
            )
        next_session = self.calendar.date_to_session(day, direction="next")
        previous_session = self.calendar.previous_session(next_session)
        return EventSessionMapping(
            observed_at.astimezone(UTC), SessionPhase.NON_TRADING_DAY,
            previous_session, next_session, next_session, False,
        )

    def session_close(self, session: pd.Timestamp) -> datetime:
        return cast(datetime, self.calendar.session_close(session).to_pydatetime())
