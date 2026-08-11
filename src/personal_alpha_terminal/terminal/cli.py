"""Thin command-line adapter over the headless application service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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


def run_daily(
    config_path: Path,
    *,
    refresh: bool = True,
    wait: bool = True,
    paper_portfolio_id: str | None = None,
) -> int:
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
    if paper_portfolio_id:
        from personal_alpha_terminal.paper_trading import PaperTradingService

        paper_service = PaperTradingService()
        paper_state = paper_service.current_state(paper_portfolio_id)
        paper_nav = (
            f"${Decimal(str(paper_state['nav'])):,.2f}"
            if paper_state["nav"] is not None
            else "UNAVAILABLE (POSITIONS REQUIRE MARKS)"
        )
        console.print(
            Panel(
                f"Portfolio {paper_portfolio_id}\nMode PAPER\n"
                f"NAV {paper_nav}\n"
                f"Cash ${Decimal(str(paper_state['cash'])):,.2f}\n"
                "Production signal remains independently gated.\n"
                "PAPER / SIMULATION ONLY",
                title="PAPER PORTFOLIO READY / FORWARD TEST AVAILABLE",
                border_style="yellow",
            )
        )
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


def _parse_position_spec(value: str) -> tuple[str, str, str | None]:
    """Parse one ``TICKER=SHARES[:AVERAGE_COST]`` entry."""

    if "=" not in value:
        raise ValueError(f"position must use TICKER=SHARES[:AVG_COST] format: {value!r}")
    ticker, _, rest = value.partition("=")
    shares, _, cost = rest.partition(":")
    return ticker.strip(), shares.strip(), (cost.strip() or None)


def _portfolio_init_wizard(service: ApplicationService, args: argparse.Namespace) -> int:
    """Interactive real-ledger initialization with cancel, retry and confirmation."""

    from personal_alpha_terminal.portfolio.portfolio_validation import (
        PortfolioValidationError,
        ValidatedPosition,
        validate_average_cost,
        validate_cash,
        validate_shares,
        validate_ticker,
    )

    create = service.create_portfolio_with_positions
    console.print(
        Panel(
            "REAL PORTFOLIO LEDGER\n"
            "Broker connection: NONE. Orders are always manual at Charles Schwab.\n"
            "Type 'cancel' at any prompt to abort without saving anything.",
            title="PORTFOLIO INITIALIZATION",
            border_style="cyan",
        )
    )

    def prompt(message: str) -> str:
        answer = console.input(f"{message} ").strip()
        if answer.lower() == "cancel":
            raise KeyboardInterrupt
        return answer

    try:
        name = args.name
        while True:
            entered = prompt(f"Portfolio name [{name}]:")
            if entered:
                name = entered
            if name.strip():
                break
            console.print("[red]Portfolio name must not be empty.[/red]")

        cash = None
        while cash is None:
            raw = prompt("Cash balance (USD):")
            try:
                cash = validate_cash(raw)
            except PortfolioValidationError as error:
                console.print(f"[red]{error}; please re-enter cash.[/red]")

        positions: list[ValidatedPosition] = []
        console.print(
            "Enter positions as TICKER=SHARES[:AVERAGE_COST], one per line.\n"
            "Average cost is optional. Press Enter on an empty line when done."
        )
        while True:
            raw = prompt(f"Position {len(positions) + 1} (blank line to finish):")
            if not raw:
                break
            try:
                ticker_text, shares_text, cost_text = _parse_position_spec(raw)
                ticker = validate_ticker(ticker_text)
                shares = validate_shares(shares_text)
                average_cost = (
                    validate_average_cost(cost_text) if cost_text not in (None, "") else None
                )
                if any(ticker == item.ticker for item in positions):
                    console.print(f"[red]Duplicate ticker {ticker}; please re-enter.[/red]")
                    continue
                positions.append(ValidatedPosition(ticker, shares, average_cost))
                console.print(f"[green]Added {ticker}: {shares} shares.[/green]")
            except (PortfolioValidationError, ValueError) as error:
                console.print(f"[red]{error}; please re-enter the position.[/red]")

        table = Table(title="PORTFOLIO INITIALIZATION SUMMARY")
        table.add_column("Item")
        table.add_column("Value", justify="right")
        table.add_row("Name", name)
        table.add_row("Cash (USD)", str(cash))
        for item in positions:
            table.add_row(
                f"{item.ticker} shares",
                str(item.shares)
                + (f" @ {item.average_cost}" if item.average_cost is not None else ""),
            )
        console.print(table)
        confirmation = prompt("Save this portfolio? [y/N]:")
        if confirmation.lower() not in {"y", "yes"}:
            console.print("Portfolio initialization cancelled; nothing was saved.")
            return 1

        portfolio_id, warnings = create(
            name=name,
            cash_balance=cash,
            currency=args.currency,
            positions=tuple(positions),
            source="cli-interactive",
        )
        console.print(f"Created portfolio id={portfolio_id}; broker connection: NONE")
        for warning in warnings:
            console.print(f"WARNING: {warning}")
        return 0
    except (KeyboardInterrupt, EOFError):
        console.print("Portfolio initialization cancelled; nothing was saved.")
        return 1


def _portfolio_command(args: argparse.Namespace) -> int:
    if args.command == "portfolio-init" and getattr(args, "mode", "real") == "paper":
        from personal_alpha_terminal.paper_trading import PaperTradingService

        if getattr(args, "position", None):
            console.print("ERROR: a paper portfolio must start cash-only with zero positions")
            return 2
        if getattr(args, "cash", None) is None:
            console.print("ERROR: --cash is required; paper cash is never assumed")
            return 2
        if not getattr(args, "portfolio_id", None):
            console.print("ERROR: --portfolio-id is required in paper mode")
            return 2
        paper = PaperTradingService(cast(Path, args.paper_root))
        portfolio = paper.initialize_portfolio(
            portfolio_id=str(args.portfolio_id),
            cash=Decimal(str(args.cash)),
            currency=str(args.currency),
        )
        experiment_id = str(
            args.experiment_id or f"paper-usadaptive-v1-{datetime.now(UTC).date():%Y%m%d}"
        )
        experiment = paper.freeze_experiment(
            portfolio_id=str(args.portfolio_id), experiment_id=experiment_id
        )
        console.print(
            Panel(
                f"Portfolio {portfolio['portfolio_id']}\n"
                "Mode PAPER\n"
                f"NAV ${Decimal(str(portfolio['starting_nav'])):,.2f}\n"
                f"Cash ${Decimal(str(portfolio['initial_cash'])):,.2f}\n"
                "Invested $0.00\nCash Weight 100%\nPositions NONE\n\n"
                f"Experiment {experiment['paper_experiment_id']}\n"
                "PAPER / SIMULATION ONLY",
                title="PAPER PORTFOLIO READY",
                border_style="yellow",
            )
        )
        return 0
    service = _service_for_args(args)
    if args.command == "portfolio-init":
        interactive = (
            sys.stdin.isatty()
            and os.environ.get("PAT_NONINTERACTIVE") != "1"
            and getattr(args, "cash", None) is None
        )
        if interactive:
            return _portfolio_init_wizard(service, args)
        if getattr(args, "cash", None) is None:
            console.print(
                "ERROR: --cash is required (or run interactively). Cash is never assumed."
            )
            return 2
        from personal_alpha_terminal.portfolio.portfolio_validation import (
            PortfolioValidationError as _ValidationError,
        )
        from personal_alpha_terminal.portfolio.portfolio_validation import (
            validate_cash,
            validate_positions,
        )

        try:
            cash = validate_cash(args.cash)
            raw_rows: list[tuple[object, object, object | None]] = []
            for spec in getattr(args, "position", None) or ():
                ticker, shares, cost = _parse_position_spec(spec)
                raw_rows.append((ticker, shares, cost))
            positions = validate_positions(raw_rows)
        except (_ValidationError, ValueError) as error:
            console.print(f"ERROR: {error}")
            return 2
        try:
            portfolio_id, warnings = service.create_portfolio_with_positions(
                name=args.name,
                cash_balance=cash,
                currency=args.currency,
                positions=positions,
                source="cli-manual",
            )
        except ValueError as error:
            console.print(f"ERROR: {error}")
            return 2
        console.print(f"Created portfolio id={portfolio_id}; broker connection: NONE")
        for warning in warnings:
            console.print(f"WARNING: {warning}")
        return 0
    if args.command == "portfolio-import":
        cash_override = None
        if getattr(args, "cash", None) is not None:
            from personal_alpha_terminal.portfolio.portfolio_validation import (
                PortfolioValidationError,
                validate_cash,
            )

            try:
                cash_override = validate_cash(args.cash)
            except PortfolioValidationError as error:
                console.print(f"ERROR: {error}")
                return 2
        parsed = service.preview_portfolio_csv(source=args.csv)
        if cash_override is not None and parsed.cash_balance is not None:
            console.print("WARNING: explicit --cash overrides the cash row found in the CSV.")
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
        effective_cash = cash_override if cash_override is not None else parsed.cash_balance
        if effective_cash is not None:
            table.add_row("CASH", str(effective_cash), "--")
        else:
            table.add_row("CASH", "(unchanged; not specified)", "--")
        console.print(table)
        for warning in parsed.warnings:
            console.print(f"WARNING: {warning}")
        if not args.commit:
            console.print("Preview only. Re-run with --commit to update the real portfolio ledger.")
            return 0
        try:
            result = service.import_portfolio_csv(
                portfolio_id=args.portfolio_id,
                source=args.csv,
                as_of_date=date.fromisoformat(args.as_of),
                cash_override=cash_override,
            )
        except ValueError as error:
            console.print(f"ERROR: {error}")
            return 2
        console.print(
            f"Committed {result.imported_count} positions; "
            f"unmatched={len(result.unmatched_symbols)}; format={result.format_name}"
        )
        console.print(
            "Cash updated"
            if result.cash_balance_updated
            else "Cash unchanged (no explicit cash provided)"
        )
        for warning in result.warnings:
            console.print(f"WARNING: {warning}")
        return 0
    if args.command == "portfolio-show":
        status = service.get_portfolio_status(int(args.portfolio_id))
        console.print(
            f"id={status['id']} name={status['name']} currency={status['currency']} "
            f"cash={status['cash']} as_of={status['as_of']}"
        )
        table = Table(title="REAL PORTFOLIO / MANUAL SCHWAB LEDGER")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Average cost", justify="right")
        position_rows = cast(tuple[dict[str, object], ...], status["positions"])
        for item in position_rows:
            table.add_row(
                str(item["symbol"]),
                str(item["shares"]),
                str(item["average_cost"] if item["average_cost"] is not None else "--"),
            )
        console.print(table)
        return 0
    portfolios = service.list_portfolios()
    if not portfolios:
        console.print(
            "QUANT ANALYSIS READY · PORTFOLIO REQUIRED · TRADING BLOCKED\n"
            "No real portfolio configured. Run portfolio-init or portfolio-import."
        )
        return 3
    for item in portfolios:
        console.print(
            f"id={item['id']} name={item['name']} currency={item['base_currency']} "
            f"cash={item['cash_balance']}"
        )
    return 0


def _paper_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.paper_trading import PaperTradingService
    from personal_alpha_terminal.paper_trading.service import (
        PaperDecisionChoice,
        PaperExecutionBar,
        PaperSignalInput,
    )

    service = PaperTradingService(cast(Path, args.paper_root))
    portfolio_id = str(args.portfolio_id)
    if args.command == "paper-status":
        state = service.current_state(portfolio_id)
        experiment = service.experiment(portfolio_id)
        nav_text = (
            f"${Decimal(str(state['nav'])):,.2f}"
            if state["nav"] is not None
            else "UNAVAILABLE (POSITIONS REQUIRE MARKS)"
        )
        console.print(
            Panel(
                f"Portfolio {portfolio_id}\nMode PAPER\n"
                f"NAV {nav_text}\n"
                f"Cash ${Decimal(str(state['cash'])):,.2f}\n"
                f"Positions {len(cast(dict[str, str], state['positions']))}\n"
                f"Experiment {experiment['paper_experiment_id']}\n"
                "Production approved FALSE\nPAPER / SIMULATION ONLY",
                title="PAPER FORWARD TEST READY",
                border_style="yellow",
            )
        )
        return 0
    if args.command == "paper-actions":
        actions = service.actions(portfolio_id)
        if not actions:
            console.print("PAPER / SIMULATION ONLY: no proposed paper actions")
            return 0
        table = Table(title="PROPOSED PAPER ACTIONS / NOT FOR REAL TRADING")
        for column in ("Action ID", "Side", "Ticker", "Qty", "User decision", "Fill"):
            table.add_column(column)
        for item in actions:
            table.add_row(
                str(item["action_id"]),
                str(item["side"]),
                str(item["ticker"]),
                str(item["quantity"]),
                str(item["user_paper_decision"]),
                str(item["simulated_fill"]),
            )
        console.print(table)
        return 0
    if args.command == "paper-confirm":
        result = service.confirm_action(
            portfolio_id=portfolio_id,
            action_id=str(args.action_id),
            choice=PaperDecisionChoice(str(args.decision).upper()),
            reason=str(args.reason),
        )
        console.print(
            f"PAPER decision recorded: {result['action_id']} "
            f"{result['user_paper_decision']} (no automatic fill)"
        )
        return 0
    if args.command == "paper-fill":
        result = service.simulate_fill(
            portfolio_id=portfolio_id,
            action_id=str(args.action_id),
            bar=PaperExecutionBar(
                ticker=str(args.ticker).upper(),
                session_date=date.fromisoformat(str(args.session_date)),
                open_price=Decimal(str(args.open)),
                available_at=datetime.fromisoformat(str(args.available_at)),
                average_daily_dollar_volume=Decimal(str(args.adv)),
                source=str(args.source),
                data_hash=str(args.data_hash),
            ),
            fill_time=datetime.fromisoformat(str(args.fill_time)),
        )
        console.print(
            f"SIMULATED PAPER FILL {result['fill_id']} at {result['fill_price']}; "
            "no broker order was sent"
        )
        return 0
    if args.command == "paper-performance":
        console.print(json.dumps(service.performance(portfolio_id), indent=2, sort_keys=True))
        return 0
    if args.command == "paper-run":
        experiment = service.experiment(portfolio_id)
        config = load_config(args.config)
        certificates = sorted(
            (config.report_dir / "daily-runs").glob("*/run_certificate.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not certificates:
            raise ValueError("NO_PERSISTED_RUN; run daily first")
        certificate = json.loads(certificates[0].read_text(encoding="utf-8"))
        analysis_date = date.fromisoformat(str(certificate["analysis_date"]))
        as_of = datetime.combine(analysis_date, datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=21
        )
        cutoff = datetime.fromisoformat(str(certificate["data_cutoff"]))
        traces = cast(dict[str, dict[str, object]], certificate.get("decision_traces", {}))
        inputs = tuple(
            PaperSignalInput(
                ticker=ticker,
                security_id=ticker,
                composite=float(str(trace["composite_alpha"])),
                expected_alpha=float(str(trace["expected_alpha"])),
                rank=int(str(trace["cross_sectional_rank"])),
                factor_values=cast(dict[str, float], trace["factor_neutralized_values"]),
            )
            for ticker, trace in traces.items()
        )
        provenance = cast(dict[str, object], certificate["provenance"])
        signals = service.record_signals(
            portfolio_id=portfolio_id,
            experiment_id=str(experiment["paper_experiment_id"]),
            as_of=as_of,
            cutoff=cutoff,
            trade_date=date.fromisoformat(str(certificate["trade_date"])),
            data_hash=str(provenance["data_hash"]),
            universe_version=str(provenance["universe_version"]),
            signals=inputs,
        )
        actions = service.propose_actions(
            portfolio_id=portfolio_id,
            experiment_id=str(experiment["paper_experiment_id"]),
            signal_ids=tuple(str(item["signal_id"]) for item in signals),
            prices={},
            sectors={},
            average_daily_dollar_volume={},
            risk_validated=False,
            decision_time=datetime.now(UTC),
        )
        console.print(
            Panel(
                f"Recorded {len(signals)} immutable PAPER_SIGNAL observations.\n"
                f"Proposed actions: {len(actions)}\n"
                "PAPER_RISK_INPUT_NOT_VALIDATED: no action manufactured.\n"
                "Production approval remains FALSE.",
                title="PAPER / SIMULATION ONLY",
                border_style="yellow",
            )
        )
        return 0
    raise ValueError(f"unsupported paper command: {args.command}")


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
        from personal_alpha_terminal.data.market_data.independent_providers import (
            build_independent_provider_router,
        )

        provider_router = build_independent_provider_router(
            cache_dir=config.cache_dir,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            retry_backoff_seconds=config.retry_backoff_seconds,
            twelve_api_key=config.settings.twelve_data_api_key,
            alpha_api_key=config.settings.alpha_vantage_api_key,
            priority=config.independent_provider_priority,
        )
        equity_configured = any(
            item.configured and item.provider_id in {"twelve_data", "alpha_vantage"}
            for item in provider_router.health()
        )
        checks.append(
            (
                "PASS" if equity_configured else "WARN",
                "Optional fallback data",
                (
                    "configured"
                    if equity_configured
                    else "not configured; Yahoo remains primary and strict internal "
                    "certification remains active"
                ),
            )
        )
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


def _provider_command(config_path: Path, action: str, provider_name: str | None) -> int:
    from personal_alpha_terminal.application.universe import ResearchAsset
    from personal_alpha_terminal.data.market_data.independent_providers import (
        AlphaVantageProvider,
        IndependentProviderError,
        TwelveDataProvider,
        build_independent_provider_router,
    )

    config = load_config(config_path)
    router = build_independent_provider_router(
        cache_dir=config.cache_dir,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        retry_backoff_seconds=config.retry_backoff_seconds,
        twelve_api_key=config.settings.twelve_data_api_key,
        alpha_api_key=config.settings.alpha_vantage_api_key,
        priority=config.independent_provider_priority,
    )
    if action == "status":
        table = Table(title="INDEPENDENT DATA PROVIDERS")
        for column in (
            "Provider",
            "Role",
            "Configured",
            "Reachable",
            "Latest session",
            "Last success",
            "Reason",
        ):
            table.add_column(column)
        for item in router.health():
            table.add_row(
                item.provider_id,
                item.role,
                "YES" if item.configured else "NO",
                item.reachable,
                item.latest_session or "--",
                item.last_success or "--",
                item.failure_category or ("AUTH_NOT_CONFIGURED" if not item.configured else "--"),
            )
        console.print(table)
        if not router.twelve.configured and not router.alpha.configured:
            console.print(
                "Optional API fallbacks are not configured; daily readiness is unaffected"
            )
        return 0

    providers = {
        "twelve-data": router.twelve,
        "twelve_data": router.twelve,
        "alpha-vantage": router.alpha,
        "alpha_vantage": router.alpha,
    }
    provider = providers.get(str(provider_name).lower())
    if not isinstance(provider, (TwelveDataProvider, AlphaVantageProvider)):
        raise ValueError("provider test supports twelve-data or alpha-vantage")
    expected = _latest_completed_us_session(datetime.now(UTC))
    asset = ResearchAsset("SPY", "SPDR S&P 500 ETF", "ARCX", "etf", "health")
    try:
        result = provider.fetch(
            asset,
            expected - timedelta(days=120),
            expected,
            expected_latest_session=expected,
        )
    except IndependentProviderError as error:
        console.print(f"{provider.provider_id}: FAIL {error.category.value} ({error})")
        return 3
    console.print(
        f"{provider.provider_id}: PASS latest={result.latest_session} "
        f"rows={len(result.prices)} cache={result.cache_hit}"
    )
    return 0


def _latest_completed_us_session(now: datetime) -> date:
    import exchange_calendars as xcals  # type: ignore[import-untyped]

    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        (now.date() - timedelta(days=14)).isoformat(), now.date().isoformat()
    )
    completed = [
        session
        for session in sessions
        if calendar.session_close(session).to_pydatetime().astimezone(UTC) <= now
    ]
    if not completed:
        raise RuntimeError("no completed XNYS session is available")
    return date.fromisoformat(str(completed[-1].date()))


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


def _research_data_command(args: argparse.Namespace) -> int:
    """Operate the isolated historical research-data store only."""

    from personal_alpha_terminal.application.research_data_service import (
        audit_local_live_inventory,
        import_and_certify_research_data,
        read_latest_research_manifest,
        recertify_latest_research_data,
    )

    action = str(args.research_data_action)
    root = cast(Path, args.root)
    if action == "audit":
        audit = audit_local_live_inventory(cast(Path, args.database), datetime.now(UTC))
        console.print(json.dumps(audit.document(), ensure_ascii=False, indent=2, sort_keys=True))
        return 3
    if action == "import":
        manifest, path = import_and_certify_research_data(
            cast(Path, args.path),
            root,
            required_start=(
                date.fromisoformat(args.required_start) if args.required_start else None
            ),
            required_end=(date.fromisoformat(args.required_end) if args.required_end else None),
        )
        console.print(json.dumps(manifest.document(), ensure_ascii=False, indent=2, sort_keys=True))
        console.print(f"Manifest: {path.resolve()}")
        return 0 if manifest.certification_state.value == "CERTIFIED" else 3
    if action == "certify":
        certified = recertify_latest_research_data(root)
        if certified is None:
            console.print("NOT_CERTIFIABLE: no imported historical research dataset")
            return 3
        manifest, path = certified
        console.print(json.dumps(manifest.document(), ensure_ascii=False, indent=2, sort_keys=True))
        console.print(f"Reproduced manifest: {path.resolve()}")
        return 0 if manifest.certification_state.value == "CERTIFIED" else 3
    latest = read_latest_research_manifest(root)
    if latest is None:
        console.print("NOT_CERTIFIABLE: no imported historical research dataset")
        return 3
    path, document = latest
    if action == "manifest":
        console.print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        console.print(f"Manifest: {path.resolve()}")
    else:
        table = Table(title="RESEARCH DATA STATUS")
        table.add_column("Field")
        table.add_column("Value")
        for key in (
            "certification_state",
            "date_start",
            "date_end",
            "security_count",
            "membership_count",
            "delisted_count",
            "corporate_action_count",
            "calendar_session_count",
            "content_hash",
            "production_eligible",
        ):
            table.add_row(key, str(document.get(key)))
        table.add_row("blockers", ", ".join(document.get("blockers", [])))
        console.print(table)
        console.print(f"Manifest: {path.resolve()}")
    return 0 if document.get("certification_state") == "CERTIFIED" else 3


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


def _render_persisted_section(config_path: Path, section: str, run_id: str | None) -> int:
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


def _verify_recommendation_run(config_path: Path, run_id: str, recommendation_id: str) -> None:
    path = _certificate_path(config_path, run_id)
    certificate = json.loads(path.read_text(encoding="utf-8"))
    decisions = certificate.get("decision_recommendations", [])
    identifiers = {
        str(item.get("recommendation_id")) for item in decisions if isinstance(item, dict)
    }
    if recommendation_id not in identifiers:
        raise ValueError(
            f"recommendation {recommendation_id} is not bound to immutable run {run_id}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PersonalAlphaTerminal")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--paper-portfolio-id", default=None)
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
    research_data = subparsers.add_parser(
        "research-data", help="Audit or import isolated historical research data"
    )
    research_data.add_argument("--root", type=Path, default=Path("var/research-data"))
    research_data.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    research_actions = research_data.add_subparsers(dest="research_data_action", required=True)
    research_actions.add_parser("status")
    research_actions.add_parser("audit")
    research_actions.add_parser("certify")
    research_actions.add_parser("manifest")
    research_import = research_actions.add_parser("import")
    research_import.add_argument("path", type=Path)
    research_import.add_argument("--required-start", default=None)
    research_import.add_argument("--required-end", default=None)
    subparsers.add_parser("backtest", help="Check the PIT backtest execution gate")
    subparsers.add_parser("init-config")
    data_provider = subparsers.add_parser(
        "data-provider", help="Inspect optional market-data fallbacks without running strategy"
    )
    provider_subcommands = data_provider.add_subparsers(dest="provider_action", required=True)
    provider_subcommands.add_parser("status")
    provider_test = provider_subcommands.add_parser("test")
    provider_test.add_argument("provider", choices=("twelve-data", "alpha-vantage"))
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
    portfolio_init.add_argument("--cash", type=float, default=None)
    portfolio_init.add_argument("--currency", default="USD")
    portfolio_init.add_argument("--portfolio-id", default=None)
    portfolio_init.add_argument("--mode", choices=("real", "paper"), default="real")
    portfolio_init.add_argument("--paper-root", type=Path, default=Path("var/paper-trading"))
    portfolio_init.add_argument("--experiment-id", default=None)
    portfolio_init.add_argument(
        "--position",
        action="append",
        default=None,
        help="TICKER=SHARES[:AVERAGE_COST]; repeat for each position",
    )
    portfolio_import = subparsers.add_parser("portfolio-import")
    portfolio_import.add_argument("csv", type=Path)
    portfolio_import.add_argument("--portfolio-id", type=int, required=True)
    portfolio_import.add_argument("--as-of", required=True)
    portfolio_import.add_argument("--commit", action="store_true")
    portfolio_import.add_argument(
        "--cash",
        type=float,
        default=None,
        help="Explicit cash balance; never assumed when omitted",
    )
    subparsers.add_parser("portfolio-list")
    subparsers.add_parser("portfolio", help="Alias for portfolio-list")
    portfolio_show = subparsers.add_parser("portfolio-show")
    portfolio_show.add_argument("--portfolio-id", required=True)
    for paper_name in ("paper-status", "paper-run", "paper-actions", "paper-performance"):
        paper_parser = subparsers.add_parser(paper_name)
        paper_parser.add_argument("--portfolio-id", default="paper-100k")
        paper_parser.add_argument("--paper-root", type=Path, default=Path("var/paper-trading"))
    paper_confirm = subparsers.add_parser("paper-confirm")
    paper_confirm.add_argument("action_id")
    paper_confirm.add_argument("--portfolio-id", default="paper-100k")
    paper_confirm.add_argument("--paper-root", type=Path, default=Path("var/paper-trading"))
    paper_confirm.add_argument("--decision", choices=("accept", "reject", "skip"), required=True)
    paper_confirm.add_argument("--reason", default="")
    paper_fill = subparsers.add_parser("paper-fill")
    paper_fill.add_argument("action_id")
    paper_fill.add_argument("--portfolio-id", default="paper-100k")
    paper_fill.add_argument("--paper-root", type=Path, default=Path("var/paper-trading"))
    paper_fill.add_argument("--ticker", required=True)
    paper_fill.add_argument("--session-date", required=True)
    paper_fill.add_argument("--open", type=float, required=True)
    paper_fill.add_argument("--adv", type=float, required=True)
    paper_fill.add_argument("--available-at", required=True)
    paper_fill.add_argument("--fill-time", required=True)
    paper_fill.add_argument("--source", required=True)
    paper_fill.add_argument("--data-hash", required=True)
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
        if command == "data-provider":
            return _provider_command(
                args.config, args.provider_action, getattr(args, "provider", None)
            )
        if command == "research":
            return _research(args.config)
        if command == "research-data":
            return _research_data_command(args)
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
        if command in {
            "paper-status",
            "paper-run",
            "paper-actions",
            "paper-confirm",
            "paper-fill",
            "paper-performance",
        }:
            return _paper_command(args)
        if command == "refresh":
            return run_daily(
                args.config,
                refresh=True,
                paper_portfolio_id=args.paper_portfolio_id,
            )
        if command in {"data", "factors", "probability", "risk", "decisions"}:
            return _render_persisted_section(args.config, command, args.run_id)
        return run_daily(
            args.config,
            refresh=not args.no_refresh,
            paper_portfolio_id=args.paper_portfolio_id,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Command failed")
        console.print(f"ERROR: {type(error).__name__}: {error}")
        return 2
