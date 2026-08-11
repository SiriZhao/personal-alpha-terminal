"""Read-only live inventory audit and isolated historical research ingest service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.quant_engine.research_data import (
    DataDomain,
    ResearchDataCapabilities,
    ResearchDataInventory,
    audit_research_inventory,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetManifestV2,
    builtin_provider_capabilities,
    certify_research_package,
    generate_xnys_sessions,
    import_research_package,
    latest_manifest,
    load_persisted_research_dataset,
    persist_research_dataset,
)


@dataclass(frozen=True, slots=True)
class LocalResearchAudit:
    database: str
    price_date_start: date | None
    price_date_end: date | None
    inventory: ResearchDataInventory
    classification: str
    blockers: tuple[str, ...]
    reference_calendar_start: date | None
    reference_calendar_end: date | None
    reference_calendar_sessions: int
    reference_calendar_early_closes: int
    provider_capabilities: tuple[dict[str, object], ...]

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


def audit_local_live_inventory(database: Path, cutoff: datetime) -> LocalResearchAudit:
    """Audit the live SQLite store without reclassifying it as research data."""

    if cutoff.tzinfo is None:
        raise ValueError("local audit cutoff must be timezone-aware")
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        latest = connection.execute(
            "SELECT as_of_date, version_id, data_version FROM market_universe_snapshots "
            "ORDER BY as_of_date DESC, id DESC LIMIT 1"
        ).fetchone()
        price_range = connection.execute(
            "SELECT min(trade_date), max(trade_date) FROM prices"
        ).fetchone()
        identifiers = _count(connection, "security_identifier_history")
        inventory = ResearchDataInventory(
            dataset_id="local-live-daily-inventory",
            as_of=date.fromisoformat(str(latest[0])) if latest else cutoff.date(),
            cutoff=cutoff,
            source="local SQLite capability audit",
            provider="mixed live adapters",
            raw_price_rows=_count(connection, "prices"),
            security_count=_count(connection, "security_master"),
            universe_snapshot_count=_count(connection, "market_universe_snapshots"),
            membership_rows=_count(connection, "market_universe_members"),
            delisted_security_count=int(
                connection.execute(
                    "SELECT count(*) FROM security_master WHERE delisting_date IS NOT NULL"
                ).fetchone()[0]
            ),
            identifier_history_rows=identifiers,
            corporate_action_rows=_count(connection, "corporate_actions"),
            total_return_version_rows=_count(connection, "pit_total_return_versions"),
            latest_universe_version=str(latest[1]) if latest and latest[1] else None,
            latest_live_data_version=str(latest[2]) if latest and latest[2] else None,
            capabilities=ResearchDataCapabilities(
                historical_membership_complete=False,
                delistings_complete=False,
                identifier_history_complete=identifiers > 0,
                corporate_actions_pit_complete=False,
                total_return_pit_complete=False,
                raw_ohlcv_complete=_count(connection, "prices") > 0,
                exchange_calendar_complete=_count(connection, "exchange_sessions") > 0,
                current_constituent_snapshot_only=True,
                fundamentals_vintage_complete=_count(connection, "fundamental_vintages") > 0,
            ),
            data_domain=DataDomain.LIVE_DAILY_DATA,
        )
    manifest = audit_research_inventory(inventory)
    price_start = (
        date.fromisoformat(str(price_range[0])) if price_range and price_range[0] else None
    )
    price_end = (
        date.fromisoformat(str(price_range[1])) if price_range and price_range[1] else None
    )
    reference_calendar = (
        generate_xnys_sessions(price_start, price_end, available_at=cutoff)
        if price_start is not None and price_end is not None
        else ()
    )
    return LocalResearchAudit(
        database=str(database.resolve()),
        price_date_start=price_start,
        price_date_end=price_end,
        inventory=inventory,
        classification=manifest.certification_state.value,
        blockers=manifest.blockers,
        reference_calendar_start=(
            reference_calendar[0].session_date if reference_calendar else None
        ),
        reference_calendar_end=(
            reference_calendar[-1].session_date if reference_calendar else None
        ),
        reference_calendar_sessions=len(reference_calendar),
        reference_calendar_early_closes=sum(
            1 for item in reference_calendar if item.is_early_close
        ),
        provider_capabilities=tuple(
            cast(dict[str, object], asdict(item)) for item in builtin_provider_capabilities()
        ),
    )


def import_and_certify_research_data(
    source: Path,
    root: Path,
    *,
    required_start: date | None = None,
    required_end: date | None = None,
) -> tuple[ResearchDatasetManifestV2, Path]:
    package = import_research_package(source)
    manifest = certify_research_package(
        package, required_start=required_start, required_end=required_end
    )
    path = persist_research_dataset(package, manifest, root)
    return manifest, path


def read_latest_research_manifest(root: Path) -> tuple[Path, dict[str, Any]] | None:
    path = latest_manifest(root)
    if path is None:
        return None
    return path, cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def recertify_latest_research_data(
    root: Path,
) -> tuple[ResearchDatasetManifestV2, Path] | None:
    latest = read_latest_research_manifest(root)
    if latest is None:
        return None
    path, document = latest
    package = load_persisted_research_dataset(path)
    required_start = (
        date.fromisoformat(str(document["required_start"]))
        if document.get("required_start")
        else None
    )
    required_end = (
        date.fromisoformat(str(document["required_end"]))
        if document.get("required_end")
        else None
    )
    manifest = certify_research_package(
        package, required_start=required_start, required_end=required_end
    )
    if manifest.manifest_hash != document.get("manifest_hash"):
        raise ValueError("persisted research manifest does not reproduce")
    return manifest, path


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
