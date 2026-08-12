"""ROUND 5: operational universe baseline collapse guard tests."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from personal_alpha_terminal.quant_engine.operational_baseline import (
    OperationalBaselineRecord,
    append_record,
    detect_collapse,
    load_baseline,
)


def _record(day: int, count: int) -> OperationalBaselineRecord:
    return OperationalBaselineRecord(
        decision_date=date(2026, 8, day),
        factor_eligible=count,
        operational_eligible=count,
        quarantine_count=0,
    )


def test_baseline_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    append_record(path, _record(10, 1900))
    append_record(path, _record(11, 1950))
    records = load_baseline(path)
    assert [item.factor_eligible for item in records] == [1900, 1950]
    assert records[-1].decision_date == date(2026, 8, 11)


def test_below_absolute_threshold_fails_closed() -> None:
    collapsed, reason = detect_collapse(
        (),
        current_factor_eligible=5,
        minimum_operational_universe=50,
        coverage_collapse_ratio=0.5,
    )
    assert collapsed is True
    assert reason is not None and "BELOW_THRESHOLD" in reason


def test_sudden_collapse_versus_recent_median_fails_closed() -> None:
    prior = tuple(_record(day, 1900) for day in range(1, 8))
    collapsed, reason = detect_collapse(
        prior,
        current_factor_eligible=700,
        minimum_operational_universe=50,
        coverage_collapse_ratio=0.5,
    )
    assert collapsed is True
    assert reason is not None and "COLLAPSE" in reason


def test_normal_size_does_not_trip_collapse() -> None:
    prior = tuple(_record(day, 1900) for day in range(1, 8))
    collapsed, reason = detect_collapse(
        prior,
        current_factor_eligible=1850,
        minimum_operational_universe=50,
        coverage_collapse_ratio=0.5,
    )
    assert collapsed is False
    assert reason is None


def test_insufficient_history_skips_collapse_check() -> None:
    prior = (_record(1, 1900),)
    collapsed, reason = detect_collapse(
        prior,
        current_factor_eligible=10,
        minimum_operational_universe=50,
        coverage_collapse_ratio=0.5,
    )
    # One prior record is not enough for a trend comparison; only the absolute
    # threshold applies, and 10 < 50 so it must still fail closed.
    assert collapsed is True
    assert reason is not None and "BELOW_THRESHOLD" in reason
