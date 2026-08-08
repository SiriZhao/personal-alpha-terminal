from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from personal_alpha_terminal.terminal.config import default_config_text, load_config
from personal_alpha_terminal.terminal.daily_renderer import render_daily_quant_result
from personal_alpha_terminal.terminal.pipeline import (
    DailyAction,
    DailyAnalysis,
    DailyResearchPipeline,
)
from personal_alpha_terminal.terminal.quality import DataSafetyStatus

if TYPE_CHECKING:
    from personal_alpha_terminal.application import ApplicationService

console = Console()
logger = logging.getLogger(__name__)


def _render(result: DailyAnalysis) -> None:
    session = result.market_session
    data_style = {
        "SAFE": "green",
        "DEGRADED": "yellow",
        "BLOCKED": "red",
    }[result.data_quality.safety_status.value]
    header = (
        f"ET: {session.timestamp_et:%Y-%m-%d %H:%M:%S %Z}    "
        f"Local: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}\n"
        f"Trade date: {session.trade_date}    Session: {session.session.value}    "
        f"Structure: {session.structure_version.value}\n\n"
        f"Data: [{data_style}]{result.data_quality.safety_status.value}[/{data_style}]    "
        f"Quality floor: {result.data_quality.minimum_quality_score:.1f}/100    "
        f"Model: {result.model_status}    Portfolio: "
        f"{'READY' if result.portfolio_risk is not None else 'INSUFFICIENT_DATA'}"
    )
    console.print(Panel(header, title="PERSONAL QUANT TERMINAL - TODAY", border_style="cyan"))

    providers = Table(title="DATA LAYER / PROVIDERS")
    providers.add_column("Provider")
    providers.add_column("Status")
    providers.add_column("Success", justify="right")
    providers.add_column("Latency", justify="right")
    providers.add_column("Last error", overflow="fold")
    for provider_health in result.provider_health:
        providers.add_row(
            provider_health.provider,
            provider_health.status,
            f"{provider_health.success_rate:.0%}",
            (
                f"{provider_health.latency_ms:.0f} ms"
                if provider_health.latency_ms is not None
                else "--"
            ),
            _public_provider_error(provider_health.last_error),
        )
    console.print(providers)

    market = Table(title="MARKET")
    market.add_column("Instrument")
    market.add_column("Close", justify="right")
    market.add_column("Change", justify="right")
    market.add_column("Latest")
    for overview_item in result.overview:
        market.add_row(
            overview_item.symbol,
            (
                f"{overview_item.close:.2f}"
                if overview_item.close is not None
                else "UNAVAILABLE"
            ),
            (
                f"{overview_item.daily_change:.2%}"
                if overview_item.daily_change is not None
                else "--"
            ),
            str(overview_item.latest_date or "--"),
        )
    console.print(market)
    console.print(
        Panel(
            f"{result.regime}\n{result.regime_reason}",
            title="MARKET REGIME SCORE",
        )
    )

    if result.portfolio_risk is None:
        portfolio = (
            "No validated real-holdings risk result. Configure holdings or import "
            "the portfolio ledger."
        )
    else:
        risk = result.portfolio_risk
        beta = f"{risk.beta:.2f}" if risk.beta is not None else "样本不足"
        portfolio = (
            f"Annualized volatility: {risk.annualized_volatility:.2%}\n"
            f"Maximum drawdown: {risk.maximum_drawdown:.2%}\n"
            f"Beta: {beta}\n"
            f"Concentration HHI: {risk.concentration_hhi:.3f}"
        )
    console.print(Panel(portfolio, title="REAL PORTFOLIO ANALYSIS"))

    actions = Table(title="TODAY'S ACTION LIST")
    for column in (
        "Symbol",
        "Action",
        "Current",
        "Target",
        "Confidence",
        "Data",
        "Feasibility",
        "Session",
        "Cost",
    ):
        actions.add_column(column, overflow="fold")
    for action_item in result.actions:
        actions.add_row(
            action_item.symbol,
            action_item.action,
            (
                f"{action_item.current_allocation:.2%}"
                if action_item.current_allocation is not None
                else "--"
            ),
            (
                f"{action_item.target_allocation:.2%}"
                if action_item.target_allocation is not None
                else "--"
            ),
            (
                f"{action_item.confidence:.0%}"
                if action_item.confidence is not None
                else "--"
            ),
            f"{action_item.data_quality:.1f}",
            action_item.execution_feasibility,
            action_item.recommended_session,
            (
                f"{action_item.estimated_cost_rate:.3%}"
                if action_item.estimated_cost_rate is not None
                else "MANUAL CHECK"
            ),
        )
    console.print(actions)
    for action_item in result.actions:
        probability = (
            f"{action_item.probability:.1%}"
            if action_item.probability is not None
            else "NO CALIBRATED PROBABILITY"
        )
        change = (
            f"{action_item.suggested_change:+.2%}"
            if action_item.suggested_change is not None
            else "--"
        )
        detail = (
            f"Signal: {action_item.signal_summary}\n"
            f"Probability evidence: {probability}\n"
            f"Risk: {action_item.risk}\n"
            f"Suggested change: {change}\n"
            f"Reason codes: {', '.join(action_item.reason_codes)}"
        )
        console.print(Panel(detail, title=f"{action_item.symbol} EVIDENCE / CONSTRAINTS"))
    warnings = "\n".join(f"- {warning}" for warning in result.warnings)
    console.print(Panel(warnings, title="WARNINGS", border_style="yellow"))


