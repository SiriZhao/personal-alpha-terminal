from typing import Any

from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.scenario_simulator.schemas import (
    ScenarioComparison,
    ScenarioResult,
)


def render_scenario_report(result: ScenarioResult) -> ReportDocument:
    """Render an auditable conditional-loss report without predictive language."""

    scenario = result.scenario
    lines = [
        f"# Scenario Report - {scenario.name}",
        "",
        f"- Portfolio: {result.portfolio_name}",
        f"- Portfolio as-of: {result.as_of_date.isoformat()}",
        f"- Scenario type: {scenario.scenario_type}",
        f"- Evidence posture: {scenario.evidence_level}",
        f"- Base value: {result.original_value:,.2f} {result.base_currency}",
        f"- Stressed value: {result.stressed_value:,.2f} {result.base_currency}",
        f"- Estimated impact: {result.pnl_percent:.2%}",
        (f"- Sensitivity interval: {result.pnl_percent_low:.2%} to {result.pnl_percent_high:.2%}"),
        f"- Risk level: **{result.risk_level}**",
        f"- Mapping coverage: {result.mapped_weight:.2%}",
        f"- Evidence quality: {result.confidence_score}/100 (not a probability)",
        f"- Data fingerprint: `{result.data_fingerprint}`",
        "",
        "> Conditional sensitivity estimate only. It is not a forecast, target price, "
        "or instruction to trade.",
        "",
        "## Scenario Assumptions",
        "",
        "| Risk factor | Shock | Unit | Status |",
        "|---|---:|---|---|",
    ]
    lines.extend(
        f"| {item.factor_code} | {item.magnitude:.4f} | {item.unit} | {item.rationale} |"
        for item in scenario.factor_shocks
    )
    lines.extend(
        f"| FX translation: {currency} | {shock:.2%} | decimal_return | "
        "position currency versus portfolio base currency |"
        for currency, shock in sorted(scenario.currency_shocks.items())
    )
    lines.extend(
        [
            "",
            "## Asset Impact",
            "",
            "| Asset | Weight | Factor | FX | Total | Contribution | Value after |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        (
            f"| {item.instrument.symbol} | {item.weight:.2%} | "
            f"{item.factor_return:.2%} | {item.currency_return:.2%} | "
            f"{item.combined_return:.2%} | {item.contribution:.2%} | "
            f"{item.stressed_value:,.2f} |"
        )
        for item in result.impacts
    )
    lines.extend(["", "## Risk Interpretation", ""])
    largest = sorted(result.impacts, key=lambda item: item.contribution)[:3]
    if largest:
        lines.append(
            "- Largest negative contributors: "
            + ", ".join(f"{item.instrument.symbol} ({item.contribution:.2%})" for item in largest)
            + "."
        )
    lines.extend(
        [
            (
                f"- {result.uncovered_weight:.2%} of portfolio value has no exposure "
                "mapping to the shocked factors."
            ),
            (
                "- The reported interval varies sensitivity coefficients only; it does "
                "not cover liquidity gaps, volatility feedback, correlation breaks, or "
                "management responses."
            ),
        ]
    )
    if result.confidence_score < 60:
        lines.append(
            "- Required next action: re-underwrite factor mappings and scenario "
            "calibration before using this result for a portfolio decision."
        )
    else:
        lines.append(
            "- Conditional action rule: compare the stressed loss with the portfolio "
            "risk budget; sizing or hedging decisions remain a separate workflow."
        )
    if result.warnings:
        lines.extend(["", "## Validation Warnings", ""])
        lines.extend(f"- {item}" for item in result.warnings)
    methodology = (
        "Each asset factor return is the sum of explicit sensitivity times normalized "
        "factor shock.",
        "Rate shocks are expressed in basis points and normalized to 100bp units.",
        "Position-currency appreciation versus the portfolio base currency is applied "
        "multiplicatively after the asset factor return.",
        "Asset losses are floored at -100%; gains are not artificially capped.",
        "Portfolio impact is the current-value-weighted sum of position returns; cash "
        "is unchanged.",
        "Sensitivity intervals use mapping low/high coefficients and do not represent "
        "statistical confidence intervals unless the mapping source explicitly does.",
    )
    risks = (
        "Linear sensitivities can fail under large shocks, changing correlations, "
        "volatility spikes, liquidity gaps, or nonlinear derivative payoffs.",
        "Illustrative built-in historical proxies are not exact historical replays and "
        "must be recalibrated from verified series.",
        "An unmapped asset is assumed unchanged, which understates risk; uncovered "
        "weight is shown prominently.",
        "Dollar-index sensitivity is an economic factor and is distinct from direct FX "
        "translation of non-base-currency holdings.",
        "Scenario outputs are conditional model estimates, not probabilities or predictions.",
    )
    lines.extend(["", "## Data Sources and Assumption Labels", ""])
    lines.extend(f"- {item}" for item in scenario.data_sources)
    lines.extend(["", "## Calculation Logic", ""])
    lines.extend(f"- {item}" for item in methodology)
    lines.extend(["", "## Known Limitations", ""])
    lines.extend(f"- {item}" for item in risks)
    return ReportDocument(
        report_type="portfolio_scenario",
        as_of_date=result.as_of_date,
        subject_key=str(result.run_id) if result.run_id is not None else None,
        title=f"Scenario Report - {scenario.name}",
        markdown="\n".join(lines),
        data_sources=scenario.data_sources,
        methodology=methodology,
        risk_factors=risks,
    )


def visualization_payload(result: ScenarioResult) -> dict[str, Any]:
    """Chart-ready risk map and asset sensitivity data."""

    return {
        "risk_map": [
            {
                "asset": item.instrument.symbol,
                "weight": item.weight,
                "estimated_return": item.combined_return,
                "contribution": item.contribution,
                "mapped": item.mapped,
            }
            for item in sorted(
                result.impacts,
                key=lambda value: value.contribution,
            )
        ],
        "asset_sensitivity": [
            {
                "asset": impact.instrument.symbol,
                "factor": factor.factor_code,
                "sensitivity": factor.sensitivity,
                "shock": factor.normalized_shock,
                "return_contribution": factor.contribution,
                "confidence_score": factor.confidence_score,
            }
            for impact in result.impacts
            for factor in impact.factor_contributions
        ],
        "portfolio_summary": {
            "scenario": result.scenario.name,
            "pnl_percent": result.pnl_percent,
            "pnl_percent_low": result.pnl_percent_low,
            "pnl_percent_high": result.pnl_percent_high,
            "risk_level": result.risk_level,
            "mapped_weight": result.mapped_weight,
            "confidence_score": result.confidence_score,
        },
    }


def comparison_payload(comparison: ScenarioComparison) -> dict[str, Any]:
    """Chart-ready scenario comparison with a shared zero baseline."""

    return {
        "portfolio_id": comparison.portfolio_id,
        "as_of_date": comparison.as_of_date.isoformat(),
        "scenarios": [
            {
                "scenario": item.scenario.name,
                "pnl_percent": item.pnl_percent,
                "pnl_percent_low": item.pnl_percent_low,
                "pnl_percent_high": item.pnl_percent_high,
                "risk_level": item.risk_level,
                "confidence_score": item.confidence_score,
            }
            for item in comparison.results
        ],
    }
