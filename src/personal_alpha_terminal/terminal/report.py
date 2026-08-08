from __future__ import annotations

from pathlib import Path

from personal_alpha_terminal.terminal.pipeline import DailyAnalysis


def render_markdown(analysis: DailyAnalysis) -> str:
    session = analysis.market_session
    lines = [
        "# Personal Alpha Terminal - Daily Quant Brief",
        "",
        f"Generated: {analysis.generated_at.isoformat()}",
        f"Trade date: {session.trade_date}",
        f"Market session: {session.session.value}",
        f"Market structure: {session.structure_version.value}",
        "",
        "## System and data",
        "",
        f"- Data safety: **{analysis.data_quality.safety_status.value}**",
        f"- Data quality floor: **{analysis.data_quality.minimum_quality_score:.1f}/100**",
        f"- Model: **{analysis.model_status}**",
        "- Execution: **manual Charles Schwab entry only; no broker API**",
        "",
        "| Provider | Status | Success rate | Latency ms | Last error |",
        "|---|---|---:|---:|---|",
    ]
    for provider_health in analysis.provider_health:
        latency = (
            f"{provider_health.latency_ms:.0f}"
            if provider_health.latency_ms is not None
            else "--"
        )
        lines.append(
            f"| {provider_health.provider} | {provider_health.status} | "
            f"{provider_health.success_rate:.0%} | {latency} | "
            f"{provider_health.last_error or '--'} |"
        )
    lines.extend(
        [
            "",
            "| Symbol | Status | Score | Latest | Missing | Provider | Issues |",
            "|---|---|---:|---|---:|---|---|",
        ]
    )
    for quality_item in analysis.data_quality.symbols:
        lines.append(
            f"| {quality_item.symbol} | {quality_item.safety_status.value} | "
            f"{quality_item.quality_score:.1f} | {quality_item.latest_date or '--'} | "
            f"{quality_item.missing_ratio:.2%} | {quality_item.provider or '--'} | "
            f"{'; '.join(quality_item.issues) or '--'} |"
        )
    lines.extend(
        [
            "",
            "## Market",
            "",
            "| Instrument | Close | Daily change | Latest |",
            "|---|---:|---:|---|",
        ]
    )
    for overview_item in analysis.overview:
        close = (
            f"{overview_item.close:.2f}"
            if overview_item.close is not None
            else "unavailable"
        )
        change = (
            f"{overview_item.daily_change:.2%}"
            if overview_item.daily_change is not None
            else "--"
        )
        lines.append(
            f"| {overview_item.symbol} | {close} | {change} | "
            f"{overview_item.latest_date or '--'} |"
        )
    lines.extend(
        [
            "",
            "## Market Regime Score",
            "",
            f"- **{analysis.regime}** - {analysis.regime_reason}",
            "- This score is not a calibrated probability or a price forecast.",
            "",
            "## Portfolio risk",
            "",
        ]
    )
    if analysis.portfolio_risk is None:
        lines.append("- Insufficient validated prices or no configured real holdings.")
    else:
        risk = analysis.portfolio_risk
        lines.extend(
            [
                f"- Annualized volatility: {risk.annualized_volatility:.2%}",
                f"- Maximum drawdown: {risk.maximum_drawdown:.2%}",
                (
                    f"- Beta: {risk.beta:.2f}"
                    if risk.beta is not None
                    else "- Beta: insufficient sample"
                ),
                f"- Concentration HHI: {risk.concentration_hhi:.3f}",
            ]
        )
    lines.extend(
        [
            "",
            "## Today's Action List",
            "",
            "| Symbol | Action | Current | Target | Confidence | Data | "
            "Feasibility | Session | Probability | Cost |",
            "|---|---|---:|---:|---:|---:|---|---|---:|---:|",
        ]
    )
    for action_item in analysis.actions:
        current = (
            f"{action_item.current_allocation:.2%}"
            if action_item.current_allocation is not None
            else "--"
        )
        target = (
            f"{action_item.target_allocation:.2%}"
            if action_item.target_allocation is not None
            else "--"
        )
        confidence = (
            f"{action_item.confidence:.0%}"
            if action_item.confidence is not None
            else "--"
        )
        probability = (
            f"{action_item.probability:.1%}"
            if action_item.probability is not None
            else "--"
        )
        cost = (
            f"{action_item.estimated_cost_rate:.3%}"
            if action_item.estimated_cost_rate is not None
            else "manual check"
        )
        lines.append(
            f"| {action_item.symbol} | {action_item.action} | {current} | {target} | "
            f"{confidence} | {action_item.data_quality:.1f} | "
            f"{action_item.execution_feasibility} | {action_item.recommended_session} | "
            f"{probability} | {cost} |"
        )
        change = (
            f"{action_item.suggested_change:+.2%}"
            if action_item.suggested_change is not None
            else "--"
        )
        lines.extend(
            [
                "",
                f"### {action_item.symbol} evidence and constraints",
                "",
                f"- Signal: {action_item.signal_summary}",
                f"- Risk: {action_item.risk}",
                f"- Suggested change: {change}",
                f"- Reason codes: {', '.join(action_item.reason_codes)}",
            ]
        )
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in analysis.warnings)
    return "\n".join(lines) + "\n"


def write_daily_report(analysis: DailyAnalysis, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{analysis.market_session.trade_date.isoformat()}_report.md"
    temporary = output.with_suffix(".md.tmp")
    temporary.write_text(render_markdown(analysis), encoding="utf-8")
    temporary.replace(output)
    return output
