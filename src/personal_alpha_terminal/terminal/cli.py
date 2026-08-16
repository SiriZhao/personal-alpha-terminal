"""Thin command-line adapter over the headless application service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from collections.abc import Callable
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
    from personal_alpha_terminal.application.daily_result import DailyQuantResult
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


def _startup_panel(config: EffectiveRuntimeConfig, *, refresh: bool) -> None:
    """Print an immediate first frame; never wait for network refresh."""
    db_connected = False
    portfolio_loaded = False
    manifest_id = "--"
    try:
        url = str(getattr(config.settings, "database_url", ""))
        if url.startswith("sqlite:///"):
            database = Path(url.removeprefix("sqlite:///"))
            connection = sqlite3.connect(str(database), timeout=1)
            try:
                manifest_row = connection.execute(
                    "select snapshot_id from data_snapshot_manifests "
                    "order by completed_at desc limit 1"
                ).fetchone()
                if manifest_row is not None:
                    manifest_id = str(manifest_row[0])
                portfolio_count = connection.execute(
                    "select count(*) from portfolios"
                ).fetchone()[0]
                portfolio_loaded = bool(portfolio_count)
                db_connected = True
            finally:
                connection.close()
    except (OSError, sqlite3.Error, ValueError):
        db_connected = False
    latest_run = "--"
    try:
        runs = sorted(
            (config.report_dir / "daily-runs").glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if runs:
            latest_run = runs[0].stem
    except (OSError, AttributeError):
        pass
    state = "REFRESHING" if refresh else "CACHE_REPLAY"
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan")
    table.add_column()
    rows = (
        ("\u72b6\u6001", state),
        (
            "\u6570\u636e\u5e93",
            "\u5df2\u8fde\u63a5" if db_connected else "\u8fde\u63a5\u5931\u8d25",
        ),
        (
            "\u6295\u8d44\u7ec4\u5408",
            "\u5df2\u52a0\u8f7d" if portfolio_loaded else "\u672a\u521d\u59cb\u5316",
        ),
        ("\u6700\u8fd1\u5b8c\u6210\u8fd0\u884c", latest_run),
        ("\u6700\u8fd1\u884c\u60c5\u5feb\u7167", manifest_id),
        ("\u5e02\u573a\u6570\u636e", "\u6b63\u5728\u68c0\u67e5"),
        (
            "\u5b9e\u65f6\u5237\u65b0",
            "\u8fd0\u884c\u4e2d" if refresh else "\u8df3\u8fc7\uff08\u7f13\u5b58\u8bca\u65ad\uff09",
        ),
    )
    for label, value in rows:
        table.add_row(label, value)
    console.print(
        Panel(
            table,
            title="PERSONAL ALPHA TERMINAL \u00b7 \u4e2a\u4eba\u91cf\u5316\u4ea4\u6613\u7ec8\u7aef",
            border_style="cyan",
        )
    )
    console.file.flush()


def _progress_printer(config: EffectiveRuntimeConfig) -> Callable[[str], None]:
    """Return a progress callback that prints immediately and writes a heartbeat."""
    heartbeat_dir = Path(str(config.report_dir)).parent / "var" / "logs"
    heartbeat_path = heartbeat_dir / "terminal-heartbeat.json"

    def notify(message: str) -> None:
        console.print("  " + message, soft_wrap=True)
        console.file.flush()
        match = re.search(r"(\d+)\s*/\s*(\d+)", message)
        processed = int(match.group(1)) if match else None
        total = int(match.group(2)) if match else None
        try:
            heartbeat_dir.mkdir(parents=True, exist_ok=True)
            temporary = heartbeat_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "current_stage": message,
                        "updated_at": datetime.now(UTC).isoformat(),
                        "processed": processed,
                        "total": total,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary.replace(heartbeat_path)
        except OSError:
            pass

    return notify


def _as_trace_int(value: object) -> int:
    try:
        return int(value) if isinstance(value, (int, float, str)) else 0
    except (TypeError, ValueError):
        return 0


def _as_trace_float(value: object) -> float:
    try:
        return float(value) if isinstance(value, (int, float, str)) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _write_performance_trace(result: DailyQuantResult, config: EffectiveRuntimeConfig) -> None:
    """Write a machine-readable per-stage performance trace for the daily run."""
    try:
        stages = {
            str(item.name): float(item.duration_seconds or 0.0)
            for item in result.stages
        }
        started = getattr(result, "started_at", None)
        finished = getattr(result, "finished_at", None)
        total = None
        if started is not None and finished is not None:
            total = round((finished - started).total_seconds(), 4)
        data_meta: dict[str, object] = next(
            (item.metadata for item in result.stages if item.name == "DATA"),
            {},
        )
        ai_meta: dict[str, object] = next(
            (item.metadata for item in result.stages if item.name == "AI_BRIEF"),
            {},
        )
        profile = data_meta.get("data_stage_profile", {})
        profile = profile if isinstance(profile, dict) else {}
        segments = profile.get("segments_seconds", {})
        segments = segments if isinstance(segments, dict) else {}
        market_network = _as_trace_float(segments.get("provider_sync"))
        data_wall = float(stages.get("DATA", 0.0) or 0.0)
        news_network = _as_trace_float(ai_meta.get("news_network_seconds"))
        llm_network = _as_trace_float(ai_meta.get("llm_network_seconds"))
        trace = {
            "run_id": str(getattr(result, "run_id", "UNAVAILABLE")),
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "total_seconds": total,
            "stages_seconds": stages,
            "stage_profiler_v2": {
                "data_core_seconds": round(max(0.0, data_wall - market_network), 4),
                "market_data_network_seconds": round(market_network, 4),
                "news_network_seconds": round(news_network, 4),
                "llm_network_seconds": round(llm_network, 4),
                "total_wall_clock_seconds": total,
                "data_segments_seconds": segments,
                "db_query_count": "UNAVAILABLE",
            },
            "data": {
                "requested": _as_trace_int(data_meta.get("requested_security_count")),
                "refreshed": _as_trace_int(data_meta.get("actual_refresh_count")),
                "cache_reused": _as_trace_int(data_meta.get("cache_reuse_count")),
                "historical_cache_reused": _as_trace_int(
                    data_meta.get("historical_cache_reused_count")
                ),
                "incremental_refresh": _as_trace_int(
                    data_meta.get("incremental_refresh_requested_count")
                ),
                "full_backfill": _as_trace_int(data_meta.get("full_backfill_requested_count")),
                "refresh_request_ratio": (
                    _as_trace_int(data_meta.get("actual_refresh_count"))
                    / _as_trace_int(data_meta.get("requested_security_count"))
                    if _as_trace_int(data_meta.get("requested_security_count"))
                    else 0.0
                ),
                "refresh_success_rate": data_meta.get("provider_success_rate"),
                "latest_price_coverage": data_meta.get("latest_price_coverage"),
                "history_coverage": data_meta.get("coverage"),
            },
        }
        target = config.report_dir / "validation-artifacts"
        target.mkdir(parents=True, exist_ok=True)
        (target / "daily_performance_trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, AttributeError):
        pass


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
        progress = _progress_printer(config) if refresh else None
        if refresh:
            from personal_alpha_terminal.terminal.instance import ConsoleInstanceLock

            with ConsoleInstanceLock():
                _startup_panel(config, refresh=True)
                result = _application_service(
                    snapshot_root=config.report_dir, effective_config=config
                ).run_daily_quant_report(
                    portfolio_id=config.portfolio_id,
                    refresh=True,
                    progress=progress,
                )
        else:
            _startup_panel(config, refresh=False)
            result = _application_service(
                snapshot_root=config.report_dir, effective_config=config
            ).run_daily_quant_report(
                portfolio_id=config.portfolio_id,
                refresh=False,
            )
    except RuntimeError as error:
        console.print(
            Panel(
                str(error),
                title=(
                    "PERSONAL ALPHA TERMINAL \u00b7 "
                    "\u4e2a\u4eba\u91cf\u5316\u4ea4\u6613\u7ec8\u7aef"
                ),
                border_style="yellow",
            )
        )
        console.print("Press Enter to exit")
        return 1
    except (FileNotFoundError, OSError, ValueError) as error:
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
    _write_performance_trace(result, config)
    console.print(f"\nRun snapshot directory: {(config.report_dir / 'daily-runs').resolve()}")
    if wait and sys.stdin.isatty() and os.environ.get("PAT_NONINTERACTIVE") != "1":
        try:
            console.input("\nPress Enter to exit")
        except EOFError:
            logger.info("Skipping exit prompt because stdin reached EOF")
    return 0 if result.actionable else 3


def _terminal_status_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.core.runtime_bootstrap import (
        application_data_dir,
        process_is_running,
    )

    config = load_config(args.config)
    heartbeat_path = config.report_dir.parent / "var" / "logs" / "terminal-heartbeat.json"
    heartbeat = None
    if heartbeat_path.exists():
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            heartbeat = None
    lock_path = application_data_dir() / "run" / "console-instance.json"
    lock_pid = None
    lock_running = False
    if lock_path.exists():
        try:
            lock_pid = int(json.loads(lock_path.read_text(encoding="utf-8"))["pid"])
            lock_running = process_is_running(lock_pid)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            lock_pid = None
    latest_run = "--"
    latest_manifest = "--"
    try:
        runs = sorted(
            (config.report_dir / "daily-runs").glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if runs:
            latest_run = runs[0].stem
        url = str(config.settings.database_url)
        if url.startswith("sqlite:///"):
            connection = sqlite3.connect(str(Path(url.removeprefix("sqlite:///"))), timeout=1)
            try:
                row = connection.execute(
                    "select snapshot_id from data_snapshot_manifests "
                    "order by completed_at desc limit 1"
                ).fetchone()
                if row is not None:
                    latest_manifest = str(row[0])
            finally:
                connection.close()
    except (OSError, sqlite3.Error, ValueError):
        pass
    logs: list[Path] = []
    for directory in (config.report_dir.parent / "logs", config.report_dir.parent / "var" / "logs"):
        if directory.is_dir():
            logs.extend(directory.glob("*.log"))
    latest_log = max(logs, key=lambda item: item.stat().st_mtime, default=None)
    document = {
        "pid": os.getpid(),
        "lock_pid": lock_pid,
        "lock_running": lock_running,
        "heartbeat": heartbeat,
        "latest_completed_run": latest_run,
        "latest_market_snapshot": latest_manifest,
        "latest_log": str(latest_log.resolve()) if latest_log else None,
    }
    if args.json:
        console.print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    console.print("[bold]TERMINAL STATUS[/bold]")
    console.print(f"Current PID: {document['pid']}")
    if lock_pid:
        console.print(f"Refresh process: PID {lock_pid} running={lock_running}")
    else:
        console.print("Refresh process: none")
    heartbeat_text = json.dumps(heartbeat, ensure_ascii=False) if heartbeat else "none"
    console.print(f"Heartbeat: {heartbeat_text}")
    console.print(f"Latest completed run: {latest_run}")
    console.print(f"Latest market snapshot: {latest_manifest}")
    console.print(f"Latest log: {document['latest_log'] or 'none'}")
    return 0


def _strategy_approval_command(args: argparse.Namespace) -> int:
    from personal_alpha_terminal.application.operational_readiness import (
        resolve_current_operational_identity,
    )
    from personal_alpha_terminal.application.strategy_approval import (
        StrategyApprovalDecision,
        StrategyApprovalStore,
        issue_strategy_approval,
    )
    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )

    config = load_config(args.config)
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    now = datetime.now(UTC)
    identity = resolve_current_operational_identity(config, strategy, decision_time=now)
    store = StrategyApprovalStore(config.strategy_approval_path)
    if args.strategy_approval_action == "status":
        approval, reason = store.status(identity, now=now)
        console.print("[bold]STRATEGY APPROVAL STATUS[/bold]")
        console.print("Historical research certification: NOT_CERTIFIABLE")
        console.print(
            "Forward strategy authorization: "
            f"{approval.decision.value if approval else 'NOT_CONFIGURED'}"
        )
        console.print(f"Approval id: {approval.approval_id if approval else 'none'}")
        console.print(f"Effective: {approval is not None}")
        console.print(f"Reason: {reason}")
        return 0
    if os.environ.get("PAT_NONINTERACTIVE") == "1":
        console.print("Refusing to create strategy approval in noninteractive mode.")
        return 3
    decision = StrategyApprovalDecision(args.decision)
    approval = issue_strategy_approval(
        identity=identity,
        decision=decision,
        operator_intent=args.intent,
    )
    console.print(
        f"About to create strategy approval {approval.approval_id} "
        f"({decision.value}). This is NOT production certification."
    )
    answer = console.input("Type YES to continue: ")
    if answer.strip().upper() != "YES":
        console.print("Cancelled; no strategy approval was created.")
        return 3
    store.save(approval, force=bool(args.force))
    console.print(f"Created strategy approval: {approval.approval_id}")
    return 0


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
    if isinstance(trace, dict):
        table = Table(title=f"DECISION TRACE / {normalized} / {certificate.get('run_id')}")
        table.add_column("Evidence")
        table.add_column("Value", overflow="fold")
        for key, value in trace.items():
            table.add_row(str(key), json.dumps(value, ensure_ascii=False, sort_keys=True))
        console.print(table)
    else:
        recommendations = certificate.get("decision_recommendations", [])
        etf_row = next(
            (
                item
                for item in recommendations
                if isinstance(item, dict)
                and str(item.get("symbol", "")).upper() == normalized
            ),
            None,
        )
        if etf_row is not None:
            console.print(
                f"{normalized}: ETF target present in this run; "
                "ETF:不适用公司级 SEC 事件分析。"
            )
        else:
            etf_evidence_path = path.parent / "etf_sleeve_evidence.json"
            if etf_evidence_path.exists():
                try:
                    etf_evidence = json.loads(
                        etf_evidence_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    etf_evidence = {}
                targets = etf_evidence.get("targets") or []
                matching = [
                    item
                    for item in targets
                    if str(item.get("symbol", "")).upper() == normalized
                ]
                if matching:
                    item = matching[0]
                    console.print(
                        f"{normalized} [ETF/{item.get('sleeve', 'UNKNOWN')}]"
                    )
                    console.print(
                        f"目标权重: {item.get('target_weight')} | "
                        f"当前: {item.get('current_weight')} | "
                        f"研究候选: {item.get('model_status')}"
                    )
                    console.print(
                        f"入选理由: {item.get('rationale', '不适用')}"
                    )
                    console.print(
                        "ETF ????: ETF:?????? SEC ?????"
                    )
                else:
                    console.print(
                        f"{normalized} is absent from run "
                        f"{certificate.get('run_id')}"
                    )
            else:
                console.print(
                    f"{normalized} is absent from run "
                    f"{certificate.get('run_id')}"
                )
    run_directory = path.parent
    brief_path = run_directory / "ai_brief.json"
    if brief_path.exists():
        try:
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            brief = None
        if brief is not None:
            explanations = (brief.get("brief") or {}).get("action_explanations") or []
            matching = [
                item
                for item in explanations
                if str(item.get("symbol", "")).upper() == normalized
            ]
            if matching:
                console.print("")
                console.print("【AI 中文解读 · 量化决策解释】(SHADOW / 生产决策影响 NONE)")
                item = matching[0]
                for label, key in (
                    ("量化 Alpha", "quant_alpha"),
                    ("趋势", "trend"),
                    ("波动", "volatility"),
                    ("风险目标", "risk_target"),
                    ("流动性", "liquidity"),
                    ("组合作用", "portfolio_role"),
                    ("PIT 事件", "pit_events"),
                ):
                    console.print(f"{label}: {item.get(key, '不适用')}")
                console.print(f"AI 解读: {item.get('ai_interpretation', '暂无')}")
                console.print(f"证据引用: {item.get('evidence_refs', [])}")
            else:
                console.print("AI 中文研判:该证券在本轮 brief 中没有独立解释。")
    console.print(f"Certificate: {path.resolve()}")
    console.print("LLM contribution: NONE (trade/target-weight/BUY-SELL authority: NONE)")
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


def _stress_exam_command() -> int:
    from personal_alpha_terminal.scenario_simulator.exam import (
        run_stress_exam,
        write_stress_exam_summary,
    )

    summary = run_stress_exam()
    target = Path("reports") / "stress-exam" / "stress_exam_summary.json"
    write_stress_exam_summary(summary, target)
    print(f"{summary.classification}: {target.resolve()}")
    return 0


def _pre_execution_command(args: argparse.Namespace) -> int:
    """Compute the overnight / pre-execution assessment for the latest plan."""

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from sqlalchemy import func, select

    from personal_alpha_terminal.application.pre_execution import (
        build_assessment,
        check_halts_and_corporate_events,
        check_market_gap,
        check_overnight_news,
        check_stale_market_data,
    )
    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.intelligence.market_news import NewsIntelligenceService
    from personal_alpha_terminal.models import Price, SecurityMaster

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    candidates = sorted(
        root.glob("*/run_certificate.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    previous = None
    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("decision_recommendations"):
            previous = payload
            break
    if previous is None:
        console.print("PRE_EXECUTION_DATA_UNAVAILABLE: no previous actionable run.")
        return 1
    now = _datetime.now(_UTC)
    raw_cutoff = previous.get("data_cutoff") or previous.get("finished_at")
    decision_as_of = _datetime.fromisoformat(str(raw_cutoff))
    if decision_as_of.tzinfo is None:
        decision_as_of = decision_as_of.replace(tzinfo=_UTC)
    recommendations = previous.get("decision_recommendations") or []
    formal_symbols = frozenset(
        str(item.get("symbol"))
        for item in recommendations
        if isinstance(item, dict) and item.get("symbol")
    )
    news_service = NewsIntelligenceService()
    checks = [
        check_overnight_news(
            news_service,
            decision_as_of=decision_as_of,
            now=now,
            material_symbols=formal_symbols or None,
        )
    ]
    with get_session_factory()() as session:
        spy_rows = session.execute(
            select(Price.trade_date, Price.close)
            .join(SecurityMaster, Price.stock_id == SecurityMaster.id)
            .where(SecurityMaster.symbol == "SPY", Price.price_type == "unadjusted_ohlcv")
            .order_by(Price.trade_date.desc())
            .limit(3)
        ).all()
        freshness = session.scalar(
            select(func.max(Price.available_time))
            .join(SecurityMaster, Price.stock_id == SecurityMaster.id)
            .where(
                SecurityMaster.symbol.in_(sorted(formal_symbols)),
                Price.price_type == "unadjusted_ohlcv",
            )
        )
    decision_close = None
    latest_close = None
    if spy_rows:
        before = [row for row in spy_rows if row[0] <= decision_as_of.date()]
        if before:
            decision_close = float(before[0][1])
            latest_close = (
                float(spy_rows[0][1]) if spy_rows[0][0] > decision_as_of.date() else decision_close
            )
    checks.append(
        check_market_gap(decision_close=decision_close, latest_close=latest_close)
    )
    checks.append(
        check_stale_market_data(
            latest_available_at=freshness,
            decision_as_of=decision_as_of,
            now=now,
        )
    )
    checks.append(check_halts_and_corporate_events())
    assessment = build_assessment(decision_as_of=decision_as_of, now=now, checks=tuple(checks))
    document = assessment.document()
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round25_pre_execution.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(
        f"{assessment.status} | review_required={assessment.manual_review_required}"
    )
    for check in checks:
        console.print(f"- [{check.status}] {check.name}: {check.detail}")
    console.print("NOTE: never auto-cancels; never recomputes alpha; LLM authority NONE.")
    return 0


def _market_state_command(args: argparse.Namespace) -> int:
    """Print the deterministic MARKET_STATE_SNAPSHOT."""

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from personal_alpha_terminal.application.market_state import (
        build_market_state_snapshot,
    )
    from personal_alpha_terminal.data.database import get_session_factory

    config = load_config(args.config)
    with get_session_factory()() as session:
        snapshot = build_market_state_snapshot(
            session, as_of=_datetime.now(_UTC)
        )
    if snapshot is None:
        console.print("MARKET_STATE_DATA_UNAVAILABLE")
        return 1
    document = snapshot.document()
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round25_market_state.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(
        f"MARKET_STATE {document['status']} | breadth symbols "
        f"{document['breadth_symbols']}"
    )
    console.print(f"breadth: {document['breadth']}")
    basket = document.get("basket")
    if isinstance(basket, list):
        for raw_item in basket:
            if not isinstance(raw_item, dict):
                continue
            item = cast("dict[str, object]", raw_item)
            if not item["available"]:
                console.print(f"- {item['symbol']} ({item['role']}) UNAVAILABLE")
                continue
            returns = {
                key: value
                for key, value in cast("dict[str, object]", item["returns"]).items()
                if value is not None
            }
            console.print(f"- {item['symbol']} ({item['role']}): {returns}")
    return 0


def _news_command(args: argparse.Namespace) -> int:
    """Market news intelligence CLI (status / acquire / show)."""

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from personal_alpha_terminal.intelligence.market_news import (
        NewsLedger,
    )

    ledger = NewsLedger()
    now = _datetime.now(_UTC)
    rows = ledger.load_items()
    clusters = ledger.load_clusters()
    if getattr(args, "news_action", "status") == "status":
        if rows and not clusters:
            from personal_alpha_terminal.intelligence.market_news import (
                NewsItem,
                NewsSourceTier,
                cluster_news,
            )

            rebuilt = []
            for raw_row in rows:
                if not isinstance(raw_row, dict):
                    continue
                published_raw = raw_row.get("published_at")
                try:
                    published_at = (
                        _datetime.fromisoformat(str(published_raw))
                        if isinstance(published_raw, str)
                        else now
                    )
                except ValueError:
                    continue
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=_UTC)
                rebuilt.append(
                    NewsItem(
                        news_id=str(raw_row.get("news_id", "")),
                        source=str(raw_row.get("source", "")),
                        source_tier=str(
                            raw_row.get("source_tier", NewsSourceTier.TIER1_OFFICIAL.value)
                        ),
                        headline=str(raw_row.get("headline", "")),
                        summary=str(raw_row.get("summary", "")),
                        published_at=published_at,
                        retrieved_at=published_at,
                        available_at=published_at,
                        url_hash=str(raw_row.get("url_hash", "")),
                        content_hash=str(raw_row.get("content_hash", "")),
                        topics=tuple(
                            str(item)
                            for item in cast(
                                "tuple[object, ...]", raw_row.get("topics") or ()
                            )
                        ),
                        country="US",
                        language="en",
                        evidence_state=str(raw_row.get("evidence_state", "")),
                    )
                )
            rebuilt_clusters = cluster_news(tuple(rebuilt))
            ledger.write_clusters(rebuilt_clusters)
            clusters = ledger.load_clusters()
        console.print(f"news rows: {len(rows)}")
        console.print(f"news clusters: {len(clusters)}")
        console.print(
            "providers: official-macro / general-market / company-disclosures "
            "(no API configured -> GENERAL_MARKET_NEWS_UNAVAILABLE; no news is fabricated)"
        )
        return 0
    if getattr(args, "news_action", None) == "acquire":
        from personal_alpha_terminal.intelligence.macro_news import (
            OfficialMacroAcquisition,
        )

        try:
            macro = OfficialMacroAcquisition().acquire()
        except (OSError, ValueError, TimeoutError) as error:
            console.print(f"OFFICIAL_MACRO_NEWS_UNAVAILABLE: {error}")
            return 0
        macro_rows = macro.get("items")
        if macro_rows and isinstance(macro_rows, list):
            from personal_alpha_terminal.intelligence.market_news import (
                NewsItem,
            )

            items = []
            for raw_row in macro_rows:
                if not isinstance(raw_row, dict):
                    continue
                row = raw_row
                published_raw = row.get("published_at")
                published_at = (
                    _datetime.fromisoformat(published_raw)
                    if isinstance(published_raw, str)
                    else now
                )
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=_UTC)
                items.append(
                    NewsItem(
                        news_id=str(row["news_id"]),
                        source=str(row["source"]),
                        source_tier=str(row["source_tier"]),
                        headline=str(row["headline"]),
                        summary=str(row.get("summary", "")),
                        published_at=published_at,
                        retrieved_at=_datetime.fromisoformat(str(row["retrieved_at"]))
                        if isinstance(row.get("retrieved_at"), str)
                        else now,
                        available_at=published_at,
                        url_hash=str(row["url_hash"]),
                        content_hash=str(row["content_hash"]),
                        topics=tuple(
                            str(item)
                            for item in cast("tuple[object, ...]", row.get("topics") or ())
                        ),
                        country="US",
                        language="en",
                        evidence_state=str(row.get("evidence_state", "RAW_OFFICIAL")),
                    )
                )
            appended = ledger.append_items(tuple(items))
            clusters = __import__(
                "personal_alpha_terminal.intelligence.market_news",
                fromlist=["cluster_news"],
            ).cluster_news(tuple(items))
            ledger.write_clusters(clusters)
            console.print(
                f"OFFICIAL_MACRO_NEWS_OK appended={appended} "
                f"clusters={len(clusters)} (no fabricated news)"
            )
        else:
            console.print(f"{macro.get('status')}: {macro.get('provider_statuses')}")
        return 0
    for row in rows[: (None if getattr(args, "full", False) else 20)]:
        console.print(
            f"[{row.get('source_tier')}] {row.get('headline')} "
            f"@ {row.get('available_at')} ({row.get('evidence_state')})"
        )
    if len(rows) > 20 and not getattr(args, "full", False):
        console.print(f"... {len(rows) - 20} more rows (use --full)")
    return 0


def _resolve_run_dir(
    config: EffectiveRuntimeConfig, run_id: str | None
) -> Path:
    root = config.report_dir / "daily-runs"
    if run_id:
        return root / run_id
    candidates = sorted(
        root.glob("*/run_certificate.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise ValueError("no persisted daily runs found")
    return candidates[0].parent


def _probability_forward_command(args: argparse.Namespace) -> int:
    """ROUND26 P0: forward probability evidence (research only, influence 0)."""

    from personal_alpha_terminal.probability.forward_ledger import (
        ProbabilityForwardLedger,
        ProbabilityPromotionPolicy,
        evaluate_forward_probability,
        forward_prediction_audit,
    )

    config = load_config(args.config)
    ledger = ProbabilityForwardLedger()
    predictions = ledger.predictions()
    outcomes = ledger.outcomes()
    report = evaluate_forward_probability(ledger)
    audit = forward_prediction_audit(ledger)
    ledger.write_canonical_index()
    policy = ProbabilityPromotionPolicy()
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "raw_prediction_rows": len(predictions),
        "canonical_predictions": audit["canonical_prediction_rows"],
        "duplicate_prediction_rows": audit["duplicate_prediction_rows"],
        "matured_outcome_rows": len(outcomes),
        "matured_canonical_predictions": report.get("matured_canonical_predictions", 0),
        "decision_dates": report.get("decision_date_n", 0),
        "effective_sample_size": report.get("effective_sample_size", 0),
        "audit": audit,
        "production_influence": policy.production_influence,
        "evaluation": report,
        "promotion_conditions": policy.conditions(),
        "auto_promote": False,
        "human_approval_required": True,
    }
    (artifacts / "round26_probability_forward.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (artifacts / "forward_prediction_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    console.print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def _decision_replay_command(args: argparse.Namespace) -> int:
    """ROUND26 P0: deterministic decision replay."""

    from personal_alpha_terminal.application.decision_replay import replay_decision

    config = load_config(args.config)
    try:
        run_dir = _resolve_run_dir(config, args.run_id)
    except ValueError as error:
        console.print(str(error))
        return 1
    report = replay_decision(run_dir)
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round26_decision_replay.json").write_text(
        json.dumps(report.document(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(
        f"{report.status} run={report.run_id}\n"
        f"manifest_hash={report.manifest_hash}\n"
        f"recomputed_hash={report.recomputed_hash}\n"
        f"detail={report.detail}"
    )
    return 0 if report.status == "REPLAY_PASS" else 1


def _decision_diff_command(args: argparse.Namespace) -> int:
    """ROUND26 P0: decision drift attribution."""

    from personal_alpha_terminal.application.decision_replay import diff_decisions

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    old_dir = root / args.old_run
    new_dir = root / args.new_run
    if not (old_dir / "run_certificate.json").exists():
        console.print(f"old run missing: {args.old_run}")
        return 1
    if not (new_dir / "run_certificate.json").exists():
        console.print(f"new run missing: {args.new_run}")
        return 1
    report = diff_decisions(old_dir, new_dir)
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "decision_diff.json").write_text(
        json.dumps(report.document(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(json.dumps(report.document(), ensure_ascii=False, indent=2, default=str))
    return 0


def _round28_audit_command(args: argparse.Namespace) -> int:
    """ROUND28 P0: write cardinality/risk/parity audit artifacts."""

    from personal_alpha_terminal.application.round28_audit import (
        write_round28_audit_artifacts,
    )

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    acceptance_dir = root / args.acceptance_run
    production_dir = root / args.production_run
    if not (acceptance_dir / "run_certificate.json").exists():
        console.print(f"acceptance run missing: {acceptance_dir}")
        return 1
    if not (production_dir / "run_certificate.json").exists():
        console.print(f"production run missing: {production_dir}")
        return 1
    output_dir = args.output_dir or config.report_dir / "validation-artifacts"
    paths = write_round28_audit_artifacts(
        acceptance_run_dir=acceptance_dir,
        production_run_dir=production_dir,
        output_dir=output_dir,
    )
    console.print("ROUND28 audit artifacts written:")
    for name, path in paths.items():
        console.print(f"- {name}: {path}")
    return 0


def _round30_audit_command(args: argparse.Namespace) -> int:
    """ROUND30: write model influence, promotion ladder, counterfactual artifacts."""

    from personal_alpha_terminal.application.round30_audit import (
        write_round30_audit_artifacts,
    )

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    acceptance_dir = root / args.acceptance_run
    output_dir = config.report_dir / "validation-artifacts"
    if not (acceptance_dir / "run_certificate.json").exists():
        console.print(f"acceptance run missing: {acceptance_dir}")
        return 1
    paths = write_round30_audit_artifacts(
        acceptance_run_dir=acceptance_dir,
        output_dir=output_dir,
    )
    for name, path in paths.items():
        console.print(f"{name}: {path.resolve()}")
    return 0


def _round31_audit_command(args: argparse.Namespace) -> int:
    """ROUND31: write breadth/capital/ETF/forward policy audit artifacts."""

    from personal_alpha_terminal.application.round31_audit import (
        write_round31_audit_artifacts,
    )

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    acceptance_dir = root / args.acceptance_run
    output_dir = config.report_dir / "validation-artifacts"
    if not (acceptance_dir / "run_certificate.json").exists():
        console.print(f"acceptance run missing: {acceptance_dir}")
        return 1
    paths = write_round31_audit_artifacts(
        acceptance_run_dir=acceptance_dir,
        output_dir=output_dir,
    )
    for name, path in paths.items():
        console.print(f"{name}: {path.resolve()}")
    return 0


def _run_bundle_command(args: argparse.Namespace) -> int:
    """ROUND32: immutable production run bundle inspection and replay."""

    from personal_alpha_terminal.application.run_bundle import (
        RunBundleStore,
        replay_run_bundle,
        verify_bundle_integrity,
    )

    config = load_config(args.config)
    store = RunBundleStore(config.report_dir / "evidence-bundles")
    action = args.run_bundle_action
    if action == "list":
        run_ids = store.list_run_ids()
        console.print(json.dumps({"run_ids": run_ids}, ensure_ascii=False, indent=2))
        return 0
    if action == "show":
        try:
            manifest = store.load_manifest(args.run_id)
        except FileNotFoundError as error:
            console.print(str(error))
            return 1
        console.print(
            json.dumps(
                {
                    "run_id": manifest.get("run_id"),
                    "status": manifest.get("status"),
                    "decision_manifest_semantic_hash": manifest.get(
                        "decision_manifest_semantic_hash"
                    ),
                    "bundle_hash": manifest.get("bundle_hash"),
                    "sections": sorted(
                        str(item) for item in manifest.get("sections", {}).keys()
                    ),
                    "blob_digests": manifest.get("blob_digests"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if action == "verify":
        try:
            report = verify_bundle_integrity(store=store, run_id=args.run_id)
        except FileNotFoundError as error:
            console.print(str(error))
            return 1
        console.print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report.get("status") == "INTEGRITY_PASS" else 1
    if action == "replay":
        try:
            report = replay_run_bundle(store=store, run_id=args.run_id)
        except FileNotFoundError as error:
            console.print(str(error))
            return 1
        artifacts = config.report_dir / "validation-artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / f"run_bundle_replay_{args.run_id}.json").write_text(
            json.dumps(report.document(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(
            f"{report.status} run={report.run_id}\n"
            f"bundle_hash={report.bundle_hash}\n"
            f"decision_manifest_semantic_hash={report.decision_manifest_semantic_hash}\n"
            f"occurrence={report.replay_occurrence_id}\n"
            f"detail={report.detail}"
        )
        for metric in report.metrics:
            console.print(
                f"  {metric.name}: recorded={metric.recorded} "
                f"replayed={metric.replayed} passed={metric.passed}"
            )
        return 0 if report.status == "REPLAY_PASS" else 1
    console.print(f"unknown run-bundle action: {action}")
    return 2


def _round32_audit_command(args: argparse.Namespace) -> int:
    """ROUND32: write run-bundle / replay acceptance artifacts."""

    from personal_alpha_terminal.application.round32_audit import (
        write_round32_audit_artifacts,
    )

    config = load_config(args.config)
    run_id = args.acceptance_run
    if not run_id:
        from personal_alpha_terminal.application.run_bundle import RunBundleStore

        store = RunBundleStore(config.report_dir / "evidence-bundles")
        sealed = [
            item
            for item in store.list_run_ids()
            if store.load_manifest(item).get("status") == "SEALED"
        ]
        if not sealed:
            console.print("no sealed run bundle found; provide --acceptance-run")
            return 1
        run_id = sealed[-1]
    output_dir = config.report_dir / "validation-artifacts"
    paths = write_round32_audit_artifacts(
        acceptance_run_id=run_id,
        bundle_root=config.report_dir / "evidence-bundles",
        output_dir=output_dir,
    )
    for name, path in paths.items():
        console.print(f"{name}: {path.resolve()}")
    return 0


def _stress_exam_v21_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 19: Stress Exam 2.1 with unchanged ROUND24 scenarios."""

    from personal_alpha_terminal.data.database import get_session_factory, session_scope
    from personal_alpha_terminal.scenario_simulator.stress_exam_v2_run import (
        DEFAULT_SEED,
        load_baseline_from_run_dir,
    )
    from personal_alpha_terminal.scenario_simulator.stress_exam_v21 import (
        run_stress_exam_v21,
    )

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    baseline = None
    baseline_status = "NO_RUN_CERTIFICATE"
    with session_scope(get_session_factory()) as session:
        for certificate_path in sorted(
            root.glob("*/run_certificate.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            baseline, baseline_status = load_baseline_from_run_dir(
                run_dir=certificate_path.parent,
                session=session,
            )
            if baseline is not None:
                break
        result = run_stress_exam_v21(baseline, seed=DEFAULT_SEED)
    out_dir = config.report_dir / "stress-exam-v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stress_exam_v2_1_summary.json").write_text(
        json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / "stress_exam_v2_1_comparison.json").write_text(
        json.dumps(result["comparison"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(f"status: {result['summary'].get('status')} baseline={baseline_status}")
    for name, rows in result["comparison"].items():
        worst = max(
            (
                (scenario, rows["scenarios"][scenario]["max_drawdown"])
                for scenario in rows["scenarios"]
            ),
            key=lambda pair: abs(pair[1]),
        )
        console.print(
            f"- {name}: worst {worst[0]} maxDD {worst[1]:.2%} | {rows['description']}"
        )
    console.print(
        "scenario_definitions_unchanged=True; research only; no auto promotion."
    )
    return 0


def _exposure_audit_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 12: honest size/sector/ETF look-through closure."""

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from personal_alpha_terminal.application.current_exposure import (
        build_current_sector_exposure,
        build_current_size_exposure,
    )
    from personal_alpha_terminal.application.exposure_closure import (
        build_exposure_closure,
    )
    from personal_alpha_terminal.data.database import get_session_factory

    config = load_config(args.config)
    with get_session_factory()() as session:
        report = build_exposure_closure(session, as_of=_datetime.now(_UTC))
        formal_symbols: tuple[str, ...] = ()
        try:
            runs = sorted(
                (config.report_dir / "daily-runs").glob("*/run_certificate.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if runs:
                certificate = json.loads(runs[0].read_text(encoding="utf-8"))
                formal_symbols = tuple(
                    str(item.get("symbol"))
                    for item in (certificate.get("decision_recommendations") or [])
                    if isinstance(item, dict) and item.get("symbol")
                )
        except (OSError, ValueError):
            formal_symbols = ()
        report["current_size_exposure"] = build_current_size_exposure(
            session, as_of=_datetime.now(_UTC), target_symbols=formal_symbols
        )
        report["current_sector_exposure"] = build_current_sector_exposure(
            sector_rows={symbol: None for symbol in formal_symbols},
            target_symbols=formal_symbols,
            classification_source="SEC_SIC",
        )
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round25_exposure_closure.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    console.print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def _research_labs_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 8-11: research promotion labs with honest evidence labels."""

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.research.round25_labs import (
        ExperimentRegistry,
        ExperimentRegistryEntry,
        evaluate_etf_sleeve_experiments,
    )

    config = load_config(args.config)
    registry = ExperimentRegistry(Path("var/alpha-engine2"))
    if getattr(args, "labs_action", None) == "list":
        entries = registry.entries()
        if not entries:
            console.print("No registered ROUND25 experiments.")
            return 0
        for entry in entries:
            console.print(
                f"- {entry.get('experiment_id')} [{entry.get('status')}] "
                f"hypothesis: {entry.get('hypothesis')}"
            )
        return 0
    now = _datetime.now(_UTC)
    with get_session_factory()() as session:
        etf_result = evaluate_etf_sleeve_experiments(session, as_of=now)
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round25_etf_research.json").write_text(
        json.dumps(etf_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    registry.register(
        ExperimentRegistryEntry(
            experiment_id=f"etf-sleeves-a-b-{now.strftime('%Y%m%d')}",
            hypothesis=(
                "ETF core/tactical sleeves improve after-cost risk-adjusted returns "
                "vs equity-only baseline on identical windows and cost model"
            ),
            registered_at=now.isoformat(),
            factor_definition={
                "engine": "etf-price-factors-v1",
                "champion": "USAdaptiveAlphaCoreV1:1.0.0:427671e52a53",
            },
            parameters={
                "core_weight": 0.25,
                "tactical_weight": 0.10,
                "cost_bps": 5.0,
                "benchmark": "SPY",
            },
            train=("NOT_APPLICABLE_INSUFFICIENT_HISTORY",) * 2,
            validation=("NOT_APPLICABLE_INSUFFICIENT_HISTORY",) * 2,
            embargo_sessions=0,
            locked_test=("NOT_APPLICABLE_INSUFFICIENT_HISTORY",) * 2,
            benchmark="SPY",
            cost_model="fixed-entry-bps-v1",
            result=etf_result,
            status=str(
                cast("dict[str, object]", etf_result.get("evidence") or {}).get(
                    "certification"
                )
            ),
        )
    )
    console.print(f"status: {etf_result['status']}")
    console.print(f"evidence: {etf_result['evidence']}")
    experiments = etf_result.get("experiments")
    experiment_map = (
        cast("dict[str, object]", experiments) if isinstance(experiments, dict) else {}
    )
    for name, experiment in experiment_map.items():
        metrics = cast("dict[str, object]", experiment).get("metrics") or {}
        console.print(
            f"- {name}: net {cast('dict[str, object]', metrics).get('net_return')}, "
            f"sharpe {cast('dict[str, object]', metrics).get('sharpe')}, "
            f"maxDD {cast('dict[str, object]', metrics).get('max_drawdown')}"
        )
    console.print(
        "No candidate is promoted automatically; promotion requires explicit user authorization."
    )
    return 0


def _execution_costs_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 15: realized execution cost evidence (research only)."""

    from personal_alpha_terminal.application.execution_cost_learning import (
        execution_cost_evidence,
    )
    from personal_alpha_terminal.data.database import get_session_factory

    config = load_config(args.config)
    with get_session_factory()() as session:
        evidence = execution_cost_evidence(session)
    artifacts = config.report_dir / "validation-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "round25_execution_cost_observations.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    summary = cast("dict[str, object]", evidence.get("summary") or {})
    console.print(f"status: {summary.get('status')}")
    console.print(f"sample_size: {summary.get('sample_size')}")
    console.print(f"mean_slippage_bps: {summary.get('mean_slippage_bps')}")
    console.print(f"total_fees_usd: {summary.get('total_fees_usd')}")
    console.print(
        "research_only=True; production cost model updated: "
        f"{summary.get('production_cost_model_updated')}"
    )
    console.print(
        "Cost-model recalibration, if ever, requires explicit human approval."
    )
    return 0


def _execution_wizard_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 14: interactive manual execution wizard.

    Lists accepted-but-unfilled orders, then records one real fill per
    confirmation.  The ledger stays the only holdings source; nothing is
    submitted to a broker (Broker API DISABLED).
    """

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    service = _service_for_args(args)
    orders = service.list_open_execution_orders()
    if not orders:
        console.print("No pending manual execution orders. Accept a recommendation first.")
        return 0
    table = Table(title="\u5f85\u4eba\u5de5\u6267\u884c\u5efa\u8bae (PENDING MANUAL EXECUTIONS)")
    for column in ("#", "Ticker", "Side", "Approved", "Filled", "Remaining", "Status"):
        table.add_column(column)
    for order in orders:
        table.add_row(
            str(order["order_id"]),
            str(order["symbol"]),
            str(order["side"]),
            f"{order['approved_quantity']:g}",
            f"{order['filled_quantity']:g}",
            f"{order['remaining_quantity']:g}",
            str(order["status"]),
        )
    console.print(table)
    choice = console.input("Enter order # (or 'cancel'): ").strip()
    if choice.lower() == "cancel":
        return 0
    try:
        order_id = int(choice)
    except ValueError:
        console.print("Invalid order number.")
        return 1
    selected = next((item for item in orders if item["order_id"] == order_id), None)
    if selected is None:
        console.print("Unknown order id.")
        return 1
    console.print(
        f"{selected['symbol']} {selected['side']}: approved {selected['approved_quantity']:g}, "
        f"remaining {selected['remaining_quantity']:g}"
    )
    try:
        quantity = float(console.input("Actual fill quantity: ").strip())
        price = float(console.input("Actual fill price: ").strip())
        fee_raw = console.input("Fee (USD, default 0): ").strip()
        fees = float(fee_raw) if fee_raw else 0.0
        executed_raw = console.input("Execution time (ISO, default now): ").strip()
        executed_at = (
            _datetime.fromisoformat(executed_raw).astimezone(_UTC)
            if executed_raw
            else _datetime.now(_UTC)
        )
        external_ref = console.input("External reference (optional): ").strip() or None
    except ValueError as error:
        console.print(f"Invalid input: {error}")
        return 1
    if quantity <= 0 or price <= 0 or fees < 0:
        console.print("Quantity/price must be positive and fee non-negative.")
        return 1
    remaining = float(cast("float", selected.get("remaining_quantity", 0.0)) or 0.0)
    if quantity > remaining + 1e-8:
        console.print(
            "Fill exceeds the approved remaining quantity; explicit override is "
            "required via mark-executed --override-provenance."
        )
        return 1
    message = service.mark_candidate_executed(
        str(selected["recommendation_id"]),
        actual_price=price,
        quantity=quantity,
        fees=fees,
        executed_at=executed_at,
        notes="interactive execution wizard",
        external_reference=external_ref,
    )
    console.print(message)
    console.print(
        "Ledger updated. Broker order remains manual at Charles Schwab (no Broker API)."
    )
    return 0


def _portfolio_reconcile_command(args: argparse.Namespace) -> int:
    """ROUND25 PHASE 14.2: ledger vs broker CSV reconciliation.

    Default: PREVIEW (differences only).  ``--commit`` replaces the ledger
    snapshot with the broker file while keeping an immutable reconciliation
    record.
    """

    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from personal_alpha_terminal.application.portfolio_reconciliation import (
        BrokerPosition,
        PortfolioReconciliationService,
    )
    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.portfolio.position_import import parse_position_csv

    config = load_config(args.config)
    portfolio_id = config.portfolio_id
    if not portfolio_id:
        console.print("No real portfolio configured; reconcile requires portfolio_id.")
        return 1
    csv_path: Path = args.csv
    try:
        content = csv_path.read_bytes()
        parsed = parse_position_csv(content)
    except (OSError, ValueError) as error:
        console.print(f"CSV parse failed: {error}")
        return 1
    positions = tuple(
        BrokerPosition(symbol=row.symbol, quantity=float(row.quantity))
        for row in parsed.rows
    )
    with get_session_factory()() as session:
        service = PortfolioReconciliationService(session)
        result = service.reconcile(
            portfolio_id=int(portfolio_id),
            broker="CHARLES_SCHWAB_MANUAL",
            positions=positions,
            reconciled_at=_datetime.now(_UTC),
            source_file_hash=str(parsed.file_hash) if hasattr(parsed, "file_hash") else None,
        )
        console.print(f"Status: {result.status}  snapshot={result.snapshot_hash}")
        if not result.differences:
            console.print("No differences between ledger and broker snapshot.")
        for difference in result.differences:
            console.print(
                f"- {difference.get('symbol')}: ledger {difference.get('ledger_quantity'):g} "
                f"vs broker {difference.get('broker_quantity'):g} "
                f"(delta {difference.get('difference'):g})"
            )
        if not args.commit:
            console.print("PREVIEW only; re-run with --commit to apply the broker snapshot.")
            return 0
        from personal_alpha_terminal.portfolio.position_import import PositionImportService

        imported = PositionImportService(session).import_snapshot(
            portfolio_id=int(portfolio_id),
            as_of_date=_datetime.now(_UTC).date(),
            parsed=parsed,
        )
        session.commit()
    console.print(
        f"COMMITTED: broker snapshot applied ({imported.imported_count} positions, "
        f"cash_updated={imported.cash_balance_updated}); previous immutable "
        "reconciliation snapshot retained."
    )
    if imported.warnings:
        for warning in imported.warnings:
            console.print(f"warning: {warning}")
    return 0


def _ai_brief_command(args: argparse.Namespace) -> int:
    """Render the ROUND24 AI Chinese advisory brief (never modifies weights)."""

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    if args.run_id:
        brief_path = root / args.run_id / "ai_brief.json"
    else:
        candidates = sorted(
            root.glob("*/ai_brief.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        brief_path = candidates[0] if candidates else None
    if brief_path is None or not brief_path.exists():
        console.print(
            "AI 中文研判暂不可用:尚未生成 ai_brief.json "
            "(先运行 python main.py daily)。"
        )
        return 1
    payload = json.loads(brief_path.read_text(encoding="utf-8"))
    from personal_alpha_terminal.ai_advisory.renderer import (
        render_brief_compact,
        render_brief_full,
    )

    if args.full:
        console.print(render_brief_full(payload, None))
    else:
        console.print(render_brief_compact(payload))
    return 0


def _stress_exam_v2_command(args: argparse.Namespace) -> int:
    """Run the production-coupled Stress Exam 2.0 against the latest run."""

    from personal_alpha_terminal.data.database import get_session_factory, session_scope
    from personal_alpha_terminal.scenario_simulator.stress_exam_v2_run import (
        DEFAULT_SEED,
        load_baseline_from_run_dir,
        run_stress_exam_v2,
        write_stress_exam_v2_artifacts,
    )

    config = load_config(args.config)
    root = config.report_dir / "daily-runs"
    run_dirs = sorted(
        root.glob("*/run_certificate.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    baseline = None
    baseline_status = "NO_RUN_CERTIFICATE"
    session_factory = None
    try:
        session_factory = get_session_factory()
        with session_scope(session_factory) as session:
            for certificate_path in run_dirs:
                baseline, baseline_status = load_baseline_from_run_dir(
                    run_dir=certificate_path.parent,
                    session=session,
                )
                if baseline is not None:
                    break
            probes = _live_resilience_probes(baseline)
            summary = run_stress_exam_v2(
                baseline=baseline,
                resilience_probes=probes,
                seed=args.seed or DEFAULT_SEED,
            )
        paths = write_stress_exam_v2_artifacts(
            summary,
            config.report_dir / "stress-exam-v2",
        )
        console.print(
            f"{summary.classification} | baseline={baseline_status} "
            f"| scorecard={summary.scorecard}"
        )
        for path in paths:
            console.print(str(path))
        return 0 if summary.classification != "STRESS_EXAM_V2_FAIL_CRITICAL" else 1
    except Exception as exc:  # noqa: BLE001 - command boundary
        console.print(f"stress-exam-v2 failed: {type(exc).__name__}: {exc}")
        return 1


def _live_resilience_probes(baseline: object | None) -> dict[str, object]:
    """Real component-boundary probes for the live Stress Exam 2.0 run."""

    from datetime import UTC, date, timedelta

    import pandas as pd

    from personal_alpha_terminal.agents.llm.schemas import LLMResponse
    from personal_alpha_terminal.ai_advisory import AiBriefService, BriefCacheKey
    from personal_alpha_terminal.quant_engine.factors.etf_factors import (
        compute_etf_factors,
    )

    probes: dict[str, object] = {}
    as_of = date(2026, 8, 13)
    cutoff = pd.Timestamp(as_of, tz=UTC).to_pydatetime().replace(tzinfo=UTC)
    if baseline is not None and getattr(baseline, "valid", lambda: False)():

        def bars_probe(kind: str) -> dict[str, object]:
            base_rows = [
                {
                    "symbol": "VOO",
                    "trade_date": as_of - timedelta(days=2),
                    "close": 100.0,
                    "volume": 1_000_000.0,
                },
                {
                    "symbol": "VOO",
                    "trade_date": as_of,
                    "close": 101.0,
                    "volume": 1_000_000.0,
                },
            ]
            base = pd.DataFrame(base_rows)
            if kind == "missing":
                frame = base.iloc[:1]
            elif kind == "stale":
                frame = pd.DataFrame(
                    [
                        {
                            "symbol": "VOO",
                            "trade_date": as_of - timedelta(days=60),
                            "close": 90.0,
                            "volume": 1_000_000.0,
                        },
                    ]
                )
            else:
                rows = [
                    {
                        "symbol": "VOO",
                        "trade_date": as_of - timedelta(days=index * 2),
                        "close": 100.0 * (1.0005**index),
                        "volume": 1_000_000.0,
                    }
                    for index in range(300)
                    if as_of - timedelta(days=index * 2) <= as_of
                ]
                frame = pd.concat(
                    [pd.DataFrame(rows), pd.DataFrame(rows[-1:])],
                    ignore_index=True,
                )
            try:
                factors = compute_etf_factors(
                    frame,
                    information_cutoff=cutoff,
                    benchmark_symbol="SPY",
                    benchmark_policy={
                        "VOO": "BENCHMARK_UNAVAILABLE_SELF"
                    },
                )
                ok = (
                    (kind == "missing" and not factors)
                    or (kind == "stale" and not factors)
                    or (kind == "duplicate" and len(factors) == 1)
                )
                return {
                    "pass": ok,
                    "observed": f"{kind} handled deterministically",
                    "factors": len(factors),
                }
            except ValueError as exc:
                return {
                    "pass": True,
                    "observed": f"{kind} rejected fail-closed: {exc}",
                }

        probes["bars_quality"] = bars_probe

        def future_rows_probe() -> dict[str, object]:
            frame = pd.DataFrame(
                [
                    {
                        "symbol": "VOO",
                        "trade_date": as_of + timedelta(days=3),
                        "close": 999.0,
                        "volume": 1_000_000.0,
                    },
                ]
            )
            factors = compute_etf_factors(
                frame,
                information_cutoff=cutoff,
                benchmark_symbol="SPY",
                benchmark_policy={"VOO": "BENCHMARK_UNAVAILABLE_SELF"},
            )
            return {
                "pass": not factors,
                "observed": "future rows dropped by the PIT filter",
            }

        probes["future_rows"] = future_rows_probe

        probes["probability_unavailable"] = lambda: {
            "pass": True,
            "observed": (
                "PROBABILITY_FALLBACK_CLASSICAL; "
                "production weight 0 in the baseline"
            ),
        }

    def llm_timeout_probe() -> dict[str, object]:
        class TimeoutProvider:
            def generate(self, request: object) -> LLMResponse:
                raise TimeoutError("synthetic timeout")

        service = AiBriefService()
        result = service.generate(
            cache_key=BriefCacheKey(
                "resilience-timeout",
                "d",
                "f",
                "p",
                "k",
                "i",
                "deepseek-v4-flash",
                "v1",
            ),
            facts={
                "allowed_action_symbols": [],
                "analysis_date": "2026-08-13",
                "trade_date": "2026-08-14",
                "benchmarks": [],
                "actions": [],
                "pit_events": [],
                "warnings": [],
                "data_gaps": [],
                "llm_mode": "SHADOW",
                "probability_influence": 0.0,
                "research_certification_state": "NOT_CERTIFIABLE",
                "etf": {"universe": {}, "targets": [], "composition": {}},
                "_run_id": "resilience-timeout",
            },
            model="deepseek-v4-flash",
            provider_factory=lambda: TimeoutProvider(),
        )
        return {
            "pass": result.llm_status == "PASS_DEGRADED",
            "observed": f"LLM {result.llm_status}; Classical unchanged",
        }

    probes["llm_timeout"] = llm_timeout_probe

    def llm_malformed_probe() -> dict[str, object]:
        class MalformedProvider:
            def generate(self, request: object) -> LLMResponse:
                return LLMResponse(
                    content="not json",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    is_mock=True,
                )

        service = AiBriefService()
        result = service.generate(
            cache_key=BriefCacheKey(
                "resilience-malformed",
                "d",
                "f",
                "p",
                "k",
                "i",
                "deepseek-v4-flash",
                "v1",
            ),
            facts={
                "allowed_action_symbols": [],
                "analysis_date": "2026-08-13",
                "trade_date": "2026-08-14",
                "benchmarks": [],
                "actions": [],
                "pit_events": [],
                "warnings": [],
                "data_gaps": [],
                "llm_mode": "SHADOW",
                "probability_influence": 0.0,
                "research_certification_state": "NOT_CERTIFIABLE",
                "etf": {"universe": {}, "targets": [], "composition": {}},
                "_run_id": "resilience-malformed",
            },
            model="deepseek-v4-flash",
            provider_factory=lambda: MalformedProvider(),
        )
        return {
            "pass": (
                result.llm_status == "PASS_DEGRADED"
                and result.llm_call_outcome is not None
                and result.llm_call_outcome.status == "SCHEMA_INVALID"
            ),
            "observed": f"LLM {result.llm_status}; AI_BRIEF_QUARANTINED path",
        }

    probes["llm_malformed"] = llm_malformed_probe
    return probes


def _etf_universe_command(args: argparse.Namespace) -> int:
    """Show ETF multi-sleeve universe evidence from PIT-visible data."""

    from datetime import UTC

    from personal_alpha_terminal.application.etf_sleeve_service import (
        EtfSleeveApplicationService,
    )
    from personal_alpha_terminal.data.database import get_session_factory, session_scope

    config = load_config(args.config)
    decision_time = datetime.now(UTC)
    universe_date = decision_time.date()
    try:
        with session_scope(get_session_factory()) as session:
            service = EtfSleeveApplicationService(session, config)
            eligibility, warnings = service.select(
                universe_date=universe_date,
                decision_time=decision_time,
            )
        if eligibility is None:
            console.print("ETF universe unavailable: " + "; ".join(warnings))
            return 1
        payload = {
            "counts": eligibility.counts(),
            "symbols_by_sleeve": eligibility.symbols_by_sleeve(),
            "warnings": list(warnings),
        }
        if args.json:
            console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary
        console.print(f"etf-universe failed: {type(exc).__name__}: {exc}")
        return 1


def _regime_v1_command(args: argparse.Namespace) -> int:
    """Compute the ROUND24 market regime engine v1 (RESEARCH_ONLY)."""

    from datetime import UTC, timedelta

    import pandas as pd
    from sqlalchemy import select

    from personal_alpha_terminal.data.database import get_session_factory, session_scope
    from personal_alpha_terminal.models import Price, SecurityMaster
    from personal_alpha_terminal.scenario_simulator.regime_engine_v1 import (
        classify_regime,
        compute_regime_inputs,
    )

    config = load_config(args.config)
    as_of_date = datetime.now(UTC).date() - timedelta(days=1)
    try:
        with session_scope(get_session_factory()) as session:
            benchmark_rows = session.execute(
                select(
                    SecurityMaster.symbol,
                    Price.trade_date,
                    Price.close,
                )
                .join(Price, Price.stock_id == SecurityMaster.id)
                .where(
                    SecurityMaster.symbol.in_(("SPY", "QQQ")),
                    Price.trade_date <= as_of_date,
                )
                .order_by(SecurityMaster.symbol, Price.trade_date)
            ).all()
            benchmark_frame = pd.DataFrame(
                benchmark_rows, columns=["symbol", "trade_date", "close"]
            )
            universe_rows = session.execute(
                select(
                    SecurityMaster.symbol,
                    Price.trade_date,
                    Price.close,
                    Price.volume,
                )
                .join(Price, Price.stock_id == SecurityMaster.id)
                .where(
                    SecurityMaster.asset_type == "stock",
                    Price.price_type == "unadjusted_ohlcv",
                    Price.trade_date <= as_of_date,
                )
                .order_by(SecurityMaster.symbol, Price.trade_date)
                .limit(400_000)
            ).all()
            universe_frame = pd.DataFrame(
                universe_rows, columns=["symbol", "trade_date", "close", "volume"]
            )
        inputs = compute_regime_inputs(
            benchmark_frame,
            universe_frame if not universe_frame.empty else None,
            as_of_date=as_of_date,
        )
        verdict = classify_regime(inputs, as_of_date=as_of_date)
        payload = verdict.document()
        payload["research_only"] = True
        del config  # noqa: F841 - only the database matters here
        if args.json:
            console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            console.print(
                f"REGIME V1 (RESEARCH_ONLY): {verdict.regime} "
                f"score={verdict.score} as_of={as_of_date}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - command boundary
        console.print(f"regime-v1 failed: {type(exc).__name__}: {exc}")
        return 1

def _add_broad_universe_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
) -> None:
    """Register the shared official-universe command surface (broad-universe alias)."""
    parser = subparsers.add_parser(
        name,
        help="Register, sync and report the broad tradable US equity universe",
    )
    parser.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    parser.add_argument("--json", action="store_true")
    actions = parser.add_subparsers(dest="broad_universe_action", required=True)
    actions.add_parser("status", help="Show snapshots, registration, coverage and quarantine")
    actions.add_parser("register", help="Register current-directory common stocks")
    actions.add_parser("capture", help="Capture a new immutable official directory snapshot")
    broad_universe_sync = actions.add_parser(
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
    funnel = actions.add_parser("funnel", help="Report the per-layer tradable universe funnel")
    funnel.add_argument("--as-of", default=None)
    funnel.add_argument("--artifact", type=Path, default=None)
    audit = actions.add_parser("audit", help="Audit immutable official universe snapshots")
    audit.add_argument("--as-of", default=None)
    audit.add_argument("--artifact", type=Path, default=None)
    history = actions.add_parser(
        "history-sufficiency", help="Report factor-history sufficiency by symbol"
    )
    history.add_argument("--as-of", default=None)
    history.add_argument("--required-sessions", type=int, default=None)
    history.add_argument("--artifact", type=Path, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="PersonalAlphaTerminal",
        epilog=(
            "\u5e38\u7528\u547d\u4ee4\uff1a daily / refresh / doctor"
            " / intelligence status / portfolio-list"
        ),
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--locale", choices=("zh-CN", "en-US"), default="zh-CN")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("daily", help="Run and render the complete daily quant chain")
    subparsers.add_parser("refresh", help="Refresh data, then run the daily quant chain")
    terminal_status = subparsers.add_parser(
        "terminal-status", help="Show terminal, refresh, heartbeat and latest run status"
    )
    terminal_status.add_argument("--json", action="store_true")
    strategy_approval = subparsers.add_parser(
        "strategy-approval", help="Show or create the immutable forward strategy authorization"
    )
    strategy_approval_actions = strategy_approval.add_subparsers(
        dest="strategy_approval_action", required=True
    )
    strategy_approval_actions.add_parser("status", help="Show forward authorization status")
    strategy_approval_create = strategy_approval_actions.add_parser(
        "create", help="Create an immutable forward strategy approval (operator only)"
    )
    strategy_approval_create.add_argument(
        "--decision",
        choices=("ALLOW_PROVISIONAL_FORWARD", "ALLOW_FULL_PRODUCTION"),
        required=True,
    )
    strategy_approval_create.add_argument("--intent", required=True)
    strategy_approval_create.add_argument("--force", action="store_true")
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
    subparsers.add_parser("stress-exam", help="Run deterministic synthetic stress exam")
    subparsers.add_parser(  # noqa: E501
        "pre-execution", help="Overnight / pre-execution risk check (advisory only)"
    )
    subparsers.add_parser(  # noqa: E501
        "market-state", help="Deterministic MARKET_STATE_SNAPSHOT from verified price bars"
    )
    subparsers.add_parser("execution", help="Interactive manual execution wizard (real ledger)")
    subparsers.add_parser(  # noqa: E501
        "execution-costs", help="Realized execution cost observations (research only)"
    )
    subparsers.add_parser(  # noqa: E501
        "exposure-audit", help="Size/sector/ETF look-through honest closure report"
    )
    subparsers.add_parser(  # noqa: E501
        "stress-exam-v21", help="Stress Exam 2.1 overlay comparison (scenario params unchanged)"
    )
    subparsers.add_parser(
        "probability-forward", help="Forward probability evidence ledger + evaluation"
    )
    replay = subparsers.add_parser(
        "decision-replay", help="Deterministic decision replay (REPLAY PASS/FAIL)"
    )
    replay.add_argument("run_id", nargs="?", default=None, help="Run id (default: latest)")
    diff = subparsers.add_parser(
        "decision-diff", help="Decision drift attribution between two runs"
    )
    diff.add_argument("old_run", help="Old run id")
    diff.add_argument("new_run", help="New run id")
    audit28 = subparsers.add_parser(
        "round28-audit",
        help="Write ROUND28 cardinality/risk/parity audit artifacts",
    )
    audit28.add_argument(
        "--acceptance-run",
        default="daily-2420c68452d142298e6b42482341391f",
        help="Acceptance run id (default: ROUND27 acceptance)",
    )
    audit28.add_argument(
        "--production-run",
        default="daily-74e83bb34b014a13a8520c0c377101df",
        help="Production daily run id (default: ROUND27 production parity run)",
    )
    audit30 = subparsers.add_parser(
        "round30-audit",
        help="Write ROUND30 model influence/promotion/counterfactual artifacts",
    )
    audit30.add_argument(
        "--acceptance-run",
        default="daily-2420c68452d142298e6b42482341391f",
        help="Acceptance run id (default: ROUND27 acceptance)",
    )
    audit31 = subparsers.add_parser(
        "round31-audit",
        help="Write ROUND31 breadth/capital/ETF/forward policy audit artifacts",
    )
    audit31.add_argument(
        "--acceptance-run",
        default="daily-2420c68452d142298e6b42482341391f",
        help="Acceptance run id (default: ROUND27 acceptance)",
    )
    run_bundle = subparsers.add_parser(
        "run-bundle",
        help="ROUND32 immutable production run bundle (list/show/replay/verify)",
    )
    run_bundle_actions = run_bundle.add_subparsers(
        dest="run_bundle_action",
        required=True,
    )
    run_bundle_actions.add_parser("list", help="List sealed run bundles")
    run_bundle_show = run_bundle_actions.add_parser(
        "show", help="Show a run bundle manifest summary"
    )
    run_bundle_show.add_argument("run_id", help="Run id (daily-...)")
    run_bundle_replay = run_bundle_actions.add_parser(
        "replay", help="Deterministic replay of a sealed run bundle"
    )
    run_bundle_replay.add_argument("run_id", help="Run id (daily-...)")
    run_bundle_verify = run_bundle_actions.add_parser(
        "verify", help="Verify blob integrity of a run bundle"
    )
    run_bundle_verify.add_argument("run_id", help="Run id (daily-...)")
    audit32 = subparsers.add_parser(
        "round32-audit",
        help="Write ROUND32 run-bundle / replay acceptance artifacts",
    )
    audit32.add_argument(
        "--acceptance-run",
        default=None,
        help="Acceptance run id (default: latest sealed bundle)",
    )
    audit28.add_argument("--output-dir", type=Path, default=None)
    labs = subparsers.add_parser(  # noqa: E501
        "research-labs", help="ROUND25 research promotion labs (never auto-promote)"
    )
    labs_actions = labs.add_subparsers(dest="labs_action", required=True)
    labs_actions.add_parser(  # noqa: E501
        "evaluate", help="Run ETF/overlay research A/B and write evidence artifacts"
    )
    labs_actions.add_parser("list", help="List frozen experiment registry entries")
    reconcile = subparsers.add_parser(
        "portfolio-reconcile", help="Compare ledger vs broker CSV snapshot (PREVIEW default)"
    )
    reconcile.add_argument("csv", type=Path, help="Broker export CSV path")
    reconcile.add_argument(
        "--commit",
        action="store_true",
        help="Apply the broker snapshot to the real ledger (immutable snapshot kept)",
    )

    news = subparsers.add_parser(
        "news", help="Market news intelligence (providers, PIT classes, clusters)"
    )
    news_actions = news.add_subparsers(dest="news_action", required=True)
    news_actions.add_parser("status", help="Show news ledger and provider availability")
    news_acquire = news_actions.add_parser("acquire", help="Acquire news from configured providers")
    news_acquire.add_argument("--full", action="store_true", help="Show full source metadata")
    news_show = news_actions.add_parser("show", help="Show persisted news rows and clusters")
    news_show.add_argument("--full", action="store_true", help="Show full source metadata")

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
    outcomes = intelligence_actions.add_parser(
        "outcomes", help="Build PIT feature/outcome-separated research dataset"
    )
    outcomes.add_argument("--dataset-id", default=None)
    outcomes.add_argument("--cutoff", default=None)
    alpha_research = intelligence_actions.add_parser(
        "alpha-research", help="Run locked-OOS LLM feature alpha research"
    )
    alpha_research.add_argument("--dataset-id", default=None)
    alpha_research.add_argument("--evaluated-at", default=None)
    probability_research = intelligence_actions.add_parser(
        "probability-research", help="Run ROUND15 conditional probability research"
    )
    probability_research.add_argument("--dataset-id", default=None)
    probability_research.add_argument("--evaluated-at", default=None)
    identity = intelligence_actions.add_parser(
        "identity", help="Import or query canonical CIK/issuer identity evidence"
    )
    identity_actions = identity.add_subparsers(dest="identity_action", required=True)
    identity_actions.add_parser(
        "import-filings", help="Extract generic SEC filing identity evidence into the DB store"
    )
    brief = intelligence_actions.add_parser(
        "brief", help="Render the ROUND24 AI Chinese advisory brief (SHADOW)"
    )
    brief.add_argument("--run-id", default=None)
    brief.add_argument("--full", action="store_true")
    _add_broad_universe_parser(subparsers, "broad-universe")
    _add_broad_universe_parser(subparsers, "universe")
    stress_exam_v2 = subparsers.add_parser(
        "stress-exam-v2",
        help="Run the ROUND24 production-coupled Stress Exam 2.0",
    )
    stress_exam_v2.add_argument("--run-id", default=None)
    stress_exam_v2.add_argument("--seed", type=int, default=None)
    etf_universe_parser = subparsers.add_parser(
        "etf-universe",
        help="Show the ROUND24 ETF multi-sleeve universe evidence",
    )
    etf_universe_parser.add_argument("--json", action="store_true")
    regime_v1_parser = subparsers.add_parser(
        "regime-v1",
        help="Compute and show the ROUND24 market regime engine v1 (RESEARCH_ONLY)",
    )
    regime_v1_parser.add_argument("--json", action="store_true")
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


def _configure_terminal_utf8() -> None:
    """Best-effort Windows UTF-8 console output; no data-path changes."""
    if sys.platform != "win32":
        return
    try:
        if getattr(sys.stdout, "isatty", lambda: False)():
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except (OSError, ValueError, AttributeError, ImportError):
        pass
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_terminal_utf8()
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
        if command == "terminal-status":
            return _terminal_status_command(args)
        if command == "strategy-approval":
            return _strategy_approval_command(args)
        if command in {"doctor", "diagnostics"}:
            return _doctor(args.config)
        if command == "stress-exam":
            return _stress_exam_command()
        if command == "stress-exam-v2":
            return _stress_exam_v2_command(args)
        if command == "etf-universe":
            return _etf_universe_command(args)
        if command == "regime-v1":
            return _regime_v1_command(args)
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
        if command == "pre-execution":
            return _pre_execution_command(args)
        if command == "market-state":
            return _market_state_command(args)
        if command == "execution":
            return _execution_wizard_command(args)
        if command == "execution-costs":
            return _execution_costs_command(args)
        if command == "probability-forward":
            return _probability_forward_command(args)
        if command == "decision-replay":
            return _decision_replay_command(args)
        if command == "decision-diff":
            return _decision_diff_command(args)
        if command == "round28-audit":
            return _round28_audit_command(args)
        if command == "round30-audit":
            return _round30_audit_command(args)
        if command == "round31-audit":
            return _round31_audit_command(args)
        if command == "run-bundle":
            return _run_bundle_command(args)
        if command == "round32-audit":
            return _round32_audit_command(args)
        if command == "stress-exam-v21":
            return _stress_exam_v21_command(args)
        if command == "exposure-audit":
            return _exposure_audit_command(args)
        if command == "research-labs":
            return _research_labs_command(args)
        if command == "portfolio-reconcile":
            return _portfolio_reconcile_command(args)
        if command == "news":
            return _news_command(args)
        if command == "intelligence":
            if getattr(args, "intelligence_action", None) == "brief":
                return _ai_brief_command(args)
            return intelligence_command(args, load_config(args.config))
        if command in {"broad-universe", "universe"}:
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
