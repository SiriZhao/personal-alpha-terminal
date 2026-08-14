"""ROUND24 backfill state machine + provider accounting tests (PHASE G, N)."""
from __future__ import annotations

from datetime import date, timedelta

from personal_alpha_terminal.data.market_data.service import (
    FULL_BACKFILL_REQUIRED,
    NEW_LISTING_WAITING_FOR_HISTORY,
    PERMANENT_PROVIDER_NO_HISTORY,
    RETRY_AFTER,
    STRUCTURALLY_INSUFFICIENT_HISTORY,
    _load_backfill_state,
    _save_backfill_state,
    classify_backfill_decision,
)

REQUIRED_START = date(2024, 8, 1)
END = date(2026, 8, 14)


def test_fully_cached_symbol_reuses_cache() -> None:
    refresh_class, _ = classify_backfill_decision(
        "AAPL",
        earliest=date(2020, 1, 1),
        latest=END,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(1990, 1, 1),
        state={},
    )
    assert refresh_class == "CACHED_UP_TO_DATE"


def test_incremental_one_session() -> None:
    refresh_class, _ = classify_backfill_decision(
        "AAPL",
        earliest=date(2020, 1, 1),
        latest=END - timedelta(days=2),
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(1990, 1, 1),
        state={},
    )
    assert refresh_class == "INCREMENTAL_ONE_SESSION"


def test_new_listing_waits_for_history() -> None:
    listing = date(2026, 6, 1)
    refresh_class, eligible_after = classify_backfill_decision(
        "NEWCO",
        earliest=None,
        latest=None,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=listing,
        state={},
    )
    assert refresh_class == NEW_LISTING_WAITING_FOR_HISTORY
    assert eligible_after is not None
    assert eligible_after > END


def test_new_listing_not_repeatedly_backfilled() -> None:
    """After one planning cycle the state persists; no provider requests."""
    listing = date(2026, 6, 1)
    state = {
        "NEWCO": {
            "state": NEW_LISTING_WAITING_FOR_HISTORY,
            "history_eligible_after": (listing + timedelta(days=380)).isoformat(),
        }
    }
    refresh_class, eligible_after = classify_backfill_decision(
        "NEWCO",
        earliest=None,
        latest=None,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=listing,
        state=state,
    )
    assert refresh_class == NEW_LISTING_WAITING_FOR_HISTORY
    assert eligible_after is not None


def test_permanent_no_history_state_persists() -> None:
    state = {"X": {"state": PERMANENT_PROVIDER_NO_HISTORY, "attempts": 3}}
    refresh_class, _ = classify_backfill_decision(
        "X",
        earliest=None,
        latest=None,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(2010, 1, 1),
        state=state,
    )
    assert refresh_class == PERMANENT_PROVIDER_NO_HISTORY


def test_retry_after_honored_until_date() -> None:
    state = {
        "X": {
            "state": RETRY_AFTER,
            "retry_after": (END + timedelta(days=2)).isoformat(),
        }
    }
    refresh_class, _ = classify_backfill_decision(
        "X",
        earliest=None,
        latest=None,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(2010, 1, 1),
        state=state,
    )
    assert refresh_class == RETRY_AFTER
    state["X"]["retry_after"] = (END - timedelta(days=2)).isoformat()
    refresh_class, _ = classify_backfill_decision(
        "X",
        earliest=None,
        latest=None,
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(2010, 1, 1),
        state=state,
    )
    assert refresh_class == FULL_BACKFILL_REQUIRED


def test_structurally_insufficient_until_eligible() -> None:
    state = {
        "X": {
            "state": STRUCTURALLY_INSUFFICIENT_HISTORY,
            "history_eligible_after": (END + timedelta(days=30)).isoformat(),
        }
    }
    refresh_class, _ = classify_backfill_decision(
        "X",
        earliest=date(2026, 7, 1),
        latest=END - timedelta(days=1),
        required_history_start=REQUIRED_START,
        end_date=END,
        listing_date=date(2010, 1, 1),
        state=state,
    )
    assert refresh_class == STRUCTURALLY_INSUFFICIENT_HISTORY


def test_state_round_trips_through_file(tmp_path) -> None:
    path = tmp_path / "backfill_state.json"
    state = {"A": {"state": RETRY_AFTER, "retry_after": "2026-08-17"}}
    _save_backfill_state(path, state)
    loaded = _load_backfill_state(path)
    assert loaded == state


def test_malformed_state_file_fails_closed(tmp_path) -> None:
    path = tmp_path / "backfill_state.json"
    path.write_text("{not json", encoding="utf-8")
    assert _load_backfill_state(path) == {}
