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

from personal_alpha_terminal.terminal.broad_universe_cli import broad_universe_command
from personal_alpha_terminal.terminal.config import default_config_text, load_config
from personal_alpha_terminal.terminal.daily_renderer import render_daily_quant_result
from personal_alpha_terminal.terminal.forward_track_cli import forward_track_command
from personal_alpha_terminal.terminal.intelligence_cli import intelligence_command
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar
from personal_alpha_terminal.terminal.round7_cli import round7_research_command
from personal_alpha_terminal.terminal.round8_cli import round8_research_command
from personal_alpha_terminal.terminal.round9_cli import round9_research_command

if TYPE_CHECKING:
    from personal_alpha_terminal.application import ApplicationService
    from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig

console = Console()
logger = logging.getLogger(__name__)


def _probability_assessment_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.quant_engine.probability_assessment import (
        ProbabilityAssessmentRegistry,
        build_round4_probability_assessment,
    )

    config = load_config(args.config)
    assessment = build_round4_probability_assessment(
        args.source,
        strategy_parameter_hash=config.strategy_parameter_hash,
    )
    path = ProbabilityAssessmentRegistry(config.validation_artifact_dir).write(assessment)
    console.print(
        json.dumps(
            {
                "assessment_id": assessment.assessment_id,
                "verdict": assessment.verdict,
                "production_influence": assessment.production_influence,
                "blockers": assessment.blockers,
                "artifact_hash": assessment.artifact_hash,
                "path": str(path.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _llm_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.intelligence.llm_runtime import (
        DEFAULT_LLM_RUNTIME_STATUS_PATH,
        llm_runtime_status,
        test_llm_runtime,
    )

    config = load_config(args.config)
    status_path = DEFAULT_LLM_RUNTIME_STATUS_PATH
    status = (
        test_llm_runtime(config.settings, status_path)
        if args.llm_action == "test"
        else llm_runtime_status(config.settings, status_path)
    )
    console.print(json.dumps(status.public_document(), indent=2, sort_keys=True))
    if args.llm_action == "test" and status.connectivity != "AVAILABLE":
        console.print(
            f"LLM test: {status.error_classification or status.connectivity}; "
            "Classical Quant Core continues."
        )
        return 3
    return 0


def run_daily(
    config_path: Path,
    *,
    refresh: bool = True,
    wait: bool = True,
    locale: str = "zh-CN",
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
    if locale == "zh-CN":
        render_daily_quant_result(result, console)
    else:
        render_daily_quant_result(result, console, locale=locale)
    console.print(f"\nRun snapshot directory: {(config.report_dir / 'daily-runs').resolve()}")
    if wait and sys.stdin.isatty() and os.environ.get("PAT_NONINTERACTIVE") != "1":
        try:
            console.input("\nPress Enter to exit")
        except EOFError:
            logger.info("Skipping exit prompt because stdin reached EOF")
    return 0 if result.actionable else 3


def _operational_policy_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.application.operational_readiness import (
        DEFAULT_ALLOWED_RESEARCH_STATES,
        OperationalPolicyDecision,
        OperationalPolicyStore,
        issue_operational_policy,
        resolve_current_operational_identity,
    )
    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )

    config = load_config(args.config)
    store = OperationalPolicyStore(config.operational_policy_path)
    now = datetime.now(UTC)
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    identity = resolve_current_operational_identity(
        config,
        strategy,
        decision_time=now,
    )
    if args.operational_policy_action in {"status", "show"}:
        status = store.status(
            identity,
            research_state="NOT_CERTIFIABLE",
            now=now,
        )
        document = status.public_document()
        console.print(
            Panel(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                title="OPERATIONAL POLICY STATUS",
                border_style="green" if status.effective else "yellow",
            )
        )
        report = {
            "report": "CURRENT_OPERATIONAL_IDENTITY_REPORT",
            "generated_at": now.isoformat(),
            "current_identity": identity.document(),
            **document,
        }
        report_path = (
            config.operational_policy_path.parent
            / "CURRENT_OPERATIONAL_IDENTITY_REPORT.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(report_path)
        console.print(f"Identity report: {report_path.resolve()}")
        return 0
    decision = OperationalPolicyDecision(args.decision.upper())
    created_at = now
    expires_at = created_at + timedelta(days=7)
    if args.expires_at:
        expires_at = datetime.combine(
            date.fromisoformat(args.expires_at),
            datetime.min.time(),
            tzinfo=UTC,
        )
    summary = {
        "Decision": decision.value,
        "Identity Schema": identity.schema_version,
        "Current Identity Hash": identity.identity_hash,
        "Strategy": f"{identity.strategy_name}:{identity.strategy_version}",
        "Probability Artifact Hash": identity.probability_artifact_hash,
        "Probability Production Influence": identity.probability_production_influence,
        "LLM Influence Identity": identity.llm_influence_identity,
        "Expires At": expires_at.isoformat(),
        "Research Certification Changed": False,
        "Automatic Execution": False,
    }
    console.print(
        Panel(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            title="OPERATIONAL POLICY CREATE / CONFIRM CURRENT IDENTITY",
            border_style="yellow",
        )
    )
    confirmation = f"CREATE {decision.value} {identity.identity_hash}"
    if (
        not sys.stdin.isatty()
        or os.environ.get("PAT_NONINTERACTIVE") == "1"
    ):
        console.print(
            "Interactive confirmation required. Run exactly:\n"
            f"python main.py operational-policy create --decision {decision.value}"
        )
        return 3
    entered = console.input(f"Type exactly to confirm:\n{confirmation}\n> ").strip()
    if entered != confirmation:
        console.print("Confirmation did not match; no policy was created.")
        return 3
    policy = issue_operational_policy(
        identity=identity,
        decision=decision,
        research_states_allowed=(
            DEFAULT_ALLOWED_RESEARCH_STATES
            if decision is OperationalPolicyDecision.ALLOW_PROVISIONAL
            else ()
        ),
        issued_by="USER:cli:operational-policy:create",
        reason=args.reason,
        created_at=created_at,
        expires_at=expires_at,
    )
    store.save(policy, force=True)
    console.print(
        Panel(
            json.dumps(
                policy.document(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            title=f"OPERATIONAL POLICY SAVED / {policy.policy_id}",
            border_style="green",
        )
    )
    console.print(f"Policy path: {config.operational_policy_path.resolve()}")
    console.print(
        "Research certification is unchanged. This policy only permits degraded "
        "production advice for the exact bound strategy/config identity."
    )
    return 0


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
        override_provenance=args.override_provenance,
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
        name = args.portfolio_id
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
                name=args.portfolio_id,
                cash_balance=cash,
                currency=args.currency,
                positions=positions,
                source="cli-manual",
            )
        except ValueError as error:
            console.print(f"ERROR: {error}")
            return 2
        status = service.get_portfolio_status(args.portfolio_id)
        console.print(
            f"Portfolio {status['portfolio_id']} | NAV ${status['nav']:,.2f} | "
            f"Cash ${status['cash']:,.2f} | Invested $0.00 | Cash Weight 100% | Positions NONE\n"
            f"Internal id={portfolio_id}; broker connection: NONE; manual execution only"
        )
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
    if args.command == "portfolio-update":
        from personal_alpha_terminal.portfolio.portfolio_validation import validate_positions

        raw_rows = []
        for spec in args.position or ():
            ticker, shares, cost = _parse_position_spec(spec)
            raw_rows.append((ticker, shares, cost))
        result = service.update_portfolio_snapshot(
            portfolio_id=args.portfolio_id,
            as_of_date=date.fromisoformat(args.as_of),
            positions=validate_positions(raw_rows),
            cash_balance=(Decimal(str(args.cash)) if args.cash is not None else None),
        )
        console.print(
            f"Updated {args.portfolio_id}: positions={result.imported_count}; "
            f"cash={'updated' if result.cash_balance_updated else 'unchanged'}; "
            f"as_of={result.as_of_date}"
        )
        return 0
    if args.command == "portfolio-show":
        status = service.get_portfolio_status(args.portfolio_id)
        console.print(
            f"portfolio_id={status['portfolio_id']} internal_id={status['id']} "
            f"currency={status['currency']} NAV={status['nav']} "
            f"cash={status['cash']} invested={status['invested']} "
            f"cash_weight={status['cash_weight']} as_of={status['as_of']}"
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
            f"portfolio_id={item['portfolio_id']} internal_id={item['id']} "
            f"currency={item['base_currency']} "
            f"cash={item['cash_balance']}"
        )
    return 0


def _doctor(config_path: Path) -> int:
    checks: list[tuple[str, str, str]] = []
    try:
        config = load_config(config_path)
        checks.append(("PASS", "Config", str(config_path.resolve())))
        checks.append(("PASS", "Python interpreter", sys.executable))
        checks.append(
            (
                "PASS",
                "Python version",
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            )
        )
        checks.append(
            (
                "PASS" if sys.prefix != sys.base_prefix else "WARN",
                "Virtual environment",
                sys.prefix,
            )
        )
        dependency_checks = []
        try:
            import exchange_calendars  # type: ignore[import-untyped]  # noqa: F401
            dependency_checks.append("exchange_calendars=PASS")
        except ImportError:
            dependency_checks.append("exchange_calendars=FAIL")
        try:
            import openai  # noqa: F401
            dependency_checks.append("openai=PASS")
        except ImportError:
            dependency_checks.append("openai=FAIL")
        checks.append(
            (
                "FAIL" if any(item.endswith("=FAIL") for item in dependency_checks) else "PASS",
                "Runtime dependencies",
                "; ".join(dependency_checks),
            )
        )
        checks.append(
            (
                "PASS" if os.environ.get("SEC_EDGAR_USER_AGENT", "").strip() else "WARN",
                "SEC_EDGAR_USER_AGENT",
                "PRESENT" if os.environ.get("SEC_EDGAR_USER_AGENT", "").strip() else "MISSING",
            )
        )
        checks.append(
            (
                "PASS" if config.settings.deepseek_api_key else "WARN",
                "DeepSeek credential",
                "PRESENT" if config.settings.deepseek_api_key else "MISSING",
            )
        )
        from personal_alpha_terminal.intelligence.llm_runtime import (
            DEFAULT_LLM_RUNTIME_STATUS_PATH,
            llm_runtime_status,
        )

        runtime = llm_runtime_status(config.settings, DEFAULT_LLM_RUNTIME_STATUS_PATH)
        checks.append(
            (
                "PASS" if runtime.connectivity == "AVAILABLE" else "WARN",
                "DeepSeek connectivity",
                runtime.connectivity,
            )
        )
        from personal_alpha_terminal.application.operational_readiness import (
            OperationalPolicyStore,
            resolve_current_operational_identity,
        )
        from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
            USAdaptiveAlphaCoreV1,
        )

        now = datetime.now(UTC)
        identity = resolve_current_operational_identity(
            config,
            USAdaptiveAlphaCoreV1(config.strategy),
            decision_time=now,
        )
        policy_status = OperationalPolicyStore(config.operational_policy_path).status(
            identity,
            research_state="NOT_CERTIFIABLE",
            now=now,
        )
        policy = policy_status.public_document()
        checks.append(
            (
                "PASS" if policy_status.effective else "WARN",
                "OperationalPolicy",
                policy_status.status.value,
            )
        )
        checks.append(("PASS", "Policy identity", policy_status.current_identity_hash))
        checks.append(
            (
                "PASS",
                "Policy mismatch fields",
                json.dumps(policy.get("Mismatch Fields", {}), sort_keys=True),
            )
        )
        local_now = datetime.now().astimezone()
        checks.append(
            (
                "PASS",
                "Timezone/system clock",
                f"{local_now.isoformat()} {local_now.tzname()}",
            )
        )
        checks.append(
            (
                "PASS" if len(config.provider_priority) >= 2 else "WARN",
                "Provider order",
                " -> ".join(config.provider_priority),
            )
        )
        for label, directory in (
            ("Cache", config.cache_dir),
            ("Reports", config.report_dir),
            ("Var", Path("var")),
        ):
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
        from sqlalchemy import func, select

        from personal_alpha_terminal.data.database import get_session_factory
        from personal_alpha_terminal.models import (
            IntelligenceEvent,
            IntelligenceRawInformation,
            Price,
        )

        with get_session_factory()() as session:
            market_rows = session.scalar(select(func.count()).select_from(Price)) or 0
            raw_rows = (
                session.scalar(select(func.count()).select_from(IntelligenceRawInformation))
                or 0
            )
            event_rows = session.scalar(select(func.count()).select_from(IntelligenceEvent)) or 0
        checks.append(
            ("PASS" if market_rows else "WARN", "Market data storage", f"{market_rows} price rows")
        )
        checks.append(
            ("PASS" if raw_rows else "WARN", "Intelligence raw corpus", f"{raw_rows} raw documents")
        )
        checks.append(
            ("PASS" if event_rows else "WARN", "Intelligence events", f"{event_rows} events")
        )
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
    import exchange_calendars as xcals

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
        acquire_available_historical_data,
        audit_local_live_inventory,
        audited_provider_capabilities,
        import_and_certify_research_data,
        read_latest_acquisition_manifest,
        read_latest_research_manifest,
        recertify_latest_research_data,
    )

    action = str(args.research_data_action)
    root = cast(Path, args.root)
    if action == "providers":
        table = Table(title="历史研究数据 Provider 能力（官方资料审计）")
        for column in (
            "Provider", "价格", "退市", "永久ID", "历史成员", "公司行动", "PIT/Vintage", "认证等级"
        ):
            table.add_column(column)
        for item in audited_provider_capabilities():
            table.add_row(
                item.provider_id,
                item.raw_ohlcv.value,
                item.delisted_securities.value,
                item.permanent_identifiers.value,
                item.historical_membership.value,
                item.corporate_actions.value,
                item.pit_vintages.value,
                item.certification_grade,
            )
        console.print(table)
        return 0
    if action == "acquire":
        baseline, acquisition, baseline_path, acquisition_path = (
            acquire_available_historical_data(
                config_path=cast(Path, args.config),
                database=cast(Path, args.database),
                root=root,
            )
        )
        console.print(
            json.dumps(acquisition.document(), ensure_ascii=False, indent=2, sort_keys=True)
        )
        console.print(f"Research baseline: {baseline.research_baseline_id}")
        console.print(f"Baseline: {baseline_path.resolve()}")
        console.print(f"Manifest: {acquisition_path.resolve()}")
        return 0 if acquisition.production_eligible else 3
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
        latest_acquisition = read_latest_acquisition_manifest(root)
        if latest_acquisition is None:
            console.print("NOT_CERTIFIABLE: no imported or acquired historical research dataset")
            return 3
        path, document = latest_acquisition
        if action == "manifest":
            console.print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
            console.print(f"Manifest: {path.resolve()}")
        else:
            table = Table(title="历史研究数据状态")
            table.add_column("字段")
            table.add_column("值")
            for key in (
                "classification",
                "actual_price_start",
                "actual_price_end",
                "current_directory_securities",
                "historical_security_count",
                "historical_membership_rows",
                "delisted_count",
                "calendar_sessions",
                "benchmark_rows",
                "research_dataset_content_hash",
                "production_eligible",
            ):
                table.add_row(key, str(document.get(key)))
            table.add_row("blockers", ", ".join(document.get("blockers", [])))
            console.print(table)
            console.print(f"Manifest: {path.resolve()}")
        return 0 if document.get("production_eligible") is True else 3
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


def _round4_research_command(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from personal_alpha_terminal.application.broad_universe_service import (
        BroadUSUniverseService,
    )
    from personal_alpha_terminal.data.us_market.broad_universe import EligibilityRules
    from personal_alpha_terminal.quant_engine.round4_research import (
        run_round4_research,
        write_round4_report,
    )

    config = load_config(args.config)
    engine = create_engine(f"sqlite:///{args.database}")
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    decision_time = (
        datetime.fromisoformat(args.as_of)
        if args.as_of
        else datetime.now(UTC)
    )
    if decision_time.tzinfo is None:
        decision_time = decision_time.replace(tzinfo=UTC)
    try:
        with factory() as session:
            rules = EligibilityRules(**asdict(config.broad_universe))
            selection = BroadUSUniverseService(
                session,
                cache_root=config.cache_dir / "us-current-directory",
                rules=rules,
            ).select(
                universe_date=decision_time.date(),
                decision_time=decision_time,
                reference_symbols=(args.benchmark, config.nasdaq_benchmark),
            )
            report = run_round4_research(
                session,
                decision_time=decision_time,
                history_start=date.fromisoformat(args.history_start),
                benchmark=args.benchmark,
                horizon=args.horizon,
                rules=rules,
                eligibility=selection.eligibility,
            )
        path = write_round4_report(report, args.output)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        console.print(f"ROUND 4 research failed closed: {error}")
        return 2
    console.print("[bold]ROUND 4 RESEARCH[/bold]")
    console.print(
        f"Universe: {report.universe.get('factor_panel_stocks', 0)} factor-eligible stocks "
        f"over {report.universe.get('factor_dates', 0)} dates"
    )
    console.print(f"Survivorship: {report.survivors}")
    calibration = report.calibration
    if calibration is not None:
        console.print(
            f"Probability OOS N={calibration.oos_samples}  Brier={calibration.brier_score:.4f}  "
            f"ECE={calibration.expected_calibration_error:.4f}  ROC-AUC={calibration.roc_auc:.4f}"
        )
    else:
        console.print("Probability: DEGRADED (calibration evidence unavailable)")
    snapshot = report.probability_snapshot
    if isinstance(snapshot, dict) and snapshot.get("rows"):
        rows = snapshot["rows"]
        if isinstance(rows, list) and rows:
            first = rows[0]
            probability = float(first.get("probability") or 0.0)
            multiplier = float(first.get("multiplier") or 0.0)
            adjusted_alpha = float(first.get("adjusted_alpha") or 0.0)
            console.print(
                f"Current probability top row: {first.get('symbol')} "
                f"p={probability:.4f} "
                f"multiplier={multiplier:.4f} "
                f"adjusted_alpha={adjusted_alpha:.6f}"
            )
    ab = report.portfolio_ab
    if ab is not None:
        console.print(
            f"Classical net {ab.classical_net_return:.2%} vs Probability net "
            f"{ab.probability_net_return:.2%}; changed rows {ab.probability_change_count}"
        )
    else:
        console.print("Probability A/B: UNAVAILABLE")
    console.print(f"Report: {path.resolve()}")
    return 0


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


def _maintenance_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.core.retention import (
        apply_runtime_cleanup,
        plan_runtime_cleanup,
        runtime_artifact_status,
    )

    config = load_config(args.config)
    root = config.report_dir.parent
    if args.maintenance_action != "artifacts":
        raise ValueError("unsupported maintenance action")
    if args.artifacts_action == "status":
        table = Table(title="RUNTIME ARTIFACT GOVERNANCE")
        for column in ("Area", "Category", "Retention days", "Files", "Size MB", "Oldest days"):
            table.add_column(
                column,
                justify="right" if column not in {"Area", "Category"} else "left",
            )
        for row in runtime_artifact_status(root):
            table.add_row(
                str(row["area"]),
                str(row["category"]),
                str(row["retention_days"] or "NEVER"),
                str(row["files"]),
                f"{int(str(row['bytes'])) / 1_000_000:.2f}",
                str(row["oldest_days"]),
            )
        console.print(table)
        console.print(
            "CRITICAL / CACHE areas are never eligible for automatic cleanup. "
            "Use `maintenance artifacts cleanup --dry-run` before any deletion."
        )
        return 0
    if args.artifacts_action == "cleanup":
        if args.commit:
            removed = apply_runtime_cleanup(root)
            console.print(f"Removed {len(removed)} expired generated artifact files.")
            return 0
        planned = plan_runtime_cleanup(root, dry_run=True)
        console.print(f"DRY-RUN: {len(planned)} files would be removed.")
        console.print("No files were deleted. Re-run with --commit to apply.")
        return 0
    raise ValueError("unsupported artifacts action")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PersonalAlphaTerminal")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--locale", choices=("zh-CN", "en-US"), default="zh-CN")
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
    probability_assessment = subparsers.add_parser(
        "probability-assessment",
        help="Materialize the immutable real-evidence probability fallback assessment",
    )
    probability_assessment.add_argument(
        "--source", type=Path, default=Path("var/round4-research/latest.json")
    )
    llm = subparsers.add_parser("llm", help="Sanitized optional LLM runtime diagnostics")
    llm_actions = llm.add_subparsers(dest="llm_action", required=True)
    llm_actions.add_parser("status", help="Show sanitized DeepSeek runtime status")
    llm_actions.add_parser("test", help="Run one minimal structured DeepSeek API call")
    operational_policy = subparsers.add_parser(
        "operational-policy",
        help="Inspect or explicitly create the persistent operational policy",
    )
    operational_policy_actions = operational_policy.add_subparsers(
        dest="operational_policy_action",
        required=True,
    )
    operational_policy_actions.add_parser(
        "status",
        help="Show sanitized current/stored identity status and exact mismatch fields",
    )
    operational_policy_actions.add_parser(
        "show",
        help="Compatibility alias for status",
    )
    operational_policy_create = operational_policy_actions.add_parser(
        "create",
        help="Explicitly create and activate an immutable finite operational policy",
    )
    operational_policy_set = operational_policy_actions.add_parser(
        "set",
        help="Deprecated compatibility alias for create",
    )
    for policy_parser in (operational_policy_create, operational_policy_set):
        policy_parser.add_argument(
        "--decision",
        choices=("ALLOW_PROVISIONAL", "BLOCK"),
        required=True,
        )
        policy_parser.add_argument(
            "--reason",
            default=(
                "Explicit temporary operational advisory authorization; "
                "research certification remains unchanged."
            ),
        )
        policy_parser.add_argument("--expires-at", default=None)
    maintenance = subparsers.add_parser(
        "maintenance",
        help="Inspect and safely manage regenerable runtime evidence",
    )
    maintenance_actions = maintenance.add_subparsers(
        dest="maintenance_action",
        required=True,
    )
    artifacts = maintenance_actions.add_parser(
        "artifacts",
        help="Runtime artifact inventory and retention",
    )
    artifacts_actions = artifacts.add_subparsers(
        dest="artifacts_action",
        required=True,
    )
    artifacts_actions.add_parser("status", help="Show categorized artifact inventory")
    artifacts_cleanup = artifacts_actions.add_parser(
        "cleanup",
        help="Show or apply retention policy; dry-run by default",
    )
    artifacts_cleanup.add_argument(
        "--commit",
        action="store_true",
        help="Actually remove expired generated artifacts (never critical evidence)",
    )
    artifacts_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting (default behavior)",
    )
    subparsers.add_parser("version", help="Show application version")
    subparsers.add_parser("research", help="Run the audited local research pipeline")
    research_data = subparsers.add_parser(
        "research-data", help="Audit or import isolated historical research data"
    )
    research_data.add_argument("--root", type=Path, default=Path("var/research-data"))
    research_data.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    research_actions = research_data.add_subparsers(dest="research_data_action", required=True)
    research_actions.add_parser("status")
    research_actions.add_parser("providers")
    research_actions.add_parser("acquire")
    research_actions.add_parser("audit")
    research_actions.add_parser("certify")
    research_actions.add_parser("manifest")
    research_import = research_actions.add_parser("import")
    research_import.add_argument("path", type=Path)
    research_import.add_argument("--required-start", default=None)
    research_import.add_argument("--required-end", default=None)
    intelligence = subparsers.add_parser(
        "intelligence", help="Acquire and process evidence-backed SEC intelligence (SHADOW only)"
    )
    intelligence.add_argument(
        "--root", type=Path, default=Path("var/intelligence/sec-edgar")
    )
    intelligence_actions = intelligence.add_subparsers(
        dest="intelligence_action", required=True
    )
    intelligence_actions.add_parser("status", help="Show sanitized SEC/PIT/LLM status")
    for action in ("acquire", "backfill"):
        acquisition = intelligence_actions.add_parser(
            action, help=f"Run bounded SEC {action}"
        )
        acquisition.add_argument("--cik", type=int, required=True)
        acquisition.add_argument("--mapping", type=Path, default=None)
        acquisition.add_argument("--start", default=None)
        acquisition.add_argument("--end", default=None)
        acquisition.add_argument("--max-documents", type=int, default=20)
        acquisition.add_argument("--acquisition-id", default=None)
    process = intelligence_actions.add_parser(
        "process", help="Run real structured extraction and deterministic SHADOW transform"
    )
    process.add_argument("--max-documents", type=int, default=10)
    process.add_argument("--cutoff", default=None)
    process.add_argument("--historical-replay", action="store_true")
    inspect = intelligence_actions.add_parser("inspect", help="Inspect accepted ticker evidence")
    inspect.add_argument("--ticker", required=True)
    intelligence_actions.add_parser("audit", help="Verify immutable raw and evidence ledgers")
    identity = intelligence_actions.add_parser(
        "identity", help="Import or query canonical CIK/issuer identity evidence"
    )
    identity_actions = identity.add_subparsers(dest="identity_action", required=True)
    identity_actions.add_parser(
        "import-filings", help="Extract generic SEC filing identity evidence into the DB store"
    )
    broad_universe = subparsers.add_parser(
        "broad-universe",
        help="Register, sync and report the broad tradable US equity universe",
    )
    broad_universe.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    broad_universe.add_argument("--json", action="store_true")
    broad_universe_actions = broad_universe.add_subparsers(
        dest="broad_universe_action",
        required=True,
    )
    broad_universe_actions.add_parser("status", help="Show registration, coverage and quarantine")
    broad_universe_actions.add_parser("register", help="Register current-directory common stocks")
    broad_universe_sync = broad_universe_actions.add_parser(
        "sync", help="Download prices for the registered broad universe"
    )
    broad_universe_sync.add_argument(
        "--mode", choices=("incremental", "backfill"), default="incremental"
    )
    broad_universe_sync.add_argument("--start-date", default=None)
    broad_universe_sync.add_argument("--end-date", default=None)
    broad_universe_sync.add_argument("--sessions-back", type=int, default=10)
    broad_universe_sync.add_argument("--max-symbols", type=int, default=None)
    broad_universe_sync.add_argument("--chunk-size", type=int, default=None)
    broad_universe_funnel = broad_universe_actions.add_parser(
        "funnel", help="Report the per-layer tradable universe funnel"
    )
    broad_universe_funnel.add_argument("--as-of", default=None)
    forward_track = subparsers.add_parser(
        "forward-track",
        help="Inspect and append the immutable forward prediction/outcome ledger",
    )
    forward_track.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    forward_track_actions = forward_track.add_subparsers(
        dest="forward_track_action", required=True
    )
    forward_track_actions.add_parser("report", help="Summarize predictions and outcomes")
    append_outcome = forward_track_actions.add_parser(
        "append-outcome", help="Append an immutable outcome for one recommendation"
    )
    append_outcome.add_argument("recommendation_id")
    append_outcome.add_argument("--horizon", default="HORIZON")
    append_outcome.add_argument("--observed-at", required=True)
    append_outcome.add_argument("--observed-price", type=float, required=True)
    append_outcome.add_argument("--benchmark-price", type=float, required=True)
    append_outcome.add_argument("--realized-return", type=float, required=True)
    append_outcome.add_argument("--benchmark-return", type=float, required=True)
    append_outcome.add_argument("--relative-return", type=float, required=True)
    append_outcome.add_argument("--source", default="DB_RAW_OHLCV")
    append_outcome.add_argument("--return-1d", type=float, default=None)
    append_outcome.add_argument("--return-5d", type=float, default=None)
    append_outcome.add_argument("--return-10d", type=float, default=None)
    append_outcome.add_argument("--return-horizon", type=float, default=None)
    append_outcome.add_argument("--spy-relative", type=float, default=None)
    append_outcome.add_argument("--qqq-relative", type=float, default=None)
    append_outcome.add_argument("--max-adverse-excursion", type=float, default=None)
    append_outcome.add_argument("--max-favorable-excursion", type=float, default=None)
    round4_research = subparsers.add_parser(
        "round4-research",
        help="Run ROUND 4 broad cross-section, calibration and OOS research",
    )
    round4_research.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    round4_research.add_argument("--as-of", default=None)
    round4_research.add_argument("--history-start", default="2020-01-01")
    round4_research.add_argument("--benchmark", default="SPY")
    round4_research.add_argument("--horizon", type=int, default=21)
    round4_research.add_argument("--output", type=Path, default=Path("var/round4-research"))
    round7_research = subparsers.add_parser(
        "round7-research",
        help="ROUND 7 historical PIT certification and gated research rerun",
    )
    round7_research.add_argument("--root", type=Path, default=Path("var/research-data"))
    round7_actions = round7_research.add_subparsers(
        dest="round7_action", required=True
    )
    round7_actions.add_parser("status", help="Show historical PIT certification status")
    round7_certify = round7_actions.add_parser(
        "certify", help="Certify the latest imported research dataset"
    )
    round7_certify.add_argument("--required-start", default=None)
    round7_certify.add_argument("--required-end", default=None)
    round7_certify.add_argument("--claim-delisting-history", action="store_true")
    round7_certify.add_argument("--claim-delisting-returns", action="store_true")
    round7_certify.add_argument("--claim-historical-membership", action="store_true")
    round7_rerun = round7_actions.add_parser(
        "rerun", help="Run the gated historical research rerun (certified only)"
    )
    round7_rerun.add_argument("--benchmark", default="SPY")
    round7_rerun.add_argument("--horizon", type=int, default=21)
    round8_research = subparsers.add_parser(
        "round8-research",
        help="ROUND 8 Alpha Engine 2.0 champion/challenger research",
    )
    round8_actions = round8_research.add_subparsers(dest="round8_action", required=True)
    round8_actions.add_parser("status", help="Show champion/challenger research status")
    round8_actions.add_parser("shadow-report", help="Show the shadow production ledger")
    shadow_outcome = round8_actions.add_parser(
        "shadow-append-outcome", help="Append a real forward outcome for a shadow prediction"
    )
    shadow_outcome.add_argument("shadow_id")
    shadow_outcome.add_argument("--observed-at", required=True)
    shadow_outcome.add_argument("--realized-return", type=float, required=True)
    shadow_outcome.add_argument("--source", default="DB_RAW_OHLCV")
    shadow_outcome.add_argument("--horizon", default="HORIZON")
    register_experiment = round8_actions.add_parser(
        "register-experiment", help="Register a research experiment (including rejected ones)"
    )
    register_experiment.add_argument("experiment_id")
    register_experiment.add_argument("--strategy-id", required=True)
    register_experiment.add_argument("--strategy-version", required=True)
    register_experiment.add_argument("--hypothesis", required=True)
    register_experiment.add_argument("--factors", required=True)
    register_experiment.add_argument("--parameters", required=True)
    register_experiment.add_argument("--universe-version", required=True)
    register_experiment.add_argument("--horizon", type=int, required=True)
    register_experiment.add_argument("--benchmark", default="SPY")
    register_experiment.add_argument("--cost-model-version", required=True)
    register_experiment.add_argument("--train-start", required=True)
    register_experiment.add_argument("--train-end", required=True)
    register_experiment.add_argument("--validation-start", required=True)
    register_experiment.add_argument("--validation-end", required=True)
    register_experiment.add_argument("--oos-start", required=True)
    register_experiment.add_argument("--oos-end", required=True)
    register_experiment.add_argument("--results", required=True)
    register_experiment.add_argument(
        "--status",
        choices=("PROMOTED", "REJECTED", "RESEARCH_ONLY", "NOT_CERTIFIABLE"),
        default="RESEARCH_ONLY",
    )
    register_experiment.add_argument("--rejection-reason", default="")
    promotion_evaluate = round8_actions.add_parser(
        "promotion-evaluate", help="Evaluate a challenger against the fixed promotion gate"
    )
    promotion_evaluate.add_argument("challenger_id")
    promotion_evaluate.add_argument("--metrics", required=True)
    round9_research = subparsers.add_parser(
        "round9-research",
        help="ROUND 9 LLM Quant Modernization (Shadow -> Advisory)",
    )
    round9_actions = round9_research.add_subparsers(dest="round9_action", required=True)
    advisory_snapshot = round9_actions.add_parser(
        "advisory-snapshot", help="Assemble a deterministic advisory snapshot"
    )
    advisory_snapshot.add_argument("--model", default="advisory-v1")
    advisory_snapshot.add_argument("--pit-documents", type=int, default=0)
    evaluate = round9_actions.add_parser(
        "evaluate", help="Evaluate an LLM against the fixed quality thresholds"
    )
    evaluate.add_argument("--metrics", required=True)
    shadow_research = round9_actions.add_parser(
        "shadow-research", help="Classical vs Classical+LLM shadow feature (strict OOS)"
    )
    shadow_research.add_argument("--metrics", required=True)
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
    execution.add_argument(
        "--override-provenance",
        default=None,
        help="Explicit user provenance required to record a fill against an "
        "expired or stale recommendation",
    )
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
    portfolio_init.add_argument("--portfolio-id", default="main")
    portfolio_init.add_argument("--cash", type=float, default=None)
    portfolio_init.add_argument("--currency", default="USD")
    portfolio_init.add_argument(
        "--position",
        action="append",
        default=None,
        help="TICKER=SHARES[:AVERAGE_COST]; repeat for each position",
    )
    portfolio_import = subparsers.add_parser("portfolio-import")
    portfolio_import.add_argument("csv", type=Path)
    portfolio_import.add_argument("--portfolio-id", required=True)
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
    portfolio_update = subparsers.add_parser("portfolio-update")
    portfolio_update.add_argument("--portfolio-id", default="main")
    portfolio_update.add_argument("--as-of", required=True)
    portfolio_update.add_argument("--cash", type=float, default=None)
    portfolio_update.add_argument(
        "--position",
        action="append",
        default=None,
        help="TICKER=SHARES[:AVERAGE_COST]; repeat for each current position",
    )
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
        if command == "probability-assessment":
            return _probability_assessment_command(args)
        if command == "llm":
            return _llm_command(args)
        if command == "operational-policy":
            return _operational_policy_command(args)
        if command == "maintenance":
            return _maintenance_command(args)
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
        if command == "intelligence":
            return intelligence_command(args, load_config(args.config))
        if command == "broad-universe":
            return broad_universe_command(args)
        if command == "forward-track":
            return forward_track_command(args)
        if command == "round4-research":
            return _round4_research_command(args)
        if command == "round7-research":
            return round7_research_command(args)
        if command == "round8-research":
            return round8_research_command(args)
        if command == "round9-research":
            return round9_research_command(args)
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
            "portfolio-update",
        }:
            return _portfolio_command(args)
        if command == "refresh":
            return run_daily(
                args.config,
                refresh=True,
                locale=args.locale,
            )
        if command in {"data", "factors", "probability", "risk", "decisions"}:
            return _render_persisted_section(args.config, command, args.run_id)
        return run_daily(
            args.config,
            refresh=not args.no_refresh,
            locale=args.locale,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        logger.exception("Command failed")
        console.print(f"ERROR: {type(error).__name__}: {error}")
        return 2
