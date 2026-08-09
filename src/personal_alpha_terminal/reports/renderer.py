from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ConditionalProbabilityStudy,
)
from personal_alpha_terminal.analysis.market_regime.schemas import MarketRegimeResult
from personal_alpha_terminal.application.view_models import MarketIndexSnapshot, StockDetail
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.portfolio.schemas import PortfolioRiskAnalysis
from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.validation.confidence import (
    assess_probability_estimate,
    assess_regime_point,
)


def render_daily_market_report(
    *,
    indices: tuple[MarketIndexSnapshot, ...],
    regime: MarketRegimeResult | None,
    probability: ConditionalProbabilityStudy | None,
    portfolio: PortfolioRiskAnalysis | None,
) -> ReportDocument:
    """Render an auditable report from persisted analytical results only."""

    if not indices:
        raise ValueError("daily report requires at least one market index")
    as_of_date = max(item.date for item in indices)
    sources = tuple(
        sorted(
            {
                f"prices:{item.source}:{item.instrument.market}:{item.instrument.symbol}"
                for item in indices
            }
        )
    )
    lines = [
        f"# Personal Alpha Terminal Daily Report - {as_of_date.isoformat()}",
        "",
        "> Generated only from persisted local data. No price forecast or trade order.",
        "",
        "## Global Market Overview",
        "",
    ]
    for index_snapshot in indices:
        change = (
            f"{index_snapshot.change_pct:+.2%}" if index_snapshot.change_pct is not None else "N/A"
        )
        lines.append(
            f"- {index_snapshot.instrument.symbol}: "
            f"{float(index_snapshot.close):,.2f}; "
            f"daily change {change}; data date {index_snapshot.date.isoformat()}"
        )
    if regime is not None and regime.observations:
        point = regime.observations[-1]
        confidence = assess_regime_point(point)
        probabilities = point.probabilities
        if probabilities is not None:
            regime_output = (
                "- Calibrated Risk-On / Neutral / Risk-Off probability: "
                f"{probabilities['risk_on']:.1%} / "
                f"{probabilities['neutral']:.1%} / "
                f"{probabilities['risk_off']:.1%}"
            )
        else:
            regime_output = (
                "- Market Regime Score (not probability), Risk-On / Neutral / Risk-Off: "
                f"{point.risk_on_score:.1%} / "
                f"{point.neutral_score:.1%} / "
                f"{point.risk_off_score:.1%}"
            )
        lines.extend(
            [
                "",
                "## Market Regime",
                "",
                f"- State: {point.regime}",
                (
                    f"- Evidence quality: {confidence.percent} "
                    f"({confidence.level}; not forecast accuracy)"
                ),
                regime_output,
                (
                    f"- Walk-forward calibration: {regime.calibration.status}; "
                    f"OOS observations {regime.calibration.out_of_sample_count}; "
                    f"Brier Score "
                    f"{regime.calibration.brier_score:.4f}"
                    if regime.calibration.brier_score is not None
                    else "- Walk-forward calibration: score only; Brier Score N/A"
                ),
            ]
        )
    if probability is not None:
        reliable = [item for item in probability.results if item.meets_minimum]
        if reliable:
            lines.extend(["", "## Historical Conditional Evidence", ""])
            for probability_item in reliable[:5]:
                confidence = assess_probability_estimate(probability_item)
                lines.append(
                    f"- {probability_item.target.symbol}, "
                    f"{probability_item.horizon_days}D: "
                    "historical conditional frequency "
                    f"{probability_item.probability:.1%}; "
                    f"evidence quality {confidence.percent}; "
                    f"sample {probability_item.sample_size}"
                )
    if portfolio is not None:
        risk = portfolio.risk
        lines.extend(
            [
                "",
                "## Portfolio Risk",
                "",
                f"- Value: {risk.base_currency} {risk.total_value:,.2f}",
                f"- Annualized volatility: {risk.annualized_volatility:.2%}",
                f"- Maximum drawdown: {risk.max_drawdown:.2%}",
                f"- Beta: {risk.beta:.2f}" if risk.beta is not None else "- Beta: N/A",
            ]
        )
    methodology = (
        "Index changes use adjacent closes from one selected provider series.",
        (
            "Regime state uses causal rolling standardization; raw Softmax output is named "
            "Score, and probability is shown only after a walk-forward Brier gate passes."
        ),
        "Conditional results require minimum samples and non-overlapping event windows.",
        "Portfolio risk replays current weights; it is not realized portfolio history.",
    )
    risks = (
        "The database may not cover every market, delisted security, or corporate action.",
        "Cross-market close times, FX, and exchange holidays affect relationship estimates.",
        "Statistical association is not causality and is not investment advice.",
        "Every evidence-quality score is a data-quality grade, not forecast accuracy.",
    )
    lines.extend(_audit_sections(sources, methodology, risks))
    return ReportDocument(
        report_type="daily_market",
        as_of_date=as_of_date,
        subject_key=None,
        title=f"Personal Alpha Terminal Daily Report - {as_of_date.isoformat()}",
        markdown="\n".join(lines),
        data_sources=sources,
        methodology=methodology,
        risk_factors=risks,
    )


