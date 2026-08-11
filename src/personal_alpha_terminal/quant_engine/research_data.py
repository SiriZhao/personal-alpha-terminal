"""Provider-neutral contracts for survivorship-safe historical research data.

Live daily readiness is deliberately separate from historical research
certification.  A current-constituent snapshot can be useful for today's
analysis but can never certify a historical backtest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


class ResearchDatasetState(StrEnum):
    CERTIFIED = "CERTIFIED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"
    DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class ResearchDataCapabilities:
    historical_membership_complete: bool
    delistings_complete: bool
    identifier_history_complete: bool
    corporate_actions_pit_complete: bool
    total_return_pit_complete: bool
    raw_ohlcv_complete: bool
    exchange_calendar_complete: bool
    current_constituent_snapshot_only: bool = False
    fundamentals_vintage_complete: bool = False


@dataclass(frozen=True, slots=True)
class ResearchDataInventory:
    dataset_id: str
    as_of: date
    cutoff: datetime
    source: str
    provider: str
    raw_price_rows: int
    security_count: int
    universe_snapshot_count: int
    membership_rows: int
    delisted_security_count: int
    identifier_history_rows: int
    corporate_action_rows: int
    total_return_version_rows: int
    latest_universe_version: str | None
    latest_live_data_version: str | None
    capabilities: ResearchDataCapabilities

    def __post_init__(self) -> None:
        if self.cutoff.tzinfo is None:
            raise ValueError("research inventory cutoff must be timezone-aware")
        if self.as_of > self.cutoff.date():
            raise ValueError("research inventory as_of cannot follow cutoff")
        if any(
            value < 0
            for value in (
                self.raw_price_rows,
                self.security_count,
                self.universe_snapshot_count,
                self.membership_rows,
                self.delisted_security_count,
                self.identifier_history_rows,
                self.corporate_action_rows,
                self.total_return_version_rows,
            )
        ):
            raise ValueError("research inventory counts cannot be negative")


@dataclass(frozen=True, slots=True)
class HistoricalMembership:
    permanent_security_id: str
    asset_type: str
    entry_date: date
    exit_date: date | None
    available_at: datetime
    source: str
    provider: str

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("membership available_at must be timezone-aware")
        if self.exit_date is not None and self.exit_date < self.entry_date:
            raise ValueError("membership exit cannot precede entry")

    def active_on(self, session: date, *, decision_time: datetime) -> bool:
        if decision_time.tzinfo is None:
            raise ValueError("membership decision_time must be timezone-aware")
        return (
            self.available_at <= decision_time
            and self.entry_date <= session
            and (self.exit_date is None or session <= self.exit_date)
        )


@dataclass(frozen=True, slots=True)
class HistoricalSecurityIdentity:
    permanent_security_id: str
    ticker: str
    valid_from: date
    valid_to: date | None
    available_at: datetime
    source: str
    provider: str


@dataclass(frozen=True, slots=True)
class ResearchDatasetManifest:
    dataset_id: str
    dataset_version: str | None
    as_of: date
    cutoff: datetime
    source: str
    provider: str
    row_count: int
    member_count: int
    content_hash: str | None
    inventory_hash: str
    certification_state: ResearchDatasetState
    blockers: tuple[str, ...]
    capabilities: ResearchDataCapabilities
    manifest_hash: str

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


class ResearchDatasetAdapter(Protocol):
    """Port for future licensed or user-supplied historical datasets."""

    provider_id: str

    def inventory(self, *, as_of: date, cutoff: datetime) -> ResearchDataInventory: ...


def audit_research_inventory(inventory: ResearchDataInventory) -> ResearchDatasetManifest:
    """Classify capability without pretending that live rows are research data."""

    blockers: list[str] = []
    capabilities = inventory.capabilities
    if inventory.raw_price_rows == 0:
        blockers.append("RAW_OHLCV_DATA_NOT_AVAILABLE")
    if not capabilities.historical_membership_complete:
        blockers.append("HISTORICAL_MEMBERSHIP_INCOMPLETE")
    if capabilities.current_constituent_snapshot_only:
        blockers.append("CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED")
    if not capabilities.delistings_complete:
        blockers.append("DELISTING_HISTORY_INCOMPLETE")
    if not capabilities.identifier_history_complete:
        blockers.append("SECURITY_IDENTIFIER_HISTORY_INCOMPLETE")
    if not capabilities.corporate_actions_pit_complete:
        blockers.append("CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE")
    if not capabilities.total_return_pit_complete:
        blockers.append("PIT_TOTAL_RETURN_HISTORY_INCOMPLETE")
    if not capabilities.raw_ohlcv_complete:
        blockers.append("RAW_OHLCV_HISTORY_INCOMPLETE")
    if not capabilities.exchange_calendar_complete:
        blockers.append("EXCHANGE_CALENDAR_INCOMPLETE")

    state = (
        ResearchDatasetState.DATA_NOT_AVAILABLE
        if inventory.raw_price_rows == 0
        else ResearchDatasetState.NOT_CERTIFIABLE
        if blockers
        else ResearchDatasetState.CERTIFIED
    )
    inventory_payload = asdict(inventory)
    inventory_hash = fingerprint(inventory_payload)
    # A content hash is intentionally absent until an adapter supplies and hashes
    # the complete row-level dataset.  Hashing an inventory is not a substitute.
    content_hash = None if state is not ResearchDatasetState.CERTIFIED else inventory_hash
    dataset_version = (
        f"research-{inventory_hash}" if state is ResearchDatasetState.CERTIFIED else None
    )
    material: dict[str, object] = {
        "dataset_id": inventory.dataset_id,
        "dataset_version": dataset_version,
        "as_of": inventory.as_of,
        "cutoff": inventory.cutoff,
        "source": inventory.source,
        "provider": inventory.provider,
        "row_count": inventory.raw_price_rows,
        "member_count": inventory.security_count,
        "content_hash": content_hash,
        "inventory_hash": inventory_hash,
        "certification_state": state,
        "blockers": tuple(blockers),
        "capabilities": capabilities,
    }
    return ResearchDatasetManifest(
        dataset_id=inventory.dataset_id,
        dataset_version=dataset_version,
        as_of=inventory.as_of,
        cutoff=inventory.cutoff,
        source=inventory.source,
        provider=inventory.provider,
        row_count=inventory.raw_price_rows,
        member_count=inventory.security_count,
        content_hash=content_hash,
        inventory_hash=inventory_hash,
        certification_state=state,
        blockers=tuple(blockers),
        capabilities=capabilities,
        manifest_hash=fingerprint(material),
    )


def eligible_members(
    memberships: tuple[HistoricalMembership, ...],
    *,
    session: date,
    decision_time: datetime,
    asset_type: str | None = None,
) -> tuple[str, ...]:
    """Return only membership records that were knowable at the cutoff."""

    return tuple(
        sorted(
            item.permanent_security_id
            for item in memberships
            if item.active_on(session, decision_time=decision_time)
            and (asset_type is None or item.asset_type == asset_type)
        )
    )


def persist_research_manifest(manifest: ResearchDatasetManifest, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{manifest.manifest_hash}.json"
    rendered = json.dumps(manifest.document(), ensure_ascii=False, indent=2, sort_keys=True)
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable research manifest: {target}")
    target.write_text(rendered, encoding="utf-8")
    return target
