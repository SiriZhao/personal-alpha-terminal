"""Recent operational-universe sizes used to detect sudden coverage collapse.

The broad universe is expected to stay roughly stable day to day.  If the
factor-eligible count collapses versus the recent median, the daily run must
fail closed instead of silently recommending from a shrunken cross-section.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, cast

MAX_HISTORY_RECORDS = 14


@dataclass(frozen=True, slots=True)
class OperationalBaselineRecord:
    decision_date: date
    factor_eligible: int
    operational_eligible: int
    quarantine_count: int

    def __post_init__(self) -> None:
        if self.factor_eligible < 0 or self.operational_eligible < 0:
            raise ValueError("operational baseline counts must be non-negative")
        if self.quarantine_count < 0:
            raise ValueError("quarantine count must be non-negative")


def load_baseline(path: Path) -> tuple[OperationalBaselineRecord, ...]:
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return ()
    records: list[OperationalBaselineRecord] = []
    for item in cast(list[dict[str, Any]], payload.get("records", [])):
        try:
            records.append(
                OperationalBaselineRecord(
                    decision_date=date.fromisoformat(str(item["decision_date"])),
                    factor_eligible=int(item["factor_eligible"]),
                    operational_eligible=int(item["operational_eligible"]),
                    quarantine_count=int(item.get("quarantine_count", 0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(records[-MAX_HISTORY_RECORDS:])


def append_record(
    path: Path,
    record: OperationalBaselineRecord,
) -> tuple[OperationalBaselineRecord, ...]:
    records = load_baseline(path)
    if records and records[-1].decision_date == record.decision_date:
        records = records[:-1]
    records = (*records, record)[-MAX_HISTORY_RECORDS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "records": [asdict(item) for item in records],
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    return records


def detect_collapse(
    records: tuple[OperationalBaselineRecord, ...],
    *,
    current_factor_eligible: int,
    minimum_operational_universe: int,
    coverage_collapse_ratio: float,
) -> tuple[bool, str | None]:
    """Return ``(collapsed, reason)``.

    A collapse is a material drop below the recent median, not merely below the
    absolute threshold.  Both checks are separate fail-closed conditions.
    """
    if current_factor_eligible < minimum_operational_universe:
        return (
            True,
            (
                f"OPERATIONAL_UNIVERSE_BELOW_THRESHOLD: "
                f"{current_factor_eligible} < {minimum_operational_universe}"
            ),
        )
    prior = records[:-1]
    if len(prior) < 2:
        return False, None
    baseline_median = median(item.factor_eligible for item in prior)
    if baseline_median < minimum_operational_universe:
        return False, None
    if current_factor_eligible < coverage_collapse_ratio * baseline_median:
        return (
            True,
            (
                f"OPERATIONAL_UNIVERSE_COLLAPSE: {current_factor_eligible} < "
                f"{coverage_collapse_ratio:g} x median {baseline_median:g}"
            ),
        )
    return False, None