def _public_provider_error(error: str | None) -> str:
    if not error:
        return "--"
    lowered = error.lower()
    if "rate limit" in lowered or "429" in lowered:
        return "RATE LIMITED · see data.log"
    if "timeout" in lowered or "timed out" in lowered:
        return "TIMEOUT · see data.log"
    return "FETCH FAILED · see data.log"


def run_daily(config_path: Path, *, refresh: bool = True, wait: bool = True) -> int:
    try:
        config = load_config(config_path)
        service = _application_service(snapshot_root=config.report_dir)
        result = service.run_daily_quant_report(
            portfolio_id=config.portfolio_id,
            refresh=refresh,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Daily quant orchestration failed")
        console.print(
            Panel(
                f"{type(error).__name__}: {error}\n完整异常已写入日志。",
                title="DAILY QUANT WORKFLOW · FAIL CLOSED",
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
            # Packaged smoke tests and redirected terminals can report a TTY
            # while providing no readable stdin. The completed analysis must
            # still return its safety-gate exit code without a traceback.
            logger.info("Skipping exit prompt because stdin reached EOF")
    return 0 if result.actionable else 3


def _attach_authorized_candidates(analysis: DailyAnalysis) -> DailyAnalysis:
    """Attach persisted deterministic decisions without inventing execution inputs."""

    try:
        candidates = _application_service().get_action_candidates()
    except Exception as error:
        logger.exception("Decision database unavailable while rendering Today")
        return replace(
            analysis,
            warnings=(
                *analysis.warnings,
                "决策数据库不可用；Today 保持只读。"
                f"诊断代码：{type(error).__name__}。请运行 doctor 并查看日志。",
            ),
        )
    if not candidates:
        return analysis
    actions: list[DailyAction] = []
    for candidate in candidates:
        local_data_safe = (
            analysis.data_quality.safety_status is DataSafetyStatus.SAFE
        )
        executable = candidate.executable and local_data_safe
        reasons = ["VALIDATED_DECISION_CHAIN"]
        if not candidate.executable:
            reasons.append("MODEL_OR_DATA_GATE_BLOCKED")
        if not local_data_safe:
            reasons.append("CURRENT_MARKET_DATA_BLOCKED")
        # The daily-price feed does not provide a certified live spread/ADV
        # snapshot, so even an approved candidate requires broker-side manual
        # feasibility review and limit-first execution.
        reasons.append("MANUAL_EXECUTION_FEASIBILITY_REVIEW_REQUIRED")
        actions.append(
            DailyAction(
                symbol=candidate.ticker,
                action=candidate.action,
                confidence=float(candidate.confidence_score) / 100.0,
                current_allocation=float(candidate.current_weight),
                target_allocation=float(candidate.target_weight),
                suggested_change=float(candidate.target_weight - candidate.current_weight),
                signal_summary="; ".join(candidate.rationale),
                probability=None,
                risk="; ".join(candidate.risk_factors) or "UNSPECIFIED",
                data_quality=analysis.data_quality.minimum_quality_score,
                execution_feasibility="WAIT" if executable else "BLOCKED",
                recommended_session="REGULAR",
                estimated_cost_rate=None,
                reason_codes=tuple(reasons),
            )
        )
    return replace(
        analysis,
        actions=tuple(actions),
        model_status="READY" if any(item.executable for item in candidates) else "BLOCKED",
    )


def _application_service(*, snapshot_root: Path | None = None) -> ApplicationService:
    from personal_alpha_terminal.application import ApplicationService
    from personal_alpha_terminal.core.config import get_settings
    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.data.migrations import upgrade_database

    upgrade_database()
    return ApplicationService(
        get_session_factory(), get_settings(), snapshot_root=snapshot_root
    )


def _review(recommendation_id: str, decision: str, reason: str) -> int:
    service = _application_service()
    operation = {
        "accept": service.accept_candidate,
        "reject": service.reject_candidate,
        "watch": service.watch_candidate,
    }[decision]
    result = operation(recommendation_id, reason)
    console.print(result)
    if decision == "accept":
        console.print(
            "Status: PENDING MANUAL EXECUTION. Enter the order yourself at Charles Schwab."
        )
    return 0


def _record_execution(args: argparse.Namespace) -> int:
    service = _application_service()
    result = service.mark_candidate_executed(
        args.recommendation_id,
        actual_price=args.price,
        quantity=args.quantity,
        fees=args.fees,
        executed_at=datetime.fromisoformat(args.timestamp) if args.timestamp else None,
        notes=args.notes,
    )
    console.print(result)
    return 0


def _portfolio_command(args: argparse.Namespace) -> int:
    service = _application_service()
    if args.command == "portfolio-init":
        portfolio_id = service.create_portfolio(name=args.name, cash_balance=args.cash)
        console.print(f"Created portfolio id={portfolio_id}; broker connection: NONE")
        return 0
    if args.command == "portfolio-import":
        result = service.import_portfolio_csv(
            portfolio_id=args.portfolio_id,
            source=args.csv,
            as_of_date=date.fromisoformat(args.as_of),
        )
        console.print(
            f"Imported {result.imported_count} positions; "
            f"unmatched={len(result.unmatched_symbols)}; format={result.format_name}"
        )
        for warning in result.warnings:
            console.print(f"WARNING: {warning}")
        return 0
    for item in service.list_portfolios():
        console.print(
            f"id={item['id']} name={item['name']} currency={item['base_currency']} "
            f"cash={item['cash_balance']}"
        )
    return 0


def _doctor(config_path: Path) -> int:
    checks: list[tuple[str, str, str]] = []
    try:
        config = load_config(config_path)
        pipeline = DailyResearchPipeline(config)
        providers = ", ".join(item.name for item in pipeline.market_data.providers)
        checks.append(("PASS", "Config", str(config_path.resolve())))
        checks.append(
            (
                "PASS" if len(pipeline.market_data.providers) >= 2 else "WARN",
                "Providers",
                providers,
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
        application = _application_service()
        readiness = application.get_system_health()
        database_status = "FAIL" if readiness.database.code == "ERROR" else "PASS"
        checks.append((database_status, "Database", readiness.database.title_zh))
        market = pipeline.market_data.calendar.classify(datetime.now().astimezone())
        checks.append(
            (
                "PASS",
                "Timezone/calendar",
                f"{market.timestamp_et.tzname()} {market.session.value} {market.trade_date}",
            )
        )
        portfolios = application.list_portfolios()
        if portfolios:
            status = "PASS"
            detail = (
                f"{len(portfolios)} real portfolio ledger(s); "
                f"first={portfolios[0]['name']}; cash={portfolios[0]['cash_balance']}"
            )
        elif config.holdings:
            status = "WARN"
            detail = "legacy config weights only; import into the real portfolio ledger"
        else:
            status, detail = "WARN", "not configured; import or record the real portfolio"
        checks.append((status, "Portfolio", detail))
        checks.append(("PASS", "Night execution", "DISABLED"))
        checks.append(("PASS", "Broker API", "NOT PRESENT"))
        checks.append(("WARN", "AI", "OPTIONAL; quant core does not require an API key"))
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        checks.append(("FAIL", "Startup contract", f"{type(error).__name__}: {error}"))
    table = Table(title="QUANT TERMINAL DOCTOR")
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Detail", overflow="fold")
    for status, label, detail in checks:
        table.add_row(status, label, detail)
    console.print(table)
    return 2 if any(status == "FAIL" for status, _, _ in checks) else 0


def _research() -> int:
    service = _application_service()
    readiness = service.get_system_health()
    if not readiness.data.allow_research:
        console.print(
            Panel(
                f"{readiness.data.code}: {readiness.data.summary}\n"
                f"修复动作：{readiness.data.repair_action}",
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


def _backtest_status() -> int:
    from personal_alpha_terminal.application.backtest_service import BacktestService

    service = _application_service()
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PersonalAlphaTerminal")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--no-refresh", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("daily", help="Run and render the complete daily quant chain")
    subparsers.add_parser("refresh", help="Refresh data, then run the daily quant chain")
    subparsers.add_parser("data", help="Render data status through the daily snapshot")
    subparsers.add_parser("factors", help="Render factor results from the daily snapshot")
    subparsers.add_parser(
        "probability", help="Render validated conditional evidence from the daily snapshot"
    )
    subparsers.add_parser("risk", help="Render portfolio risk from the daily snapshot")
    subparsers.add_parser("decisions", help="Render final validated decisions")
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
        command.add_argument("--reason", default="")
    execution = subparsers.add_parser("mark-executed")
    execution.add_argument("recommendation_id")
    execution.add_argument("--price", type=float, required=True)
    execution.add_argument("--quantity", type=float, required=True)
    execution.add_argument("--fees", type=float, default=0.0)
    execution.add_argument("--timestamp", default=None)
    execution.add_argument("--notes", default="")
    portfolio_init = subparsers.add_parser("portfolio-init")
    portfolio_init.add_argument("--name", default="My Portfolio")
    portfolio_init.add_argument("--cash", type=float, default=0.0)
    portfolio_import = subparsers.add_parser("portfolio-import")
    portfolio_import.add_argument("csv", type=Path)
    portfolio_import.add_argument("--portfolio-id", type=int, required=True)
    portfolio_import.add_argument("--as-of", required=True)
    subparsers.add_parser("portfolio-list")
    subparsers.add_parser("portfolio", help="Alias for portfolio-list")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    command = args.command or "daily"
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
        console.print(f"Active configuration: {args.config.resolve()}")
        return 0
    if command == "version":
        from personal_alpha_terminal import __version__

        console.print(f"Personal Alpha Terminal {__version__}")
        return 0
    if command == "research":
        return _research()
    if command == "backtest":
        return _backtest_status()
    if command in {"accept", "reject", "watch"}:
        return _review(args.recommendation_id, command, args.reason)
    if command == "mark-executed":
        return _record_execution(args)
    if command == "portfolio":
        args.command = "portfolio-list"
        return _portfolio_command(args)
    if command in {"portfolio-init", "portfolio-import", "portfolio-list"}:
        return _portfolio_command(args)
    if command == "refresh":
        return run_daily(args.config, refresh=True)
    if command in {"data", "factors", "probability", "risk", "decisions"}:
        return run_daily(args.config, refresh=False)
    return run_daily(args.config, refresh=not args.no_refresh)
