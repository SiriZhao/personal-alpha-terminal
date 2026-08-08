from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd


class PITStatus(StrEnum):
    VALID = "VALID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED = "BLOCKED"
    NOT_VALIDATED = "NOT_VALIDATED"
    SURVIVORSHIP_BIAS_RISK = "SURVIVORSHIP_BIAS_RISK"


@dataclass(frozen=True, slots=True)
class PITSelection:
    frame: pd.DataFrame
    status: PITStatus
    blockers: tuple[str, ...]
    information_cutoff: datetime


def select_fundamental_vintages(
    observations: pd.DataFrame,
    *,
    information_cutoff: datetime,
    latest_period_only: bool = True,
) -> PITSelection:
    """Select the exact fundamental revision visible at ``information_cutoff``.

    A later restatement never replaces an earlier filing before the restatement's
    own ``available_at``.  Missing timestamps fail closed; they are not inferred
    from period end dates.
    """

    _require_aware(information_cutoff, "information_cutoff")
    required = {
        "permanent_security_id",
        "fiscal_period_end",
        "fiscal_period",
        "filing_date",
        "publication_time",
        "available_at",
        "ingested_at",
        "revision_id",
        "data_version",
    }
    missing = required - set(observations.columns)
    if missing:
        return PITSelection(
            observations.iloc[0:0].copy(),
            PITStatus.BLOCKED,
            (f"fundamental vintages miss required columns: {sorted(missing)}",),
            information_cutoff,
        )
    frame = observations.copy()
    try:
        for column in ("publication_time", "available_at", "ingested_at"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
        for column in ("fiscal_period_end", "filing_date"):
            frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date
    except (TypeError, ValueError) as error:
        return PITSelection(
            frame.iloc[0:0],
            PITStatus.BLOCKED,
            (f"invalid fundamental vintage timestamps: {error}",),
            information_cutoff,
        )
    cutoff = pd.Timestamp(information_cutoff).tz_convert("UTC")
    invalid_order = (
        (frame["publication_time"] > frame["available_at"])
        | (frame["available_at"] > frame["ingested_at"])
        | (frame["fiscal_period_end"] > frame["filing_date"])
    )
    if invalid_order.any():
        return PITSelection(
            frame.iloc[0:0],
            PITStatus.BLOCKED,
            (f"{int(invalid_order.sum())} fundamental vintages have impossible timestamp order",),
            information_cutoff,
        )
    visible = frame.loc[
        (frame["fiscal_period_end"] <= information_cutoff.date())
        & (frame["filing_date"] <= information_cutoff.date())
        & (frame["publication_time"] <= cutoff)
        & (frame["available_at"] <= cutoff)
    ].copy()
    if visible.empty:
        return PITSelection(
            visible,
            PITStatus.INSUFFICIENT_DATA,
            ("no fundamental vintage was available at the information cutoff",),
            information_cutoff,
        )
    vintage_keys = ["permanent_security_id", "fiscal_period_end", "fiscal_period"]
    visible = (
        visible.sort_values([*vintage_keys, "available_at", "revision_id"])
        .groupby(vintage_keys, sort=False, as_index=False)
        .tail(1)
    )
    if latest_period_only:
        visible = (
            visible.sort_values(
                ["permanent_security_id", "fiscal_period", "fiscal_period_end", "available_at"]
            )
            .groupby(["permanent_security_id", "fiscal_period"], sort=False, as_index=False)
            .tail(1)
        )
    visible = visible.sort_values(["permanent_security_id", "fiscal_period"]).reset_index(drop=True)
    return PITSelection(visible, PITStatus.VALID, (), information_cutoff)


def select_universe_snapshot(
    observations: pd.DataFrame,
    *,
    information_cutoff: datetime,
    certified_history: bool,
) -> PITSelection:
    """Select the latest universe snapshot actually available at the cutoff."""

    _require_aware(information_cutoff, "information_cutoff")
    required = {
        "snapshot_id",
        "snapshot_date",
        "available_at",
        "permanent_security_id",
        "listing_date",
        "delisting_date",
        "source",
    }
    missing = required - set(observations.columns)
    if missing:
        return PITSelection(
            observations.iloc[0:0].copy(),
            PITStatus.BLOCKED,
            (f"universe snapshots miss required columns: {sorted(missing)}",),
            information_cutoff,
        )
    frame = observations.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"], errors="coerce")
    frame["listing_date"] = pd.to_datetime(frame["listing_date"], errors="coerce")
    frame["delisting_date"] = pd.to_datetime(frame["delisting_date"], errors="coerce")
    if frame[["available_at", "snapshot_date"]].isna().any(axis=None):
        return PITSelection(
            frame.iloc[0:0],
            PITStatus.BLOCKED,
            ("universe snapshot has missing or invalid PIT timestamps",),
            information_cutoff,
        )
    cutoff = pd.Timestamp(information_cutoff).tz_convert("UTC")
    visible = frame.loc[
        (frame["snapshot_date"] <= pd.Timestamp(information_cutoff.date()))
        & (frame["available_at"] <= cutoff)
    ].copy()
    if visible.empty:
        return PITSelection(
            visible,
            PITStatus.INSUFFICIENT_DATA,
            ("no universe snapshot was available at the information cutoff",),
            information_cutoff,
        )
    latest_date = visible["snapshot_date"].max()
    candidates = visible.loc[visible["snapshot_date"] == latest_date]
    latest_available = candidates["available_at"].max()
    selected = candidates.loc[candidates["available_at"] == latest_available].copy()
    selected = selected.loc[
        (selected["listing_date"].isna() | (selected["listing_date"] <= latest_date))
        & (selected["delisting_date"].isna() | (selected["delisting_date"] >= latest_date))
    ].sort_values("permanent_security_id").reset_index(drop=True)
    if not certified_history:
        return PITSelection(
            selected,
            PITStatus.SURVIVORSHIP_BIAS_RISK,
            ("historical membership/delisting coverage is not independently certified",),
            information_cutoff,
        )
    return PITSelection(selected, PITStatus.VALID, (), information_cutoff)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
