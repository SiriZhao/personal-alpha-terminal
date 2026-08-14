"""CLI handlers for broad-universe registration, sync and funnel reporting."""

from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from pathlib import Path

from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.broad_market.service import (
    BroadUniverseDataService,
)
from personal_alpha_terminal.data.us_market.broad_universe import (
    EligibilityRules,
    latest_directory_snapshot_at,
    list_directory_snapshots,
)

console = Console()


def _session_factory(database: Path) -> Callable[[], Session]:
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{database}")
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def _service(
    config: EffectiveRuntimeConfig,
    *,
    database: Path,
    chunk_size: int | None = None,
) -> BroadUniverseDataService:
    factory = _session_factory(database)
    session = factory()
    base_rules = asdict(config.broad_universe)
    base_rules["minimum_trading_sessions"] = max(
        int(base_rules["minimum_trading_sessions"]),
        config.strategy.required_history_sessions,
    )
    rules = EligibilityRules(**base_rules)
    from personal_alpha_terminal.data.broad_market.batch_provider import (
        YahooBatchStockProvider,
    )

    provider = (
        YahooBatchStockProvider(chunk_size=chunk_size)
        if chunk_size is not None
        else None
    )
    return BroadUniverseDataService(
        session,
        cache_root=config.cache_dir,
        directory_root=config.cache_dir / "us-current-directory",
        rules=rules,
        provider=provider,
    )


def broad_universe_command(args: Namespace) -> int:
    from personal_alpha_terminal.terminal.config import load_config

    config = load_config(args.config)
    database = getattr(args, "database", Path("var/personal_alpha.db"))
    service = _service(
        config,
        database=database,
        chunk_size=getattr(args, "chunk_size", None),
    )
    action = getattr(args, "broad_universe_action", "status")
    try:
        if action == "status":
            return _broad_status(service, args)
        if action == "register":
            result = _broad_register(service, args)
            service.session.commit()
            return result
        if action == "sync":
            result = _broad_sync(service, args)
            service.session.commit()
            return result
        if action == "funnel":
            return _broad_funnel(service, args)
        if action == "capture":
            return _broad_capture(service, args)
        if action == "audit":
            return _broad_audit(service, args)
        if action == "history-sufficiency":
            if getattr(args, "required_sessions", None) is None:
                args.required_sessions = max(
                    config.broad_universe.minimum_trading_sessions,
                    config.strategy.required_history_sessions,
                )
            return _broad_history_sufficiency(service, args)
        console.print(f"Unknown broad-universe action: {action}")
        return 2
    finally:
        service.session.close()


def _broad_status(service: BroadUniverseDataService, args: Namespace) -> int:
    coverage = service.coverage()
    now = datetime.now(UTC)
    snapshots = list_directory_snapshots(service.directory_root)
    visible = latest_directory_snapshot_at(service.directory_root, now)
    console.print("[bold]BROAD UNIVERSE STATUS[/bold]")
    console.print(f"Registered stocks: {coverage['registered_stocks']}")
    console.print(f"Stocks with prices: {coverage['stocks_with_prices']}")
    console.print(f"Price rows: {coverage['price_rows']}")
    console.print(f"Latest price date: {coverage['latest_price_date']}")
    console.print(f"Immutable snapshots: {len(snapshots)}")
    if snapshots:
        latest = snapshots[-1]
        console.print(f"Latest snapshot: {latest.content_hash}")
        console.print(f"Acquired at: {latest.retrieved_at.isoformat()}")
        console.print(f"Records: {len(latest.records)}")
        console.print(
            f"Decision-visible now: {'YES' if visible is not None else 'NO'} "
            f"({visible.content_hash if visible else 'none'})"
        )
    quarantine = service.quarantine_status()
    console.print(f"Quarantined symbols: {len(quarantine)}")
    if quarantine:
        table = Table(title="Quarantine")
        table.add_column("Symbol")
        table.add_column("Reason")
        for symbol, reason in sorted(quarantine.items()):
            table.add_row(symbol, reason)
        console.print(table)
    return 0