def render_stock_report(detail: StockDetail) -> ReportDocument:
    if not detail.prices:
        raise ValueError("stock report requires price history")
    first = detail.prices[0]
    latest = detail.prices[-1]
    total_return = float(latest.close / first.close - 1) if first.close > 0 else None
    sources = tuple(sorted({f"prices:{item.source}" for item in detail.prices}))
    methodology = (
        "Period return uses the first and last adjusted closes.",
        "The period uses only persisted daily observations for one security.",
        "No future price is extrapolated.",
    )
    risks = (
        "Historical return does not indicate future performance.",
        "Adjusted-history quality depends on upstream corporate-action data.",
        "The report omits news or filings not present in the local database.",
    )
    lines = [
        f"# {detail.instrument.symbol} - {detail.instrument.name}",
        "",
        f"- Market: {detail.instrument.market}",
        f"- Industry: {detail.industry or 'Unclassified'}",
        f"- Data range: {first.date.isoformat()} to {latest.date.isoformat()}",
        (
            f"- Adjusted period return: {total_return:.2%}"
            if total_return is not None
            else "- Adjusted period return: N/A"
        ),
        "",
        "> This report contains no target price or future-price forecast.",
    ]
    lines.extend(_audit_sections(sources, methodology, risks))
    return ReportDocument(
        report_type="stock",
        as_of_date=latest.date,
        subject_key=str(detail.instrument.id),
        title=f"{detail.instrument.symbol} Stock Research Report",
        markdown="\n".join(lines),
        data_sources=sources,
        methodology=methodology,
        risk_factors=risks,
    )


def render_portfolio_report(analysis: PortfolioRiskAnalysis) -> ReportDocument:
    risk = analysis.risk
    sources = (
        "portfolio_positions",
        "prices:selected_consistent_source",
        "fx_rates",
    )
    methodology = (
        "Every position value is translated into the portfolio base currency.",
        "Return and risk replay current weights over aligned historical observations.",
        "Beta is covariance with the benchmark divided by benchmark variance.",
        "Stress loss combines position beta and FX shocks multiplicatively.",
    )
    risks = (
        "Current-weight replay is not the portfolio's realized historical performance.",
        "Static stress tests omit liquidity, volatility, and correlation shocks.",
        "Short positions, leverage, and derivatives are not supported.",
    )
    lines = [
        f"# {risk.portfolio_name} - Portfolio Risk Report",
        "",
        f"- Valuation date: {risk.as_of_date.isoformat()}",
        f"- Value: {risk.base_currency} {risk.total_value:,.2f}",
        f"- Annualized return: {risk.annualized_return:.2%}",
        f"- Annualized volatility: {risk.annualized_volatility:.2%}",
        f"- Maximum drawdown: {risk.max_drawdown:.2%}",
        (
            f"- Sharpe ratio: {risk.sharpe_ratio:.2f}"
            if risk.sharpe_ratio is not None
            else "- Sharpe ratio: N/A"
        ),
        f"- Beta: {risk.beta:.2f}" if risk.beta is not None else "- Beta: N/A",
    ]
    lines.extend(_audit_sections(sources, methodology, risks))
    return ReportDocument(
        report_type="portfolio_risk",
        as_of_date=risk.as_of_date,
        subject_key=str(risk.portfolio_id),
        title=f"{risk.portfolio_name} - Portfolio Risk Report",
        markdown="\n".join(lines),
        data_sources=sources,
        methodology=methodology,
        risk_factors=risks,
    )


def _audit_sections(
    sources: tuple[str, ...],
    methodology: tuple[str, ...],
    risks: tuple[str, ...],
) -> list[str]:
    lines = ["", "## Data Sources", ""]
    lines.extend(f"- {item}" for item in sources)
    lines.extend(["", "## Analytical Logic", ""])
    lines.extend(f"- {item}" for item in methodology)
    lines.extend(["", "## Risk Factors and Known Limitations", ""])
    lines.extend(f"- {item}" for item in risks)
    lines.extend(
        [
            "",
            "---",
            "",
            f"{PRODUCT_DISPLAY_NAME} · Research only · Not investment advice.",
        ]
    )
    return lines
