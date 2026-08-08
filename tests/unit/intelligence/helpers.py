from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    EventEvidence,
    EventType,
    UnifiedEvent,
)


def make_event(
    event_id: str,
    observed_at: datetime,
    *,
    symbol: str = "MSFT",
    title: str = "Microsoft reports quarterly earnings",
    source: str = "wire",
    event_type: EventType = EventType.EARNINGS,
) -> UnifiedEvent:
    published = observed_at - timedelta(minutes=1)
    ingested = observed_at + timedelta(minutes=1)
    created = observed_at + timedelta(minutes=2)
    evidence = EventEvidence(
        evidence_id=f"raw-{event_id}",
        source=source,
        source_identifier=f"story-{event_id}",
        source_hash=(event_id * 64)[:64],
        published_at=published,
        observed_at=observed_at,
        reference=f"https://example.test/{event_id}",
    )
    return UnifiedEvent(
        event_id=event_id,
        symbol=symbol,
        entity="Microsoft",
        sector="Technology",
        industry="Software",
        event_type=event_type,
        title=title,
        summary="Reported results with structured evidence.",
        published_at=published,
        observed_at=observed_at,
        effective_at=observed_at,
        ingested_at=ingested,
        source=source,
        source_identifier=f"story-{event_id}",
        source_hash=(event_id * 64)[:64],
        direction=EventDirection.POSITIVE,
        relevance=0.9,
        novelty=0.8,
        confidence=0.8,
        expected_horizon=20,
        affected_assets=(symbol,),
        affected_sectors=("technology",),
        themes=("earnings",),
        evidence=(evidence,),
        model_version="fixture-model-v1",
        prompt_version="fixture-prompt-v1",
        data_cutoff=ingested,
        created_at=created,
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
    )


UTC_NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)