def _broad_register(service: BroadUniverseDataService, args: Namespace) -> int:
    decision_time = datetime.now(UTC)
    report = service.register_current_directory(decision_time=decision_time)
    console.print("[bold]BROAD UNIVERSE REGISTRATION[/bold]")
    console.print(f"Directory securities: {report.directory_securities}")
    console.print(f"Registered new: {report.registered}")
    console.print(f"Already registered: {report.already_registered}")
    console.print(f"Skipped: {report.skipped}")
    if report.skip_reasons:
        console.print(f"Skip reasons: {report.skip_reasons}")
    console.print(f"New symbols: {', '.join(report.registered_symbols[:50]) or '(none)'}")
    if len(report.registered_symbols) > 50:
        console.print(f"... and {len(report.registered_symbols) - 50} more")
    return 0


def _broad_sync(service: BroadUniverseDataService, args: Namespace) -> int:
    now = datetime.now(UTC)
    end_date = _optional_date(getattr(args, "end_date", None)) or now.date()
    mode = getattr(args, "mode", "incremental")
    if mode == "backfill":
        start_date = _optional_date(getattr(args, "start_date", None)) or date(2020, 1, 1)
        result = service.backfill(
            start_date=start_date,
            end_date=end_date,
            decision_time=now,
            max_symbols=getattr(args, "max_symbols", None),
        )
    else:
        result = service.incremental_sync(
            end_date=end_date,
            decision_time=now,
            sessions_back=getattr(args, "sessions_back", 10),
            max_symbols=getattr(args, "max_symbols", None),
        )
    console.print("[bold]BROAD UNIVERSE SYNC[/bold]")
    console.print(f"Decision time: {result.decision_time.isoformat()}")
    console.print(f"Range: {result.start_date} -> {result.end_date}")
    console.print(
        f"Requested {result.report.requested_symbols.__len__()}, "
        f"received {result.report.received_symbols.__len__()}, "
        f"failed {result.report.failed_symbols.__len__()}, "
        f"coverage {result.report.coverage:.3f}"
    )
    console.print(f"Bars: {result.report.bar_count}")
    console.print(f"Inserted: {result.inserted_rows}, Updated: {result.updated_rows}")
    console.print(f"Quarantined: {result.quarantined}")
    return 0


def _broad_capture(service: BroadUniverseDataService, args: Namespace) -> int:
    from personal_alpha_terminal.application.broad_universe_service import (
        BroadUSUniverseService,
    )

    snapshot = BroadUSUniverseService(
        service.session,
        cache_root=service.directory_root,
        rules=service.rules,
    ).refresh_directory()
    console.print("[bold]OFFICIAL UNIVERSE CAPTURE[/bold]")
    console.print(f"Snapshot: {snapshot.content_hash}")
    console.print(f"Acquired at: {snapshot.retrieved_at.isoformat()}")
    console.print(f"Records: {len(snapshot.records)}")
    console.print(f"Provider: {snapshot.provider}")
    console.print(f"Historical use allowed: {snapshot.historical_use_allowed}")
    if args.json:
        console.print(
            json.dumps(snapshot.document(), ensure_ascii=False, indent=2, sort_keys=True)
        )
    return 0


