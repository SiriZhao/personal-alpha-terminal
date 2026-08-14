from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol, cast
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


class _TimestampLike(Protocol):
    def to_pydatetime(self) -> datetime: ...


class _ExchangeCalendar(Protocol):
    def is_session(self, session_label: str) -> bool: ...

    def session_close(self, session_label: str) -> _TimestampLike: ...


class MarketSession(StrEnum):
    NIGHT = "NIGHT"
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    POSTMARKET = "POSTMARKET"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class MarketStructureVersion(StrEnum):
    LEGACY_US_EQUITY = "LEGACY_US_EQUITY"
    NASDAQ_23H = "NASDAQ_23H"


@dataclass(frozen=True, slots=True)
class MarketSessionState:
    timestamp_utc: datetime
    timestamp_et: datetime
    calendar_date: date
    trade_date: date
    session: MarketSession
    structure_version: MarketStructureVersion
    is_execution_session: bool


class MarketSessionCalendar:
    """US-equity session classifier with an explicit future 23-hour mode.

    Night data is an information input only. Enabling the future structure does
    not enable night execution and does not assert that a provider supplies it.
    """

    def __init__(
        self,
        *,
        nasdaq_23h_enabled: bool = False,
        nasdaq_23h_effective_date: date | None = None,
        night_execution_enabled: bool = False,
        allow_deterministic_fallback: bool = False,
    ) -> None:
        self.nasdaq_23h_enabled = nasdaq_23h_enabled
        self.nasdaq_23h_effective_date = nasdaq_23h_effective_date
        self.night_execution_enabled = night_execution_enabled
        self.allow_deterministic_fallback = allow_deterministic_fallback

    def classify(self, value: datetime) -> MarketSessionState:
        if value.tzinfo is None:
            raise ValueError("market timestamp must be timezone-aware")
        utc_value = value.astimezone(UTC)
        local = utc_value.astimezone(NEW_YORK)
        structure = self._structure(local.date())
        regular_close = self._regular_close(local.date())
        local_time = local.timetz().replace(tzinfo=None)

        if structure is MarketStructureVersion.NASDAQ_23H:
            session = self._classify_23h(local_time, regular_close)
        else:
            session = self._classify_legacy(local_time, regular_close)
        if not self._session_is_scheduled(local, session):
            session = MarketSession.CLOSED

        trade_date = self._trade_date(local, structure)
        execution = session is MarketSession.REGULAR or (
            self.night_execution_enabled and session is MarketSession.NIGHT
        )
        return MarketSessionState(
            timestamp_utc=utc_value,
            timestamp_et=local,
            calendar_date=local.date(),
            trade_date=trade_date,
            session=session,
            structure_version=structure,
            is_execution_session=execution,
        )

    def market_close_utc(self, trade_date: date) -> datetime:
        local_close = datetime.combine(
            trade_date,
            self._regular_close(trade_date),
            tzinfo=NEW_YORK,
        )
        return local_close.astimezone(UTC)

    def structure_for_date(self, value: date) -> MarketStructureVersion:
        return self._structure(value)

    def is_trading_day(self, value: date) -> bool:
        try:
            calendar = self._calendar()
            return bool(calendar.is_session(value.isoformat()))
        except (ImportError, ValueError, TypeError, AttributeError) as error:
            if self.allow_deterministic_fallback:
                return value.weekday() < 5
            raise CalendarUnavailableError(
                f"certified XNYS calendar unavailable: {type(error).__name__}: {error}"
            ) from error

    def completed_session_date(self, value: datetime) -> date:
        """Return the most recent session whose data is observable after close.

        An after-close or overnight clock on a trading day resolves to that same
        trading day; before the close it resolves to the previous trading day.
        """
        if value.tzinfo is None:
            raise ValueError("market timestamp must be timezone-aware")
        utc_value = value.astimezone(UTC)
        local = utc_value.astimezone(NEW_YORK)
        candidate = local.date()
        if self.is_trading_day(candidate) and utc_value >= self.market_close_utc(candidate):
            return candidate
        candidate -= timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def next_trading_day(self, value: date) -> date:
        candidate = value + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def _structure(self, local_date: date) -> MarketStructureVersion:
        if (
            self.nasdaq_23h_enabled
            and self.nasdaq_23h_effective_date is not None
            and local_date >= self.nasdaq_23h_effective_date
        ):
            return MarketStructureVersion.NASDAQ_23H
        return MarketStructureVersion.LEGACY_US_EQUITY

    def _regular_close(self, value: date) -> time:
        try:
            calendar = self._calendar()
            label = value.isoformat()
            if calendar.is_session(label):
                close = (
                    calendar.session_close(label)
                    .to_pydatetime()
                    .astimezone(NEW_YORK)
                )
                return time(close.hour, close.minute, close.second)
            return time(16, 0)
        except (ImportError, ValueError, TypeError, AttributeError) as error:
            if self.allow_deterministic_fallback:
                return time(16, 0)
            raise CalendarUnavailableError(
                f"certified XNYS session close unavailable: {type(error).__name__}: {error}"
            ) from error

    @staticmethod
    def _calendar() -> _ExchangeCalendar:
        xcals = importlib.import_module("exchange_calendars")
        return cast(_ExchangeCalendar, xcals.get_calendar("XNYS"))

    @staticmethod
    def _classify_legacy(value: time, regular_close: time) -> MarketSession:
        if time(4, 0) <= value < time(9, 30):
            return MarketSession.PREMARKET
        if time(9, 30) <= value < regular_close:
            return MarketSession.REGULAR
        if regular_close <= value < time(20, 0):
            return MarketSession.POSTMARKET
        return MarketSession.CLOSED

    @staticmethod
    def _classify_23h(value: time, regular_close: time) -> MarketSession:
        if value >= time(21, 0) or value < time(4, 0):
            return MarketSession.NIGHT
        if time(4, 0) <= value < time(9, 30):
            return MarketSession.PREMARKET
        if time(9, 30) <= value < regular_close:
            return MarketSession.REGULAR
        if regular_close <= value < time(20, 0):
            return MarketSession.POSTMARKET
        if time(20, 0) <= value < time(21, 0):
            return MarketSession.MAINTENANCE
        return MarketSession.CLOSED

    def _session_is_scheduled(
        self,
        local: datetime,
        session: MarketSession,
    ) -> bool:
        if session is MarketSession.CLOSED:
            return False
        if session is MarketSession.NIGHT and local.time() >= time(21, 0):
            # The overnight session only opens when the next calendar day is a
            # valid exchange session. This closes Friday/Saturday nights and
            # the evening before an exchange holiday.
            return self.next_trading_day(local.date()) == local.date() + timedelta(days=1)
        return self.is_trading_day(local.date())

    def _trade_date(
        self,
        local: datetime,
        structure: MarketStructureVersion,
    ) -> date:
        if (
            structure is MarketStructureVersion.NASDAQ_23H
            and local.time() >= time(21, 0)
        ):
            return self.next_trading_day(local.date())
        if self.is_trading_day(local.date()):
            return local.date()
        return self.next_trading_day(local.date())


class CalendarUnavailableError(RuntimeError):
    pass
