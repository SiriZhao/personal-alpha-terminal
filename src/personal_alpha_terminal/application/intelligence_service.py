from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models.intelligence import (
    IntelligenceEvent,
    IntelligenceExtractionCache,
    IntelligenceRawInformation,
    IntelligenceResearchResult,
)


class IntelligenceApplicationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def status(self, *, as_of: datetime | None = None) -> dict[str, object]:
        raw_count = self.session.scalar(select(func.count(IntelligenceRawInformation.id))) or 0
        event_query = select(func.count(IntelligenceEvent.id))
        if as_of is not None:
            event_query = event_query.where(
                IntelligenceEvent.observed_at <= as_of,
                IntelligenceEvent.data_cutoff <= as_of,
                IntelligenceEvent.backtest_safety == "BACKTEST_SAFE",
            )
        event_count = self.session.scalar(event_query) or 0
        cache_count = (
            self.session.scalar(select(func.count(IntelligenceExtractionCache.cache_key))) or 0
        )
        latest = self.session.scalar(select(func.max(IntelligenceEvent.observed_at)))
        return {
            "status": "READY" if event_count else "UNAVAILABLE",
            "raw_information_count": raw_count,
            "canonical_event_count": event_count,
            "cache_entry_count": cache_count,
            "latest_observed_at": latest.isoformat() if latest is not None else None,
            "message": (
                "PIT-safe versioned intelligence is available."
                if event_count
                else (
                    "No validated intelligence has been materialized; Quant Core remains available."
                )
            ),
        }

    def latest_scan(self) -> dict[str, object]:
        result = self.session.scalar(
            select(IntelligenceResearchResult)
            .where(IntelligenceResearchResult.result_type == "DAILY_OPPORTUNITY_SCAN")
            .order_by(IntelligenceResearchResult.created_at.desc())
            .limit(1)
        )
        if result is None:
            return {
                "status": "UNAVAILABLE",
                "candidates": [],
                "message": "No scanner result exists; no placeholder candidates were generated.",
            }
        return dict(result.payload)
