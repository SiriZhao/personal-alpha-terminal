import csv
import importlib
import importlib.metadata
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from personal_alpha_terminal.data.market_data_quality.schemas import (
    CalendarSession,
    CorporateActionRecord,
    CorporateActionType,
)

CALENDAR_BY_EXCHANGE = {
    "SSE": ("XSHG", "Asia/Shanghai"),
    "SZSE": ("XSHG", "Asia/Shanghai"),
    "HKEX": ("XHKG", "Asia/Hong_Kong"),
    "NYSE": ("XNYS", "America/New_York"),
    "NASDAQ": ("XNYS", "America/New_York"),
}


class ExchangeCalendarsAdapter:
    source = "exchange_calendar_rules"

    def fetch_sessions(
        self,
        *,
        exchange: str,
        start_date: date,
        end_date: date,
    ) -> list[CalendarSession]:
        if exchange not in CALENDAR_BY_EXCHANGE:
            raise ValueError(f"unsupported exchange calendar: {exchange}")
        calendar_name, timezone = CALENDAR_BY_EXCHANGE[exchange]
        module = importlib.import_module("exchange_calendars")
        version = importlib.metadata.version("exchange-calendars")
        calendar = module.get_calendar(calendar_name)
        fetched_at = datetime.now(UTC)
        open_sessions = calendar.sessions_in_range(
            start_date.isoformat(), end_date.isoformat()
        )
        by_date = {session.date(): session for session in open_sessions}
        output: list[CalendarSession] = []
        current = start_date
        while current <= end_date:
            session = by_date.get(current)
            output.append(
                CalendarSession(
                    exchange=exchange,
                    session_date=current,
                    is_open=session is not None,
                    open_time=(
                        calendar.session_open(session).to_pydatetime()
                        if session is not None
                        else None
                    ),
                    close_time=(
                        calendar.session_close(session).to_pydatetime()
                        if session is not None
                        else None
                    ),
                    timezone=timezone,
                    source=self.source,
                    provider=f"exchange_calendars:{version}:{calendar_name}",
                    available_time=fetched_at,
                    ingested_time=fetched_at,
                )
            )
            current += timedelta(days=1)
        return output


class CertifiedCorporateActionCSVAdapter:
    """Import only actions with explicit point-in-time dates and lineage."""

    REQUIRED_COLUMNS = {
        "stock_id",
        "action_type",
        "effective_date",
        "announcement_date",
        "available_date",
        "event_time",
        "available_time",
        "source",
        "provider",
    }

    def read(self, path: Path) -> list[CorporateActionRecord]:
        ingested = datetime.now(UTC)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = self.REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing:
                raise ValueError(
                    "corporate-action file is missing columns: " + ", ".join(sorted(missing))
                )
            return [self._record(row, ingested) for row in reader]

    @staticmethod
    def _record(row: dict[str, str], ingested: datetime) -> CorporateActionRecord:
        return CorporateActionRecord(
            stock_id=int(row["stock_id"]),
            action_type=CorporateActionType(row["action_type"]),
            effective_date=date.fromisoformat(row["effective_date"]),
            announcement_date=date.fromisoformat(row["announcement_date"]),
            available_date=date.fromisoformat(row["available_date"]),
            event_time=datetime.fromisoformat(row["event_time"]),
            available_time=datetime.fromisoformat(row["available_time"]),
            ingested_time=ingested,
            source=row["source"],
            provider=row["provider"],
            split_ratio=(Decimal(row["split_ratio"]) if row.get("split_ratio") else None),
            cash_amount=(Decimal(row["cash_amount"]) if row.get("cash_amount") else None),
            currency=row.get("currency") or None,
        )
