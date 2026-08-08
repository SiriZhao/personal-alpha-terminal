from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from personal_alpha_terminal.intelligence.dedup import CanonicalEventDeduplicator
from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.time import EventTradingClock, SessionPhase
from tests.unit.intelligence.helpers import make_event

NEW_YORK = ZoneInfo("America/New_York")


def test_raw_information_rejects_future_observation_and_computes_hash() -> None:
    published = datetime(2026, 8, 7, 12, tzinfo=UTC)
    raw = RawInformation(
        raw_id="raw-1",
        source="wire",
        source_identifier="story-1",
        title="Results",
        body="Observed evidence",
        published_at=published,
        observed_at=published + timedelta(minutes=1),
        ingested_at=published + timedelta(minutes=2),
        data_cutoff=published + timedelta(minutes=2),
    )
    assert raw.source_hash is not None and len(raw.source_hash) == 64
    with pytest.raises(ValidationError, match="before publication"):
        RawInformation(
            raw_id="raw-2",
            source="wire",
            source_identifier="story-2",
            title="Future",
            body="Leak",
            published_at=published,
            observed_at=published - timedelta(seconds=1),
            ingested_at=published + timedelta(minutes=2),
            data_cutoff=published + timedelta(minutes=2),
        )


@pytest.mark.parametrize(
    ("timestamp", "phase", "first_session"),
    [
        (datetime(2026, 3, 9, 9, 29, tzinfo=NEW_YORK), SessionPhase.PRE_MARKET, "2026-03-09"),
        (datetime(2026, 3, 9, 9, 30, tzinfo=NEW_YORK), SessionPhase.REGULAR, "2026-03-10"),
        (datetime(2026, 3, 9, 15, 59, tzinfo=NEW_YORK), SessionPhase.REGULAR, "2026-03-10"),
        (datetime(2026, 3, 9, 16, 0, tzinfo=NEW_YORK), SessionPhase.AT_CLOSE, "2026-03-10"),
        (datetime(2026, 3, 9, 16, 1, tzinfo=NEW_YORK), SessionPhase.AFTER_HOURS, "2026-03-10"),
        (datetime(2026, 7, 4, 12, 0, tzinfo=NEW_YORK), SessionPhase.NON_TRADING_DAY, "2026-07-06"),
    ],
)
def test_trading_clock_handles_boundaries_dst_and_holidays(
    timestamp: datetime, phase: SessionPhase, first_session: str
) -> None:
    mapping = EventTradingClock().map(timestamp)
    assert mapping.phase is phase
    assert str(mapping.first_tradable_session.date()) == first_session


def test_dedup_merges_evidence_without_counting_duplicate_signals() -> None:
    observed = datetime(2026, 8, 7, 20, tzinfo=UTC)
    left = make_event("a", observed, source="wire-a")
    right = make_event(
        "b",
        observed + timedelta(minutes=10),
        source="wire-b",
        title="Microsoft reports quarterly earnings results",
    )
    result = CanonicalEventDeduplicator().cluster((left, right))
    assert len(result) == 1
    assert len(result[0].evidence) == 2
    assert result[0].confidence == pytest.approx(0.82)
    assert result[0].direction == left.direction


def test_article_update_is_invisible_before_its_observed_time() -> None:
    observed = datetime(2026, 8, 7, 20, tzinfo=UTC)
    original = make_event("original", observed, source="wire-a")
    update = make_event(
        "update",
        observed + timedelta(hours=2),
        source="wire-b",
        title="Microsoft reports quarterly earnings update",
    )
    canonical = CanonicalEventDeduplicator().cluster((original, update))[0]
    historical = canonical.at_cutoff(observed + timedelta(minutes=1))
    current = canonical.at_cutoff(observed + timedelta(hours=3))
    assert historical is not None and len(historical.evidence) == 1
    assert historical.confidence == pytest.approx(0.8)
    assert current is not None and len(current.evidence) == 2
    assert current.confidence == pytest.approx(0.82)
