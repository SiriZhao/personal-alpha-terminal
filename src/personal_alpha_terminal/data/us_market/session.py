from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.models import ExchangeSession


@dataclass(frozen=True, slots=True)
class CertifiedExecutionSession:
    exchange: str
    open_time: datetime
    close_time: datetime
    calendar_source: str


class CertifiedUSSessionService:
    """Resolve execution sessions only from persisted, time-available US calendars."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def next_tradable_open(
        self,
        *,
        decision_time: datetime,
        exchange: str = "XNYS",
    ) -> CertifiedExecutionSession:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        candidates = self.session.scalars(
            select(ExchangeSession)
            .where(
                ExchangeSession.exchange == exchange,
                ExchangeSession.is_open.is_(True),
                ExchangeSession.open_time > decision_time,
                ExchangeSession.available_time <= decision_time,
                ExchangeSession.source != "legacy_unknown",
                ExchangeSession.provider != "legacy_unknown",
            )
            .order_by(ExchangeSession.open_time, ExchangeSession.id)
            .limit(2)
        ).all()
        if not candidates:
            raise ValueError("verified US next-tradable-open calendar is unavailable")
        first = candidates[0]
        if first.open_time is None or first.close_time is None:
            raise ValueError("verified US session has incomplete timestamps")
        return CertifiedExecutionSession(
            exchange=first.exchange,
            open_time=normalize_utc(first.open_time),
            close_time=normalize_utc(first.close_time),
            calendar_source=f"{first.source}:{first.provider}",
        )
