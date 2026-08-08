from typing import Any

from personal_alpha_terminal.backtest.schemas import (
    BacktestConfig,
    BacktestResult,
)
from personal_alpha_terminal.reports.schemas import ReportDocument


def render_strategy_report(
    result: BacktestResult,
    config: BacktestConfig,
    *,
    data_sources: tuple[str, ...],
) -> ReportDocument:
    """Render a deterministic strategy report with explicit reliance limits."""

    if not data_sources:
        raise ValueError("strategy report requires explicit data sources")
    evidence_score, evidence_reasons = _evidence_quality(result, config)
    metrics = result.metrics
    executed = sum(item.status == "executed" for item in result.rebalances)
    rejected = sum(item.status == "rejected" for item in result.rebalances)
    lines = [
        f"# Strategy Report - {result.strategy_name}",
        "",
        f"- Market: {result.market}",
        f"- Window: {result.start_date.isoformat()} to {result.end_date.isoformat()}",
        f"- Rebalance frequency: {config.rebalance_frequency}",
        (
            "- Signal timing: session close plus "
            f"{config.decision_delay_minutes} minutes, using only information "
            "available by that cutoff"
        ),
        "- Execution timing: next available portfolio-calendar session open",
        f"- Data fingerprint: `{result.data_fingerprint}`",
        f"- Evidence quality: {evidence_score}/100 (not a success probability)",
        f"- Executed / rejected rebalances: {executed} / {rejected}",
        "",
        "> Historical simulation only. It is not a price forecast, trade instruction, "
        "or evidence that the strategy will remain profitable.",
        "",
        "## Net Performance",
        "",
        "| Metric | Result | Definition |",
        "|---|---:|---|",
        f"| Total return | {metrics.total_return:.2%} | Ending NAV / initial NAV - 1 |",
        (
            f"| Annualized return | {metrics.annualized_return:.2%} | "
            "Geometric, 252-session convention |"
        ),
        (
            f"| Annualized volatility | {metrics.annualized_volatility:.2%} | "
            "Sample standard deviation × sqrt(252) |"
        ),
        f"| Sharpe ratio | {_number(metrics.sharpe_ratio)} | Net daily excess returns |",
        f"| Sortino ratio | {_number(metrics.sortino_ratio)} | Downside deviation |",
        (f"| Maximum drawdown | {metrics.maximum_drawdown:.2%} | Worst peak-to-trough NAV loss |"),
        (
            f"| Holding-period win rate | {_percent(metrics.period_win_rate)} | "
            "Completed rebalance-to-rebalance periods, including breakeven |"
        ),
        (
            f"| Holding-period profit/loss ratio | "
            f"{_number(metrics.period_profit_loss_ratio)} | "
            "Mean winning period / absolute mean losing period |"
        ),
        f"| Total turnover | {metrics.total_turnover:.2f}× NAV | One-way traded notional |",
        (f"| Trading cost | {metrics.total_transaction_cost:,.2f} | Commission + fee + slippage |"),
        "",
        "## Annual Returns",
        "",
        "| Year | Net return |",
        "|---:|---:|",
    ]
    lines.extend(
        f"| {year} | {value:.2%} |" for year, value in sorted(metrics.annual_returns.items())
    )
    strengths, suitable, failures = _strategy_assessment(result)
    lines.extend(["", "## Observed Strengths", ""])
    lines.extend(f"- {item}" for item in strengths)
    lines.extend(["", "## Applicable Conditions", ""])
    lines.extend(f"- {item}" for item in suitable)
    lines.extend(["", "## Risks and Failure Conditions", ""])
    lines.extend(f"- {item}" for item in failures)
    lines.extend(["", "## Evidence Quality Basis", ""])
    lines.extend(f"- {item}" for item in evidence_reasons)
    if result.validation_issues:
        lines.extend(["", "## Data Validation Warnings", ""])
        lines.extend(
            f"- `{item.code}`: {item.message}"
            + (f" (asset {item.asset_id})" if item.asset_id is not None else "")
            for item in result.validation_issues
        )
    methodologies = (
        "Signals are formed after the signal-date close and cannot execute until the "
        "next portfolio-calendar session open.",
        "Every price input carries event_time, available_time, and ingested_time; "
        "strategy history is filtered by available_time at the decision cutoff.",
        "Adjusted OHLC is derived with the daily adjusted-close/raw-close ratio; raw "
        "OHLC remains subject to the selected provider's corporate-action history.",
        "Portfolio positions are marked to adjusted prices; suspended holdings use the "
        "last adjusted close only within the configured staleness limit.",
        "Commission, fees, and slippage are proportional to one-way traded notional and "
        "deducted by solving post-cost NAV before target units are set.",
        "Opening-auction tradability must be explicitly confirmed and order notional "
        "must remain within the configured share of prior-session average dollar volume.",
        "Win rate and profit/loss ratio use pre-rebalance-open to next "
        "pre-rebalance-open completed periods (including the first rebalance cost and "
        "breakeven periods), not individual security round trips.",
    )
    risks = (
        "Survivorship bias remains possible unless the supplied universe includes "
        "delisted and historically eligible securities.",
        "Free-price sources can revise corporate actions and may not represent an "
        "institutionally executable opening auction.",
        "The prior-session ADV limit is a conservative capacity proxy, not an opening "
        "auction queue or nonlinear market-impact model.",
        "Cross-market portfolios require a timezone-aware global calendar and FX ledger; "
        "this engine deliberately enforces one market per run.",
        "Runs are blocked unless a caller supplies a verified trading calendar; the "
        "platform does not infer holidays from price availability.",
        "A strong backtest can result from selection bias, parameter search, or regime "
        "luck and requires locked out-of-sample and manual forward-observation validation.",
    )
    lines.extend(["", "## Data Sources", ""])
    lines.extend(f"- {item}" for item in data_sources)
    lines.extend(["", "## Calculation and Execution Logic", ""])
    lines.extend(f"- {item}" for item in methodologies)
    lines.extend(["", "## Known Limitations", ""])
    lines.extend(f"- {item}" for item in risks)
    return ReportDocument(
        report_type="strategy_backtest",
        as_of_date=result.end_date,
        subject_key=str(result.run_id) if result.run_id is not None else None,
        title=f"Strategy Report - {result.strategy_name}",
        markdown="\n".join(lines),
        data_sources=data_sources,
        methodology=methodologies,
        risk_factors=risks,
    )


