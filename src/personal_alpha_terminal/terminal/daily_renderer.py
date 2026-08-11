from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    StageStatus,
)


def render_daily_quant_result(result: DailyQuantResult, console: Console) -> None:
    """Render one immutable result. No model, gate or trade calculation lives here."""

    console.print(
        Panel(
            _header(result),
            title="PERSONAL ALPHA TERMINAL · TODAY QUANT REPORT",
            border_style="cyan",
        )
    )
    _pipeline(result, console)
    _data_certification(result, console)
    _pit_universe(result, console)
    _data_health(result, console)
    _market(result, console)
    _portfolio(result, console)
    _factors(result, console)
    _probability(result, console)
    _risk(result, console)
    _decisions(result, console)
    _rejected(result, console)
    _execution(result, console)
    _benchmark(result, console)
    _run_certificate(result, console)
    _summary(result, console)


def capture_daily_quant_result(result: DailyQuantResult, *, width: int = 120) -> str:
    stream = StringIO()
    console = Console(file=stream, width=width, color_system=None, force_terminal=False)
    render_daily_quant_result(result, console)
    return stream.getvalue()


def _layered_status(result: DailyQuantResult) -> str:
    data_status = next(
        (stage.status for stage in result.stages if stage.name == "DATA"),
        None,
    )
    data_ready = data_status in {StageStatus.PASS, StageStatus.PASS_DEGRADED}
    quant_ready = result.diagnostic_analysis_complete
    portfolio_ready = result.portfolio.status != "NOT_INITIALIZED"
    risk_ready = result.risk.status == "PASS"
    trading_actionable = result.actionable
    return (
        f"DATA {'READY' if data_ready else 'BLOCKED'}   "
        f"QUANT ANALYSIS {'READY' if quant_ready else 'NOT READY'}   "
        f"PORTFOLIO {'READY' if portfolio_ready else 'REQUIRED'}   "
        f"RISK {'READY' if risk_ready else 'BLOCKED'}   "
        f"TRADING {'ACTIONABLE' if trading_actionable else 'BLOCKED'}   "
        f"LLM {result.llm_status}"
    )


def _header(result: DailyQuantResult) -> str:
    classification = {
        "CERTIFIED_ACTIONABLE": "ACTIONABLE TRADING PLAN · MANUAL EXECUTION ONLY",
        "CERTIFIED_NO_ACTION": "CERTIFIED NO-ACTION RUN",
        "VALID_ANALYSIS_NON_ACTIONABLE": (
            "VALID QUANT ANALYSIS / NON-ACTIONABLE\n"
            "FORMAL TRADING DECISION NOT AVAILABLE"
        ),
        "INVALID_NON_ACTIONABLE": "INVALID / NON-ACTIONABLE QUANT RUN\nDO NOT USE FOR TRADING",
    }[result.run_classification]
    raw_latest = max(
        (item.latest_date for item in result.data_health if item.latest_date),
        default=None,
    )
    data_through = (
        result.data_cutoff.isoformat()
        if result.data_cutoff
        else (
            f"{raw_latest} (raw only; PIT cutoff unavailable)"
            if raw_latest
            else "UNAVAILABLE"
        )
    )
    return (
        f"{classification}\n\nVersion {result.version}   Run {result.run_id}\n"
        f"ET/Market session {result.market_session}   Analysis {result.analysis_date}   "
        f"Trade {result.trade_date}\n"
        f"Data through {data_through}   "
        f"Duration {result.duration_seconds:.2f}s\n"
        f"{_layered_status(result)}"
    )


def _pipeline(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="PIPELINE · FAIL CLOSED", show_lines=False)
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Time", justify="right")
    table.add_column("Message", overflow="fold")
    for stage in result.stages:
        table.add_row(
            stage.name,
            _status_text(stage.status),
            f"{stage.duration_seconds:.2f}s",
            stage.message,
        )
    console.print(table)


