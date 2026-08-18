from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.terminal.cli import _daily_decision_time


def test_daily_decision_time_requires_an_explicit_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _daily_decision_time("2026-08-14T20:00:00")


def test_daily_decision_time_preserves_a_valid_historical_cutoff() -> None:
    parsed = _daily_decision_time("2026-08-14T20:00:00+00:00")

    assert parsed == datetime(2026, 8, 14, 20, 0, tzinfo=UTC)


def test_daily_decision_time_rejects_future_replay() -> None:
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    with pytest.raises(ValueError, match="cannot be in the future"):
        _daily_decision_time(future)