def visualization_payload(result: BacktestResult) -> dict[str, Any]:
    """Return chart-ready, bounded data for Dashboard rendering."""

    return {
        "equity_curve": [
            {
                "date": item.trade_date.isoformat(),
                "nav": item.nav,
                "daily_return": item.daily_return,
            }
            for item in result.points
        ],
        "drawdown_curve": [
            {"date": item.trade_date.isoformat(), "drawdown": item.drawdown}
            for item in result.points
        ],
        "annual_returns": [
            {"year": year, "return": value}
            for year, value in sorted(result.metrics.annual_returns.items())
        ],
        "risk_analysis": {
            "annualized_volatility": result.metrics.annualized_volatility,
            "maximum_drawdown": result.metrics.maximum_drawdown,
            "sharpe_ratio": result.metrics.sharpe_ratio,
            "sortino_ratio": result.metrics.sortino_ratio,
            "total_turnover": result.metrics.total_turnover,
            "total_transaction_cost": result.metrics.total_transaction_cost,
        },
    }


def _evidence_quality(
    result: BacktestResult,
    config: BacktestConfig,
) -> tuple[int, tuple[str, ...]]:
    sessions = len(result.points)
    executed = sum(item.status == "executed" for item in result.rebalances)
    score = 25
    score += min(25, sessions // 50 * 5)
    score += min(20, executed * 2)
    if config.require_adjusted_prices:
        score += 10
    if config.total_cost_rate > 0:
        score += 10
    score += max(0, 10 - 2 * len(result.validation_issues))
    score = min(score, 90)
    return score, (
        "25 points: next-session execution, immutable data fingerprint, and "
        "deterministic accounting controls.",
        f"History contribution: {sessions} sessions.",
        f"Rebalance contribution: {executed} executed observations.",
        f"Adjusted prices required: {config.require_adjusted_prices}.",
        f"Explicit round-trip assumptions: {config.total_cost_rate:.4%} per traded notional.",
        f"Validation warnings: {len(result.validation_issues)}.",
        "Score is capped at 90 because a backtest cannot establish future success.",
    )


def _strategy_assessment(
    result: BacktestResult,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    strengths: list[str] = [
        "Rules and rebalance decisions are reproducible from saved inputs and parameters.",
        "Reported returns are net of the configured commission, fee, and slippage.",
    ]
    if result.metrics.total_return > 0:
        strengths.append(
            "The tested sample produced a positive net return; this is an observed "
            "sample fact, not an expected return."
        )
    else:
        strengths.append(
            "The tested sample did not produce a positive net return, preventing a "
            "false-positive profitability claim."
        )
    if result.metrics.maximum_drawdown > -0.20:
        strengths.append("Observed maximum drawdown stayed above -20% in this sample.")
    suitable = [
        "Only markets, universes, and liquidity conditions represented by the input data.",
        "Research use after parameter locking and before a separate manual pilot phase.",
    ]
    if result.strategy_name.startswith("factor_quantile"):
        suitable.append("Broad cross-sections with point-in-time factor coverage.")
    elif result.strategy_name == "event_follow":
        suitable.append("Event datasets with trustworthy occurrence and availability times.")
    elif result.strategy_name == "group_rotation":
        suitable.append("Distinct groups with enough members and stable classification history.")
    elif result.strategy_name == "etf_dynamic_allocation":
        suitable.append("Liquid ETFs with comparable calendars and corporate-action histories.")
    failures = [
        "Performance disappears on locked out-of-sample data or after more conservative costs.",
        "Results depend on current constituents, revised fundamentals, or delisted-name exclusion.",
        "Turnover, opening-auction liquidity, or suspension risk makes modeled fills infeasible.",
        "Parameter changes materially reverse conclusions, indicating instability or overfitting.",
        "Regime, crowding, policy, or market-microstructure changes break the historical relation.",
    ]
    return tuple(strengths), tuple(suitable), tuple(failures)


def _number(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "N/A"


def _percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "N/A"