def _data_certification(result: DailyQuantResult, console: Console) -> None:
    stage = next((item for item in result.stages if item.name == "DATA"), None)
    evidence = stage.metadata if stage is not None else {}
    body = (
        f"Status {stage.status.value if stage else 'NOT_RUN'}   "
        f"Provider {evidence.get('provider', 'UNAVAILABLE')}\n"
        f"Snapshot {evidence.get('snapshot_id', 'UNAVAILABLE')}   "
        f"Requested {_item_count(evidence.get('requested_symbols'))}   "
        f"Received {_item_count(evidence.get('received_symbols'))}   "
        f"Valid {_item_count(evidence.get('certified_symbols'))}   "
        f"Rejected {_item_count(evidence.get('rejected_symbols'))}   "
        f"Missing {_item_count(evidence.get('missing_symbols'))}   "
        f"Stale {_item_count(evidence.get('stale_symbols'))}\n"
        f"Bars expected {evidence.get('expected_bars', 0)}   "
        f"matched {evidence.get('matched_bars', 0)}   "
        f"unexpected {evidence.get('unexpected_bars', 0)}   "
        f"quarantined {evidence.get('quarantined_bars', 0)}   "
        f"missing {evidence.get('missing_bars', 0)}   "
        f"received {evidence.get('received_bars', 0)}   "
        f"valid {evidence.get('valid_bars', 0)}   "
        f"coverage {_percent(_as_float(evidence.get('coverage')))}\n"
        f"Latest {evidence.get('latest_timestamp', 'UNAVAILABLE')}   "
        f"PIT cutoff {result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}\n"
        f"Corporate actions {evidence.get('corporate_action_status', 'NOT_CERTIFIED')}   "
        f"PIT integrity {evidence.get('pit_integrity_status', 'NOT_CERTIFIED')}   "
        f"Freshness {evidence.get('freshness_status', 'NOT_CERTIFIED')}   "
        f"Duplicates {evidence.get('duplicate_rows', 0)}   "
        f"Invalid OHLC {evidence.get('invalid_ohlc', 0)}   "
        f"Future rows {evidence.get('future_rows', 0)}   "
        f"Timezone violations {evidence.get('timezone_violations', 0)}"
    )
    fallback_usage = evidence.get("fallback_usage", ())
    if isinstance(fallback_usage, (list, tuple)) and fallback_usage:
        fallback_table = Table(title="FALLBACK USED")
        fallback_table.add_column("Ticker")
        fallback_table.add_column("Provider")
        fallback_table.add_column("Reason", overflow="fold")
        for item in fallback_usage:
            if isinstance(item, dict):
                fallback_table.add_row(
                    str(item.get("symbol", "--")),
                    str(item.get("provider", "--")),
                    str(item.get("reason", "primary request failed")),
                )
        console.print(fallback_table)
    console.print(
        Panel(
            body,
            title="DATA CERTIFICATION",
            border_style=(
                "green"
                if stage and stage.status is StageStatus.PASS
                else "yellow"
                if stage and stage.status is StageStatus.PASS_DEGRADED
                else "red"
            ),
        )
    )
    matrix = evidence.get("symbol_matrix", ())
    rejected = [
        item
        for item in matrix
        if isinstance(item, dict) and item.get("final") != "CERTIFIED"
    ] if isinstance(matrix, (list, tuple)) else []
    if rejected:
        table = Table(title="REJECTED DATA")
        table.add_column("Ticker")
        table.add_column("Required")
        table.add_column("Gate")
        table.add_column("Reason", overflow="fold")
        for item in rejected:
            gate = "DATA"
            if item.get("primary") != "PASS":
                gate = "PRIMARY/CALENDAR"
            elif item.get("corporate_action") not in {"PASS", "PASS_WITH_WARNING"}:
                gate = "CORPORATE_ACTION"
            table.add_row(
                str(item.get("symbol", "--")),
                "YES" if item.get("required") else "NO",
                gate,
                str(item.get("reason", "unavailable")),
            )
        console.print(table)


