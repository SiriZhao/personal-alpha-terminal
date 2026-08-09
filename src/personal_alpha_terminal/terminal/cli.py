"""Thin command-line adapter over the headless application service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from personal_alpha_terminal.terminal.config import default_config_text, load_config
from personal_alpha_terminal.terminal.daily_renderer import render_daily_quant_result
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar

if TYPE_CHECKING:
    from personal_alpha_terminal.application import ApplicationService
    from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig

console = Console()
logger = logging.getLogger(__name__)


def run_daily(config_path: Path, *, refresh: bool = True, wait: bool = True) -> int:
    """Run the canonical orchestrator and render exactly its persisted result."""

    try:
        config = load_config(config_path)
        result = _application_service(
            snapshot_root=config.report_dir, effective_config=config
        ).run_daily_quant_report(
            portfolio_id=config.portfolio_id,
            refresh=refresh,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Daily quant orchestration failed")
        console.print(
            Panel(
                f"{type(error).__name__}: {error}\n完整异常已写入日志。",
                title="DAILY QUANT WORKFLOW - FAIL CLOSED",
                border_style="red",
            )
        )
        return 2
    render_daily_quant_result(result, console)
    console.print(f"\nRun snapshot directory: {(config.report_dir / 'daily-runs').resolve()}")
    if wait and sys.stdin.isatty() and os.environ.get("PAT_NONINTERACTIVE") != "1":
        try:
            console.input("\nPress Enter to exit")
        except EOFError:
            logger.info("Skipping exit prompt because stdin reached EOF")
    return 0 if result.actionable else 3


def _application_service(
    *,
    snapshot_root: Path | None = None,
    effective_config: EffectiveRuntimeConfig | None = None,
) -> ApplicationService:
    from personal_alpha_terminal.application import ApplicationService
    from personal_alpha_terminal.core.config import get_settings
    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.data.migrations import upgrade_database

    upgrade_database()
    settings = effective_config.settings if effective_config is not None else get_settings()
    return ApplicationService(
        get_session_factory(),
        settings,
        snapshot_root=snapshot_root,
        effective_config=effective_config,
    )


def _service_for_args(args: argparse.Namespace) -> ApplicationService:
    config_path = getattr(args, "config", None)
    if config_path is None:
        return _application_service()
    config = load_config(config_path)
    return _application_service(effective_config=config)


def _review(args: argparse.Namespace, decision: str) -> int:
    service = _service_for_args(args)
    operation = {
        "accept": service.accept_candidate,
        "reject": service.reject_candidate,
        "watch": service.watch_candidate,
    }[decision]
    result = operation(args.recommendation_id, args.reason)
    console.print(result)
    if decision == "accept":
        console.print(
            "Status: PENDING MANUAL EXECUTION. Enter the order yourself at Charles Schwab."
        )
    return 0


def _record_execution(args: argparse.Namespace) -> int:
    result = _service_for_args(args).mark_candidate_executed(
        args.recommendation_id,
        actual_price=args.price,
        quantity=args.quantity,
        fees=args.fees,
        executed_at=datetime.fromisoformat(args.timestamp) if args.timestamp else None,
        notes=args.notes,
        fill_id=args.fill_id,
        external_reference=args.external_reference,
    )
    console.print(result)
    return 0


def _change_execution(args: argparse.Namespace) -> int:
    service = _service_for_args(args)
    if args.command == "cancel-execution":
        result = service.cancel_candidate_execution(
            args.recommendation_id,
            reason=args.reason,
        )
    else:
        result = service.modify_candidate_execution(
            args.recommendation_id,
            approved_quantity=args.quantity,
            reason=args.reason,
        )
    console.print(result)
    return 0


def _portfolio_command(args: argparse.Namespace) -> int:
    service = _service_for_args(args)
    if args.command == "portfolio-init":
        portfolio_id = service.create_portfolio(
            name=args.name,
            cash_balance=args.cash,
            currency=args.currency,
        )
        console.print(f"Created portfolio id={portfolio_id}; broker connection: NONE")
        return 0
    if args.command == "portfolio-import":
        parsed = service.preview_portfolio_csv(source=args.csv)
        table = Table(title=f"PORTFOLIO IMPORT PREVIEW - {parsed.format_name}")
        table.add_column("Symbol")
        table.add_column("Quantity", justify="right")
        table.add_column("Average cost", justify="right")
        for row in parsed.rows:
            table.add_row(
                row.symbol,
                str(row.quantity),
                str(row.average_cost) if row.average_cost is not None else "--",
            )
        if parsed.cash_balance is not None:
            table.add_row("CASH", str(parsed.cash_balance), "--")
        console.print(table)
        for warning in parsed.warnings:
            console.print(f"WARNING: {warning}")
        if not args.commit:
            console.print("Preview only. Re-run with --commit to update the real portfolio ledger.")
            return 0
        result = service.import_portfolio_csv(
            portfolio_id=args.portfolio_id,
            source=args.csv,
            as_of_date=date.fromisoformat(args.as_of),
        )
        console.print(
            f"Committed {result.imported_count} positions; "
            f"unmatched={len(result.unmatched_symbols)}; format={result.format_name}"
        )
        for warning in result.warnings:
            console.print(f"WARNING: {warning}")
        return 0
    if args.command == "portfolio-show":
        status = service.get_portfolio_status(args.portfolio_id)
        console.print(
            f"id={status['id']} name={status['name']} currency={status['currency']} "
            f"cash={status['cash']} as_of={status['as_of']}"
        )
        table = Table(title="REAL PORTFOLIO / MANUAL SCHWAB LEDGER")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Average cost", justify="right")
        positions = cast(tuple[dict[str, object], ...], status["positions"])
        for item in positions:
            table.add_row(
                str(item["symbol"]),
                str(item["shares"]),
                str(item["average_cost"] if item["average_cost"] is not None else "--"),
            )
        console.print(table)
        return 0
    portfolios = service.list_portfolios()
    if not portfolios:
        console.print("No real portfolio configured. Run portfolio-init or portfolio-import.")
        return 3
    for item in portfolios:
        console.print(
            f"id={item['id']} name={item['name']} currency={item['base_currency']} "
            f"cash={item['cash_balance']}"
        )
    return 0


def _doctor(config_path: Path) -> int:
    checks: list[tuple[str, str, str]] = []
    try:
        config = load_config(config_path)
        checks.append(("PASS", "Config", str(config_path.resolve())))
        checks.append(
            (
                "PASS" if len(config.provider_priority) >= 2 else "WARN",
                "Provider order",
                " -> ".join(config.provider_priority),
            )
        )
        for label, directory in (("Cache", config.cache_dir), ("Reports", config.report_dir)):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                probe = directory / ".doctor-write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
                checks.append(("PASS", label, str(directory.resolve())))
            except OSError as error:
                checks.append(("FAIL", label, type(error).__name__))
        checks.append(("PASS", "Runtime config hash", config.runtime_config_hash))
        checks.append(("PASS", "Effective symbols", ",".join(config.symbols)))
        application = _application_service(effective_config=config)
        readiness = application.get_system_health()
        checks.append(
            (
                "FAIL" if readiness.database.code == "ERROR" else "PASS",
                "Database",
                readiness.database.summary,
            )
        )
        diagnostics = application.get_diagnostic_summary()
        checks.append(("PASS", "Migration", str(diagnostics.get("migration", "unknown"))))
        checks.append(("PASS", "Data directory", str(diagnostics.get("data_directory", "unknown"))))
        market = MarketSessionCalendar(
            nasdaq_23h_enabled=config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
        ).classify(datetime.now(UTC))
        checks.append(
            (
                "PASS",
                "Timezone/calendar",
                f"{market.timestamp_et.tzname()} {market.session.value} {market.trade_date}",
            )
        )
        portfolios = application.list_portfolios()
        checks.append(
            (
                "PASS" if portfolios else "WARN",
                "Portfolio",
                f"{len(portfolios)} real ledger(s)" if portfolios else "not configured",
            )
        )
        checks.extend(
            (
                ("PASS", "Night execution", "DISABLED"),
                ("PASS", "Broker API", "NOT PRESENT"),
                ("WARN", "AI", "OPTIONAL; quant core does not require an API key"),
            )
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Doctor startup check failed")
        checks.append(("FAIL", "Startup contract", f"{type(error).__name__}: {error}"))
    table = Table(title="PERSONAL ALPHA TERMINAL - DOCTOR")
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Detail", overflow="fold")
    for status, label, detail in checks:
        table.add_row(status, label, detail)
    console.print(table)
    return 2 if any(status == "FAIL" for status, _, _ in checks) else 0


def _research(config_path: Path) -> int:
    config = load_config(config_path)
    service = _application_service(effective_config=config)
    readiness = service.get_system_health()
    if not readiness.data.allow_research:
        console.print(
            Panel(
                f"{readiness.data.code}: {readiness.data.summary}\n"
                f"Repair action: {readiness.data.repair_action}",
                title="Research workflow blocked",
                border_style="red",
            )
        )
        return 3
    result = service.run_daily_pipeline()
    console.print(
        f"Research pipeline: {result.status}\n"
        f"Run date: {result.run_date}\nReport: {result.report_path}"
    )
    return 2 if result.status == "failed" else 0


def _backtest_status(config_path: Path) -> int:
    from personal_alpha_terminal.application.backtest_service import BacktestService

    config = load_config(config_path)
    service = _application_service(effective_config=config)
    availability = BacktestService().availability(
        gate_approved=service.get_model_readiness().allow_candidates
    )
    console.print(
        Panel(
            availability.reason,
            title=f"Historical Backtest: {availability.status}",
            border_style="green" if availability.available else "yellow",
        )
    )
    return 0 if availability.available else 3


def _certificate_path(config_path: Path, run_id: str | None) -> Path:
    config = load_config(config_path)
    root = config.report_dir / "daily-runs"
    candidates = (
        [root / run_id / "run_certificate.json"]
        if run_id
        else sorted(
            root.glob("*/run_certificate.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    )
    candidates = [item for item in candidates if item.exists()]
    if not candidates:
        raise ValueError("NO_PERSISTED_RUN; run daily or refresh first")
    return candidates[0]


def _explain(config_path: Path, symbol: str, run_id: str | None = None) -> int:
    path = _certificate_path(config_path, run_id)
    certificate = json.loads(path.read_text(encoding="utf-8"))
    normalized = symbol.strip().upper()
    trace = certificate.get("decision_traces", {}).get(normalized)
    if not isinstance(trace, dict):
        raise ValueError(f"{normalized} is absent from run {certificate.get('run_id')}")
    table = Table(title=f"DECISION TRACE / {normalized} / {certificate.get('run_id')}")
    table.add_column("Evidence")
    table.add_column("Value", overflow="fold")
    for key, value in trace.items():
        table.add_row(str(key), json.dumps(value, ensure_ascii=False, sort_keys=True))
    console.print(table)
    console.print(f"Certificate: {path.resolve()}")
    console.print("LLM contribution: NONE")
    return 0


def _render_persisted_section(
    config_path: Path, section: str, run_id: str | None
) -> int:
    path = _certificate_path(config_path, run_id)
    certificate = json.loads(path.read_text(encoding="utf-8"))
    mapping = {
        "data": ("data_certification", "data"),
        "factors": ("factor_statistics", "signals"),
        "probability": ("probability",),
        "risk": ("risk",),
        "decisions": ("decision_counts", "decision_traces"),
    }
    payload = {key: certificate.get(key) for key in mapping[section]}
    console.print(
        Panel(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            title=f"{section.upper()} / IMMUTABLE RUN {certificate.get('run_id')}",
        )
    )
    console.print(f"Certificate: {path.resolve()}")
    return 0


def _verify_recommendation_run(
    config_path: Path, run_id: str, recommendation_id: str
) -> None:
    path = _certificate_path(config_path, run_id)
    certificate = json.loads(path.read_text(encoding="utf-8"))
    decisions = certificate.get("decision_recommendations", [])
    identifiers = {
        str(item.get("recommendation_id"))
        for item in decisions
        if isinstance(item, dict)
    }
    if recommendation_id not in identifiers:
        raise ValueError(
            f"recommendation {recommendation_id} is not bound to immutable run {run_id}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PersonalAlphaTerminal")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--no-refresh", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("daily", help="Run and render the complete daily quant chain")
    subparsers.add_parser("refresh", help="Refresh data, then run the daily quant chain")
    for name, help_text in (
        ("data", "Render data status through the daily snapshot"),
        ("factors", "Render factor results from the daily snapshot"),
        ("probability", "Render validated conditional evidence from the daily snapshot"),
        ("risk", "Render portfolio risk from the daily snapshot"),
        ("decisions", "Render final validated decisions"),
    ):
        section = subparsers.add_parser(name, help=help_text)
        section.add_argument("--run-id", default=None)
    subparsers.add_parser("doctor")
    subparsers.add_parser("diagnostics", help="Alias for doctor")
    subparsers.add_parser("settings", help="Show the active terminal configuration path")
    subparsers.add_parser("version", help="Show application version")
    subparsers.add_parser("research", help="Run the audited local research pipeline")
    subparsers.add_parser("backtest", help="Check the PIT backtest execution gate")
    subparsers.add_parser("init-config")
    for name in ("accept", "reject", "watch"):
        command = subparsers.add_parser(name)
        command.add_argument("recommendation_id")
        command.add_argument("--run-id", required=True)
        command.add_argument("--reason", default="")
    execution = subparsers.add_parser("mark-executed")
    execution.add_argument("recommendation_id")
    execution.add_argument("--run-id", required=True)
    execution.add_argument("--price", type=float, required=True)
    execution.add_argument("--quantity", type=float, required=True)
    execution.add_argument("--fees", type=float, default=0.0)
    execution.add_argument("--timestamp", default=None)
    execution.add_argument("--notes", default="")
    execution.add_argument(
        "--fill-id",
        default=None,
        help="Unique Schwab/manual fill identity; required for multiple partial fills",
    )
    execution.add_argument("--external-reference", default=None)
    cancel_execution = subparsers.add_parser("cancel-execution")
    cancel_execution.add_argument("recommendation_id")
    cancel_execution.add_argument("--run-id", required=True)
    cancel_execution.add_argument("--reason", required=True)
    modify_execution = subparsers.add_parser("modify-execution")
    modify_execution.add_argument("recommendation_id")
    modify_execution.add_argument("--run-id", required=True)
    modify_execution.add_argument("--quantity", type=float, required=True)
    modify_execution.add_argument("--reason", required=True)
    portfolio_init = subparsers.add_parser("portfolio-init")
    portfolio_init.add_argument("--name", default="My Portfolio")
    portfolio_init.add_argument("--cash", type=float, default=0.0)
    portfolio_init.add_argument("--currency", default="USD")
    portfolio_import = subparsers.add_parser("portfolio-import")
    portfolio_import.add_argument("csv", type=Path)
    portfolio_import.add_argument("--portfolio-id", type=int, required=True)
    portfolio_import.add_argument("--as-of", required=True)
    portfolio_import.add_argument("--commit", action="store_true")
    subparsers.add_parser("portfolio-list")
    subparsers.add_parser("portfolio", help="Alias for portfolio-list")
    portfolio_show = subparsers.add_parser("portfolio-show")
    portfolio_show.add_argument("--portfolio-id", type=int, required=True)
    explain = subparsers.add_parser("explain")
    explain.add_argument("symbol")
    explain.add_argument("--run-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    command = args.command or "daily"
    try:
        if command == "init-config":
            if args.config.exists():
                console.print(f"Configuration already exists: {args.config}")
                return 0
            args.config.write_text(default_config_text(), encoding="utf-8")
            console.print(f"Created configuration: {args.config}")
            return 0
        if command in {"doctor", "diagnostics"}:
            return _doctor(args.config)
        if command == "settings":
            config = load_config(args.config)
            console.print(
                json.dumps(
                    {
                        **config.identity_payload(),
                        "runtime_config_hash": config.runtime_config_hash,
                        "canonical_run_config_hash": config.canonical_run_config_hash,
                    },
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
            )
            return 0
        if command == "version":
            from personal_alpha_terminal import __version__

            console.print(f"Personal Alpha Terminal {__version__}")
            return 0
        if command == "research":
            return _research(args.config)
        if command == "backtest":
            return _backtest_status(args.config)
        if command == "explain":
            return _explain(args.config, args.symbol, args.run_id)
        if command in {"accept", "reject", "watch"}:
            _verify_recommendation_run(args.config, args.run_id, args.recommendation_id)
            return _review(args, command)
        if command == "mark-executed":
            _verify_recommendation_run(args.config, args.run_id, args.recommendation_id)
            return _record_execution(args)
        if command in {"cancel-execution", "modify-execution"}:
            _verify_recommendation_run(args.config, args.run_id, args.recommendation_id)
            return _change_execution(args)
        if command == "portfolio":
            args.command = "portfolio-list"
            return _portfolio_command(args)
        if command in {
            "portfolio-init",
            "portfolio-import",
            "portfolio-list",
            "portfolio-show",
        }:
            return _portfolio_command(args)
        if command == "refresh":
            return run_daily(args.config, refresh=True)
        if command in {"data", "factors", "probability", "risk", "decisions"}:
            return _render_persisted_section(args.config, command, args.run_id)
        return run_daily(args.config, refresh=not args.no_refresh)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Command failed")
        console.print(f"ERROR: {type(error).__name__}: {error}")
        return 2
