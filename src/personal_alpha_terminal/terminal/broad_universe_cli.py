"""CLI handlers for broad-universe registration, sync and funnel reporting."""

from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.broad_market.service import (
    BroadUniverseDataService,
)
from personal_alpha_terminal.data.us_market.broad_universe import EligibilityRules

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
    rules = EligibilityRules(**asdict(config.broad_universe))
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
        console.print(f"Unknown broad-universe action: {action}")
        return 2
    finally:
        service.session.close()


def _broad_status(service: BroadUniverseDataService, args: Namespace) -> int:
    coverage = service.coverage()
    console.print("[bold]BROAD UNIVERSE STATUS[/bold]")
    console.print(f"Registered stocks: {coverage['registered_stocks']}")
    console.print(f"Stocks with prices: {coverage['stocks_with_prices']}")
    console.print(f"Price rows: {coverage['price_rows']}")
    console.print(f"Latest price date: {coverage['latest_price_date']}")
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


def _broad_funnel(service: BroadUniverseDataService, args: Namespace) -> int:
    now = datetime.now(UTC)
    universe_date = _optional_date(getattr(args, "as_of", None)) or now.date()
    report = service.funnel(universe_date=universe_date, decision_time=now)
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
    if args.json:
        console.print(json.dumps(report.document(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
