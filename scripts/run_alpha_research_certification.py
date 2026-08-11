"""Audit the actual local research-data capability and run certification E2E."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from personal_alpha_terminal.quant_engine.alpha_research_workflow import (
    run_alpha_research_capability_audit,
)
from personal_alpha_terminal.quant_engine.research_data import (
    ResearchDataCapabilities,
    ResearchDataInventory,
)


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _inventory(database: Path, cutoff: datetime) -> ResearchDataInventory:
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        latest = connection.execute(
            "SELECT as_of_date, version_id, data_version FROM market_universe_snapshots "
            "ORDER BY as_of_date DESC, id DESC LIMIT 1"
        ).fetchone()
        as_of = date.fromisoformat(str(latest[0])) if latest else cutoff.date()
        security_count = _count(connection, "security_master")
        delisted_count = int(
            connection.execute(
                "SELECT count(*) FROM security_master WHERE delisting_date IS NOT NULL"
            ).fetchone()[0]
        )
        snapshots = _count(connection, "market_universe_snapshots")
        identifiers = _count(connection, "security_identifier_history")
        # The configured current universe has snapshots only near the live date;
        # it is not a historical constituent timeline.
        capabilities = ResearchDataCapabilities(
            historical_membership_complete=False,
            delistings_complete=False,
            identifier_history_complete=identifiers > 0,
            corporate_actions_pit_complete=False,
            total_return_pit_complete=False,
            raw_ohlcv_complete=_count(connection, "prices") > 0,
            exchange_calendar_complete=_count(connection, "exchange_sessions") > 0,
            current_constituent_snapshot_only=True,
            fundamentals_vintage_complete=_count(connection, "fundamental_vintages") > 0,
        )
        return ResearchDataInventory(
            dataset_id="local-live-daily-inventory",
            as_of=as_of,
            cutoff=cutoff,
            source="local SQLite capability audit",
            provider="mixed live adapters",
            raw_price_rows=_count(connection, "prices"),
            security_count=security_count,
            universe_snapshot_count=snapshots,
            membership_rows=_count(connection, "market_universe_members"),
            delisted_security_count=delisted_count,
            identifier_history_rows=identifiers,
            corporate_action_rows=_count(connection, "corporate_actions"),
            total_return_version_rows=_count(connection, "pit_total_return_versions"),
            latest_universe_version=str(latest[1]) if latest and latest[1] else None,
            latest_live_data_version=str(latest[2]) if latest and latest[2] else None,
            capabilities=capabilities,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    parser.add_argument("--output", type=Path, default=Path("reports/research-runs"))
    parser.add_argument("--cutoff", type=datetime.fromisoformat, required=True)
    args = parser.parse_args()
    cutoff = args.cutoff
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    run = run_alpha_research_capability_audit(
        _inventory(args.database, cutoff), output_root=args.output, evaluated_at=cutoff
    )
    print(f"run_id={run.run_id}")
    print(f"result_hash={run.result_hash}")
    print(f"certification={run.certification.status.value}")
    for blocker in run.certification.blockers:
        print(f"blocker={blocker}")
    return 0 if run.certification.status.value == "PRODUCTION_APPROVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
