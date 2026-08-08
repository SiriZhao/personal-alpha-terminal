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
    _summary(result, console)


def capture_daily_quant_result(result: DailyQuantResult, *, width: int = 120) -> str:
    stream = StringIO()
    console = Console(file=stream, width=width, color_system=None, force_terminal=False)
    render_daily_quant_result(result, console)
    return stream.getvalue()


def _header(result: DailyQuantResult) -> str:
    state = "READY" if result.actionable else "NOT_ACTIONABLE"
    return (
        f"Version {result.version}   Run {result.run_id}\n"
        f"ET/Market session {result.market_session}   Analysis {result.analysis_date}   "
        f"Trade {result.trade_date}\n"
        f"Data through {result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}   "
        f"Duration {result.duration_seconds:.2f}s\n"
        f"QUANT {state}   PORTFOLIO {result.portfolio.status}   "
        f"RISK {result.risk.status}   DECISION {state}   LLM {result.llm_status}"
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
    console.print(
        Panel(
            f"Status {summary.status}   NAV {_money(summary.nav)}   Cash {_money(summary.cash)}   "
            f"Invested {_percent(summary.invested_weight)}   "
            f"Cash weight {_percent(summary.cash_weight)}",
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
    table.add_column("Confidence", justify="right")
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
            _percent(row.confidence),
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
        empty = (
            (
                "ALL",
                "NO_ACTION",
                "-- → --",
                "--",
                "No actionable decision passed every required gate",
            )
            if narrow
            else (
                "ALL",
                "NO_ACTION",
                "--",
                "--",
                "--",
                "--",
                "--",
                "--",
                "BLOCKED",
                "No actionable decision passed every required gate",
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
    table = Table(title="BENCHMARK · SAME PIT DATA CONVENTION")
    for column in ("Benchmark", "Status", "N", "Period Return", "Ann Vol", "Note"):
        table.add_column(column, overflow="fold")
    if not result.benchmarks:
        table.add_row("--", "UNAVAILABLE", "0", "--", "--", "No certified comparable sample")
    for item in result.benchmarks:
        table.add_row(
            item.name,
            item.status,
            str(item.observation_count),
            _signed_percent(item.period_return),
            _percent(item.annualized_volatility),
            item.note,
        )
    console.print(table)


def _summary(result: DailyQuantResult, console: Console) -> None:
    buys = sum(item.action in {"BUY", "ADD", "INCREASE"} for item in result.final_decisions)
    sells = sum(item.action in {"SELL", "REDUCE"} for item in result.final_decisions)
    blockers = "; ".join(result.blockers) if result.blockers else "None"
    data_status = next(
        (stage.status.value for stage in result.stages if stage.name == "DATA"),
        "UNKNOWN",
    )
    console.print(
        Panel(
            f"Pipeline {result.decision_readiness.value}   "
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
        StageStatus.WARN: "yellow",
        StageStatus.FAIL: "red bold",
        StageStatus.SKIPPED: "dim",
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