def _pit_universe(result: DailyQuantResult, console: Console) -> None:
    stage = next((item for item in result.stages if item.name == "PIT"), None)
    evidence = stage.metadata if stage is not None else {}
    data_stage = next((item for item in result.stages if item.name == "DATA"), None)
    data_evidence = data_stage.metadata if data_stage is not None else {}
    console.print(
        Panel(
            f"Status {stage.status.value if stage else 'NOT_RUN'}   "
            f"Rows {evidence.get('output_row_count', 0)}   "
            f"Universe {result.provenance.get('universe_count', 0)}\n"
            "As-of cutoff "
            f"{result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}\n"
            "Latest completed session "
            f"{data_evidence.get('latest_completed_session', result.analysis_date)}\n"
            "Decision convention "
            f"{data_evidence.get('decision_timestamp_convention', 'UNAVAILABLE')}\n"
            f"Message: {stage.message if stage else 'PIT stage was not created'}",
            title="PIT / UNIVERSE",
            border_style=(
                "green"
                if stage and stage.status is StageStatus.PASS
                else "yellow"
                if stage and stage.status is StageStatus.PASS_DEGRADED
                else "red"
            ),
        )
    )


def _data_health(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="DATA HEALTH · STRATEGY INPUTS ONLY")
    narrow = console.width < 100
    columns = (
        ("Dataset", "Latest / Expected", "Source", "Status", "Detail")
        if narrow
        else (
            "Dataset",
            "Expected",
            "Latest",
            "Age",
            "Coverage",
            "Missing",
            "Source",
            "Status",
            "Detail",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    if not result.data_health:
        empty = (
            ("PIT DATASET", "-- / --", "UNAVAILABLE", "FAIL", "No canonical input")
            if narrow
            else (
                "PIT DATASET",
                "--",
                "--",
                "--",
                "--",
                "--",
                "UNAVAILABLE",
                "FAIL",
                "No canonical strategy input was available",
            )
        )
        table.add_row(*empty)
    for item in result.data_health:
        row = (
            (
                item.dataset,
                f"{item.latest_date or '--'} / {item.expected_date or '--'}",
                item.source,
                item.status.value,
                item.detail or "--",
            )
            if narrow
            else (
                item.dataset,
                str(item.expected_date or "--"),
                str(item.latest_date or "--"),
                str(item.age_days) if item.age_days is not None else "--",
                _percent(item.coverage),
                _percent(item.missing_ratio),
                item.source,
                item.status.value,
                item.detail or "--",
            )
        )
        table.add_row(*row)
    console.print(table)


def _market(result: DailyQuantResult, console: Console) -> None:
    console.print(
        Panel(
            f"State: {result.market_regime}\n{result.market_regime_detail}\n"
            f"Structure: {result.market_structure}",
            title="MARKET REGIME",
        )
    )


def _portfolio(result: DailyQuantResult, console: Console) -> None:
    summary = result.portfolio
    onboarding = (
        "\nQuant diagnostics remain available. Formal trading decisions require:\n"
        "  portfolio-init\n  or portfolio-import"
        if summary.status == "NOT_INITIALIZED"
        else ""
    )
    console.print(
        Panel(
            f"Status {summary.status}   NAV {_money(summary.nav)}   Cash {_money(summary.cash)}   "
            f"Invested {_percent(summary.invested_weight)}   "
            f"Cash weight {_percent(summary.cash_weight)}{onboarding}",
            title="REAL PORTFOLIO · MANUAL LEDGER",
        )
    )
    table = Table()
    for column in ("Ticker", "Shares", "Price", "Current", "Target", "Delta"):
        table.add_column(column, justify="right" if column != "Ticker" else "left")
    if not summary.positions:
        table.add_row("PORTFOLIO NOT INITIALIZED", "--", "--", "--", "--", "--")
    for item in summary.positions:
        table.add_row(
            item.symbol,
            f"{item.shares:g}" if item.shares is not None else "--",
            f"{item.price:.2f}" if item.price is not None else "--",
            _percent(item.current_weight),
            _percent(item.target_weight),
            _signed_percent(item.delta_weight),
        )
    console.print(table)


def _factors(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="FACTOR / ALPHA · CANDIDATE ≠ TRADE")
    component_names = (
        []
        if console.width < 100
        else sorted({name for row in result.factors for name in row.components})
    )
    table.add_column("Rank", justify="right")
    table.add_column("Ticker")
    for name in component_names:
        table.add_column(name[:12], justify="right")
    table.add_column("Composite", justify="right")
    table.add_column("Exp Alpha", justify="right")
    table.add_column("Evidence", justify="right")
    table.add_column("Status")
    if not result.candidates:
        table.add_row(
            "--",
            "NO VALID CANDIDATES",
            *("--" for _ in component_names),
            "--",
            "--",
            "--",
            "DIAGNOSTIC ONLY",
        )
    for row in result.candidates:
        table.add_row(
            str(row.rank),
            row.symbol,
            *(f"{row.components.get(name, 0.0):+.2f}" for name in component_names),
            f"{row.composite:+.2f}",
            _signed_percent(row.expected_alpha),
            _percent(row.evidence_coverage),
            row.status,
        )
    console.print(table)


def _probability(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="CONDITIONAL PROBABILITY · SUPPORTING EVIDENCE ONLY")
    narrow = console.width < 100
    columns = (
        ("Condition", "N", "P(cond)", "Lift", "Reliability / OOS")
        if narrow
        else (
            "Condition",
            "Target",
            "N",
            "Hits",
            "P(cond)",
            "P(base)",
            "Lift",
            "Avg",
            "Median",
            "Std",
            "CI",
            "Reliability",
            "OOS",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    for row in result.probabilities:
        interval = (
            f"[{row.credible_interval[0]:.1%}, {row.credible_interval[1]:.1%}]"
            if row.credible_interval
            else "--"
        )
        values = (
            (
                row.condition,
                str(row.sample_size),
                _percent(row.conditional_probability),
                _signed_percent(row.lift),
                f"{row.reliability}; {row.oos_status}",
            )
            if narrow
            else (
                row.condition,
                row.target,
                str(row.sample_size),
                str(row.hits) if row.hits is not None else "--",
                _percent(row.conditional_probability),
                _percent(row.base_probability),
                _signed_percent(row.lift),
                _signed_percent(row.average_return),
                _signed_percent(row.median_return),
                _percent(row.return_std),
                interval,
                row.reliability,
                row.oos_status,
            )
        )
        table.add_row(*values)
    console.print(table)
    for row in result.probabilities:
        if row.conditional_probability is not None:
            console.print(f"  {row.condition[:28]:28} {_bar(row.conditional_probability)}")


def _risk(result: DailyQuantResult, console: Console) -> None:
    risk = result.risk
    stress_notes = (*risk.stress_failures, *risk.stress_warnings)
    console.print(
        Panel(
            f"Correlation {risk.correlation_status}: "
            f"recent {_number(risk.recent_average_correlation)} / "
            f"baseline {_number(risk.baseline_average_correlation)} / "
            f"jump {_number(risk.correlation_jump)} "
            f"(N={risk.correlation_sample_count})\n"
            f"Size exposure {risk.size_exposure_status}   Stress {risk.stress_status}\n"
            + (
                "Stress evidence: " + "; ".join(stress_notes)
                if stress_notes
                else "Stress evidence: no veto or warning"
            ),
            title="RISK EVIDENCE - CAUSAL CORRELATION / SIZE / STRESS",
            border_style="yellow" if risk.stress_status != "PASS" else "green",
        )
    )
    console.print(
        Panel(
            f"Gate {risk.status}   Expected vol {_percent(risk.expected_volatility)}   "
            f"Target vol {_percent(risk.target_volatility)}   HHI {_number(risk.hhi)}\n"
            f"Largest target {_percent(risk.largest_target_weight)}   "
            f"Gross {_percent(risk.gross_exposure)} → Cash {_percent(risk.cash_target)}   "
            f"Turnover {_percent(risk.turnover)}\n"
            + ("Reasons: " + "; ".join(risk.reasons) if risk.reasons else "Reasons: none"),
            title="RISK · RAW TARGET → RISK-ADJUSTED TARGET",
            border_style="yellow" if risk.status != "PASS" else "green",
        )
    )


def _decisions(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="FINAL VALIDATED DECISIONS · ONLY FORMAL BUY/SELL AREA")
    narrow = console.width < 100
    columns = (
        ("Ticker", "Action", "Current → Target", "Value", "Reason")
        if narrow
        else (
            "Ticker",
            "Action",
            "Current",
            "Target",
            "Delta",
            "Value",
            "Alpha",
            "Confidence",
            "Risk",
            "Reason",
        )
    )
    for column in columns:
        table.add_column(column, overflow="fold")
    if not result.final_decisions:
        action = "NO_ACTION" if result.actionable else "NOT_ACTIONABLE"
        reason = (
            "Complete certified pipeline produced no rebalance outside the no-trade band"
            if result.actionable
            else "Required stages did not complete; no trading judgment was generated"
        )
        empty = (
            (
                "ALL",
                action,
                "-- → --",
                "--",
                reason,
            )
            if narrow
            else (
                "ALL",
                action,
                "--",
                "--",
                "--",
                "--",
                "--",
                "--",
                "BLOCKED",
                reason,
            )
        )
        table.add_row(*empty)
    for item in result.final_decisions:
        values = (
            (
                item.symbol,
                item.action,
                f"{_percent(item.current_weight)} → {_percent(item.target_weight)}",
                _money(item.estimated_value),
                item.reason,
            )
            if narrow
            else (
                item.symbol,
                item.action,
                _percent(item.current_weight),
                _percent(item.target_weight),
                _signed_percent(item.delta_weight),
                _money(item.estimated_value),
                _signed_percent(item.expected_alpha),
                _percent(item.confidence),
                f"{item.risk_contribution:.3f}",
                item.reason,
            )
        )
        table.add_row(*values)
    console.print(table)


def _rejected(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="REJECTED SIGNALS / GATE BLOCKERS")
    table.add_column("Ticker")
    table.add_column("Rejected by")
    table.add_column("Reason", overflow="fold")
    if not result.rejected_signals:
        table.add_row("--", "--", "None")
    for item in result.rejected_signals:
        table.add_row(item.symbol, item.rejected_by, item.reason)
    console.print(table)


def _execution(result: DailyQuantResult, console: Console) -> None:
    plan = result.execution_plan
    table = Table(title=f"EXECUTION PLAN · {plan.status} · {plan.broker}")
    for column in ("#", "Ticker", "Action", "Est Value", "Qty", "Est Cost", "Earliest"):
        table.add_column(column, overflow="fold")
    if not plan.legs:
        table.add_row("--", "--", "NO EXECUTION", "--", "--", "--", "--")
    for leg in plan.legs:
        table.add_row(
            str(leg.sequence), leg.symbol, leg.action, _money(leg.estimated_value),
            str(leg.estimated_quantity),
            _money(leg.estimated_cost),
            leg.earliest_execution_time.isoformat(),
        )
    console.print(table)
    console.print(
        f"Cash before {_money(plan.estimated_cash_before)}  "
        f"+ Proceeds {_money(plan.estimated_proceeds)}  "
        f"- Buys {_money(plan.estimated_buys)}  - Costs {_money(plan.estimated_cost)}  "
        f"= Cash after {_money(plan.estimated_cash_after)}"
    )


def _benchmark(result: DailyQuantResult, console: Console) -> None:
    table = Table(title="BENCHMARK · SAME PIT DATA CONVENTION AS STRATEGY")
    for column in (
        "Benchmark",
        "Status",
        "Start",
        "End",
        "N",
        "Period Return",
        "Ann Vol",
        "Max DD",
        "Note",
    ):
        table.add_column(column, overflow="fold")
    if not result.benchmarks:
        table.add_row(
            "--", "UNAVAILABLE", "--", "--", "0", "--", "--", "--",
            "No certified comparable sample",
        )
    for item in result.benchmarks:
        table.add_row(
            item.name,
            item.status,
            str(item.start_date or "--"),
            str(item.end_date or "--"),
            str(item.observation_count),
            _signed_percent(item.period_return),
            _percent(item.annualized_volatility),
            _signed_percent(item.max_drawdown),
            item.note,
        )
    console.print(table)
    cost = result.provenance.get("transaction_cost_assumption")
    if isinstance(cost, str) and cost:
        console.print(f"Cost assumption: {cost}")


def _run_certificate(result: DailyQuantResult, console: Console) -> None:
    console.print(
        Panel(
            f"Classification: {result.run_classification}\n"
            f"Run ID: {result.run_id}\n"
            f"Data hash: {result.provenance.get('data_hash', 'UNAVAILABLE')}\n"
            f"Config hash: {result.config_hash}\n"
            f"Models: {', '.join(result.model_versions) or 'UNAVAILABLE'}\n"
            f"Certificate: {result.certificate_path or 'UNAVAILABLE'}",
            title="RUN CERTIFICATE",
            border_style="green" if result.actionable else "red",
        )
    )


def _summary(result: DailyQuantResult, console: Console) -> None:
    buys = sum(item.action in {"BUY", "ADD", "INCREASE"} for item in result.final_decisions)
    sells = sum(item.action in {"SELL", "REDUCE"} for item in result.final_decisions)
    blockers = "; ".join(result.blockers) if result.blockers else "None"
    data_status = next(
        (stage.status.value for stage in result.stages if stage.name == "DATA"),
        "UNKNOWN",
    )
    if not result.actionable:
        valid_analysis = result.diagnostic_analysis_complete
        conclusion = (
            "VALID QUANT ANALYSIS - FORMAL TRADING DECISION UNAVAILABLE"
            if valid_analysis
            else "INVALID / NON-ACTIONABLE QUANT RUN - DO NOT USE FOR TRADING"
        )
        console.print(
            Panel(
                f"Run {result.run_classification}   Pipeline {result.decision_readiness.value}   "
                f"Data {data_status}   Portfolio {result.portfolio.status}   "
                f"Risk {result.risk.status}\n"
                f"Actions 0   Blockers: {blockers}\n\n"
                + conclusion,
                title="TODAY SUMMARY",
                border_style="yellow" if valid_analysis else "red",
            )
        )
        return
    console.print(
        Panel(
            f"Run {result.run_classification}   Pipeline {result.decision_readiness.value}   "
            f"Data {data_status}   "
            f"Portfolio {result.portfolio.status}   Risk {result.risk.status}\n"
            f"Actions {len(result.execution_plan.legs)}   Buy/Add {buys}   Sell/Reduce {sells}   "
            f"Turnover {_percent(result.execution_plan.turnover)}   "
            f"Cash after {_money(result.execution_plan.estimated_cash_after)}\n"
            f"Blockers: {blockers}\n\nMANUAL EXECUTION REQUIRED · CHARLES SCHWAB · NO BROKER API",
            title="TODAY SUMMARY",
            border_style="green" if result.actionable else "red",
        )
    )


def _status_text(status: StageStatus) -> Text:
    style = {
        StageStatus.PASS: "green",
        StageStatus.PASS_DEGRADED: "yellow",
        StageStatus.FAIL_BLOCKING: "red bold",
        StageStatus.NOT_RUN: "dim",
    }[status]
    return Text(status.value, style=style)


def _bar(value: float, width: int = 30) -> str:
    bounded = max(0.0, min(1.0, value))
    filled = round(bounded * width)
    return "█" * filled + "░" * (width - filled) + f" {bounded:.1%}"


def _percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "--"


def _signed_percent(value: float | None) -> str:
    return f"{value:+.2%}" if value is not None else "--"


def _money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "--"


def _number(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "--"


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _item_count(value: object) -> int:
    return len(value) if isinstance(value, (list, tuple, set)) else 0
