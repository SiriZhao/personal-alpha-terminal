from personal_alpha_terminal.alpha_discovery.factor_generator import FACTOR_BY_NAME
from personal_alpha_terminal.alpha_discovery.schemas import AlphaDiscoveryResult
from personal_alpha_terminal.reports.schemas import ReportDocument


def render_alpha_research_report(
    result: AlphaDiscoveryResult,
    *,
    data_sources: tuple[str, ...],
) -> ReportDocument:
    """Render a deterministic discovery report without price predictions."""

    if not data_sources:
        raise ValueError("alpha report requires explicit data sources")
    confirmed = [item for item in result.combinations if item.status == "test_confirmed"]
    test_factors = [item for item in result.factor_evaluations if item.split_name == "test"]
    test_factors.sort(
        key=lambda item: (
            item.directional_mean_ic is None,
            -(item.directional_mean_ic or 0.0),
            item.factor_name,
        )
    )
    lines = [
        f"# Alpha Research Report - {result.market}",
        "",
        (f"- Research window: {result.start_date.isoformat()} to {result.end_date.isoformat()}"),
        f"- Forward horizon: {result.horizon_days} market sessions",
        f"- Data fingerprint: `{result.data_fingerprint}`",
        f"- Factors evaluated: {result.tested_factor_count}",
        f"- Combinations evaluated before test reveal: {result.tested_combination_count}",
        f"- Locked-test confirmed candidates: {len(confirmed)}",
        (
            "- Locked-test factors with insufficient evidence: "
            f"{sum(item.directional_mean_ic is None for item in test_factors)}"
        ),
        "",
        "> These are historical research hypotheses, not forecasts, trade signals, "
        "or investment recommendations.",
        "",
        "## Discovery Controls",
        "",
        (
            f"- Train dates: {len(result.split.train_dates)}; validation dates: "
            f"{len(result.split.validation_dates)}; locked test dates: "
            f"{len(result.split.test_dates)}."
        ),
        f"- Purged boundary dates: {len(result.split.purged_dates)}.",
        "- Every combination uses equal-weight, direction-adjusted percentile ranks.",
        "- Training screens factors; validation selects combinations; test is revealed last.",
        "- Benjamini-Hochberg FDR controls factor and combination search multiplicity.",
        "",
        "## Factor IC Results",
        "",
        "| Factor | Scope | Test Rank IC | FDR q-value | Confidence |",
        "|---|---|---:|---:|---:|",
    ]
    for factor_evaluation in test_factors:
        adjusted = (
            f"{factor_evaluation.adjusted_p_value:.4f}"
            if factor_evaluation.adjusted_p_value is not None
            else "N/A"
        )
        lines.append(
            f"| {factor_evaluation.factor_name} | "
            f"{factor_evaluation.evaluation_axis} | "
            f"{_format(factor_evaluation.directional_mean_ic)} | {adjusted} | "
            f"{factor_evaluation.confidence_score}/80 |"
        )
    if not test_factors:
        lines.append("| No factor had sufficient locked-test evidence | — | — | — | 0/80 |")
    lines.extend(["", "## Selected Factor Combinations", ""])
    if result.combinations:
        for combination in result.combinations:
            factors = " + ".join(combination.factors)
            lines.extend(
                [
                    f"### {combination.rank}. {factors}",
                    "",
                    f"- Status: `{combination.status}`",
                    (
                        f"- Directional Rank IC — train "
                        f"{_format(combination.train.directional_mean_ic)}, validation "
                        f"{_format(combination.validation.directional_mean_ic)}, test "
                        f"{_format(combination.test.directional_mean_ic)}"
                    ),
                    (
                        f"- Long-short spread — train "
                        f"{_format_percent(combination.train_long_short_return)}, "
                        f"validation "
                        f"{_format_percent(combination.validation_long_short_return)}, "
                        f"test {_format_percent(combination.test_long_short_return)}"
                    ),
                    (
                        "- Maximum average pairwise factor correlation: "
                        f"{combination.maximum_pairwise_correlation:.3f}"
                    ),
                    f"- Evidence quality: {combination.confidence_score}/80",
                    "- Selection logic:",
                    *[f"  - {reason}" for reason in combination.selection_reasons],
                    "- Invalidation conditions:",
                    "  - Locked-test IC is non-positive or loses FDR significance.",
                    "  - Sign reverses across market regimes or subperiods.",
                    "  - Results disappear after costs, liquidity, and executable-price lag.",
                    "  - Corporate-action or point-in-time fundamental corrections change ranks.",
                    "",
                ]
            )
    else:
        lines.append(
            "No combination passed training and validation FDR/stability gates. "
            "The correct research conclusion is no validated candidate."
        )
    methodologies = (
        "Cross-sectional factors use one Spearman Rank IC per date; dates, not stock rows, "
        "are the statistical samples.",
        "Market-environment factors use one equal-weight market return and one factor value "
        "per date to prevent pseudo-replication.",
        "Financial inputs are visible only after available_at and growth uses one source.",
        "Returns and technical factors use adjusted closes; valuation yields use raw close.",
        "Split boundaries are purged and forward windows are non-overlapping.",
        "Test evidence is diagnostic and cannot retroactively change selection rank.",
    )
    risks = (
        "Close-to-close IC is a research association, not an executable fill-price backtest.",
        "The current database may have survivorship bias and incomplete delisted securities.",
        "Free market and fundamental data can be revised, delayed, or mis-adjusted.",
        "IC significance can decay under regime, crowding, capacity, and cost changes.",
        "Market-environment IC is observational and does not establish causality.",
        "Evidence quality is capped at 80 and is not a forecast probability.",
    )
    lines.extend(["", "## Factor Definitions", ""])
    used_names = sorted({factor for item in result.combinations for factor in item.factors})
    if used_names:
        for factor_name in used_names:
            definition = FACTOR_BY_NAME[factor_name]
            lines.append(
                f"- `{factor_name}`: {definition.description} Formula: `{definition.formula}`."
            )
    else:
        lines.append("- No combination advanced; see the complete registered factor library.")
    lines.extend(["", "## Data Sources", ""])
    lines.extend(f"- {item}" for item in data_sources)
    lines.extend(["", "## Analytical Logic", ""])
    lines.extend(f"- {item}" for item in methodologies)
    lines.extend(["", "## Risks and Known Limitations", ""])
    lines.extend(f"- {item}" for item in risks)
    return ReportDocument(
        report_type="alpha_discovery",
        as_of_date=result.end_date,
        subject_key=str(result.run_id) if result.run_id is not None else None,
        title=f"Alpha Research Report - {result.market}",
        markdown="\n".join(lines),
        data_sources=data_sources,
        methodology=methodologies,
        risk_factors=risks,
    )


def _format(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "N/A"


def _format_percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "N/A"