def _broad_audit(service: BroadUniverseDataService, args: Namespace) -> int:
    as_of = _optional_date(getattr(args, "as_of", None))
    decision_time = (
        datetime.combine(as_of, time(20, 30), tzinfo=UTC) if as_of else datetime.now(UTC)
    )
    snapshots = list_directory_snapshots(service.directory_root)
    visible = latest_directory_snapshot_at(service.directory_root, decision_time)
    console.print("[bold]OFFICIAL UNIVERSE SNAPSHOT AUDIT[/bold]")
    console.print(f"Decision as-of: {decision_time.isoformat()}")
    console.print(f"Immutable snapshots: {len(snapshots)}")
    table = Table(title="Official Universe Snapshots")
    table.add_column("Acquired at")
    table.add_column("Records")
    table.add_column("Content hash")
    for snapshot in snapshots:
        marker = (
            "*"
            if visible is not None and snapshot.content_hash == visible.content_hash
            else ""
        )
        table.add_row(
            snapshot.retrieved_at.isoformat(),
            str(len(snapshot.records)),
            snapshot.content_hash[:16] + marker,
        )
    console.print(table)
    console.print(
        f"Decision-visible snapshot: {visible.content_hash if visible else 'NONE'}"
    )
    console.print(
        "Historical membership capability: "
        + str(visible.capabilities.historical_membership if visible else False)
    )
    console.print(
        "Historical use allowed for visible snapshot: "
        + str(visible.historical_use_allowed if visible else False)
    )
    artifact = {
        "decision_time": decision_time.isoformat(),
        "snapshot_count": len(snapshots),
        "snapshots": [
            {
                "content_hash": item.content_hash,
                "acquired_at": item.retrieved_at.isoformat(),
                "record_count": len(item.records),
                "provider": item.provider,
                "historical_use_allowed": item.historical_use_allowed,
                "historical_membership": item.capabilities.historical_membership,
            }
            for item in snapshots
        ],
        "decision_visible_snapshot": (
            visible.content_hash if visible is not None else None
        ),
    }
    _write_artifact(args, artifact)
    if args.json:
        console.print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _broad_history_sufficiency(service: BroadUniverseDataService, args: Namespace) -> int:
    now = datetime.now(UTC)
    as_of = _optional_date(getattr(args, "as_of", None))
    universe_date = as_of or now.date()
    decision_time = (
        datetime.combine(as_of, time(20, 30), tzinfo=UTC) if as_of else now
    )
    report = service.history_sufficiency(
        universe_date=universe_date,
        decision_time=decision_time,
        required_history_sessions=getattr(args, "required_sessions", None),
    )
    console.print("[bold]BROAD HISTORY SUFFICIENCY[/bold]")
    console.print(
        f"Required history sessions: {report['required_history_sessions']}   "
        f"Denominator: {report['denominator']}   "
        f"History sufficient: {report['history_sufficient']}   "
        f"Coverage: {report['coverage_pct']}%"
    )
    reasons = report.get("reasons") or {}
    if isinstance(reasons, dict):
        for reason, count in reasons.items():
            console.print(f"{reason}: {count}")
    _write_artifact(args, report)
    if args.json:
        console.print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _write_artifact(args: Namespace, payload: object) -> None:
    artifact = getattr(args, "artifact", None)
    if artifact is None:
        return
    path = Path(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _broad_funnel(service: BroadUniverseDataService, args: Namespace) -> int:
    now = datetime.now(UTC)
    as_of = _optional_date(getattr(args, "as_of", None))
    universe_date = as_of or now.date()
    decision_time = (
        datetime.combine(as_of, time(20, 30), tzinfo=UTC) if as_of else now
    )
    report = service.funnel(universe_date=universe_date, decision_time=decision_time)
    console.print("[bold]FULL TRADABLE UNIVERSE FUNNEL[/bold]")
    console.print(
        f"Universe date: {report.universe_date} | "
        f"Rules fingerprint: {report.rules_fingerprint[:12]}"
    )
    table = Table(title="Universe Funnel")
    table.add_column("Layer")
    table.add_column("Eligible")
    table.add_column("Excluded")
    table.add_column("Top exclusion reasons")
    for layer in report.layers:
        top = ", ".join(
            f"{name}={count}"
            for name, count in sorted(layer.breakdown.items(), key=lambda item: -item[1])[:3]
        )
        table.add_row(layer.name, str(layer.count), str(layer.excluded), top)
    console.print(table)
    console.print(
        "Current operational tier (CURRENT_OPERATIONAL_PIT, price-based): "
        f"data {report.price_based_data_eligible}, "
        f"liquidity {report.price_based_liquidity_eligible}, "
        f"factor {report.price_based_factor_eligible}"
    )
    console.print(f"Survivorship status: {report.survivorship_status}")
    console.print(f"PIT status: {report.pit_status}")
    console.print(f"Qualification: {report.qualification}")
    console.print(f"Quarantined symbols: {report.quarantine_count}")
    console.print(f"Eligible symbols ({len(report.eligible_symbols)}):")
    console.print(", ".join(report.eligible_symbols[:60]))
    _write_artifact(args, report.document())
    if args.json:
        console.print(json.dumps(report.document(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
