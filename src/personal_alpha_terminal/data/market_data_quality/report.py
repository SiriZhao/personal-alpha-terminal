from collections import Counter

from personal_alpha_terminal.data.market_data_quality.schemas import QualityReport


def render_markdown(report: QualityReport, *, run_id: int) -> str:
    sample = report.sample
    sample_count = len(sample.selected) if sample is not None else 0
    segment_counts = (
        Counter(item.segment.value for item in sample.selected) if sample is not None else Counter()
    )
    market_counts = (
        Counter(item.market for item in sample.selected) if sample is not None else Counter()
    )

    lines = [
        "# Personal Alpha Terminal Data Quality Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Generated at (UTC): `{report.generated_at.isoformat()}`",
        f"- Historical scope: `{report.history_start}` to `{report.history_end}`",
        f"- Gate status: **{report.status.value.upper()}**",
        f"- Actual stratified sample: **{sample_count}** instruments",
        "",
        "## Executive conclusion",
        "",
    ]
    if report.status.value == "passed":
        lines.append(
            "The sampled history passed the configured lineage, calendar, completeness, "
            "corporate-action, and continuity gates."
        )
    else:
        lines.append(
            "This database is **not certified for downstream investment research**. "
            "The update/analysis pipeline must remain blocked until the listed blockers "
            "and instrument-level errors are resolved."
        )

    lines.extend(["", "## Universe coverage", ""])
    if not market_counts:
        lines.append("No traceable universe snapshot was available; no sample was fabricated.")
    else:
        lines.extend(
            [
                "| Market | Sample count |",
                "|---|---:|",
                *[f"| {market} | {count} |" for market, count in sorted(market_counts.items())],
                "",
                "| Segment | Sample count |",
                "|---|---:|",
                *[f"| {segment} | {count} |" for segment, count in sorted(segment_counts.items())],
            ]
        )

    lines.extend(["", "## Completeness and anomaly rates", ""])
    missing = (
        "N/A (no verified expected-session denominator)"
        if report.missing_rate is None
        else f"{report.missing_rate:.6%}"
    )
    anomaly = (
        "N/A (no observed-session denominator)"
        if report.anomaly_rate is None
        else f"{report.anomaly_rate:.6%}"
    )
    lines.extend(
        [
            f"- Expected exchange sessions: `{report.expected_sessions}`",
            f"- Observed sessions: `{report.observed_sessions}`",
            f"- Missing rate: `{missing}`",
            f"- Anomaly rate: `{anomaly}`",
            (
                "- Missing sessions are not silently classified as suspension. A verified "
                "trading-status record is required."
            ),
        ]
    )

    lines.extend(["", "## Data lineage", ""])
    if not report.source_counts:
        lines.append("- Price source rows: none")
    else:
        lines.extend(
            f"- Source `{key}`: {value} rows" for key, value in sorted(report.source_counts.items())
        )
    if not report.provider_counts:
        lines.append("- Provider rows: none")
    else:
        lines.extend(
            f"- Provider `{key}`: {value} rows"
            for key, value in sorted(report.provider_counts.items())
        )
    lines.extend(
        [
            "",
            "Every accepted price row must retain `source`, `provider`, `event_time`, "
            "`available_time`, and `ingested_at`. Universe snapshots, exchange sessions, "
            "and corporate actions carry equivalent lineage fields.",
            "",
            "Universe/source policy:",
            "",
            "- A shares: SSE/SZSE official security lists and notices define membership, "
            "board, listing and delisting truth; AKShare is the price adapter.",
            "- US: Nasdaq Trader Symbol Directory/Daily List defines NASDAQ and other-"
            "exchange membership/events; Yahoo Finance is the price source through yfinance.",
            "- Hong Kong: HKEX Full List of Securities and notices define Main Board, ETF "
            "and listing events; Yahoo Finance is the price source through yfinance.",
            "",
            "## Adjustment policy",
            "",
            "| Mode | Permitted use | Prohibited use |",
            "|---|---|---|",
            (
                "| Unadjusted (raw) | execution prices, valuation, corporate-action "
                "checks | total-return measurement without action ledger |"
            ),
            "| Forward adjusted (qfq) | current chart display | point-in-time backtest |",
            (
                "| Backward adjusted (hfq) | long-history comparison and provider "
                "reconciliation | point-in-time backtest and valuation |"
            ),
            "| Provider adjusted total return | source reconciliation | point-in-time backtest |",
            (
                "| Point-in-time total return | backtest, only when built from actions "
                "available at each decision time | current provider history without "
                "vintage/action provenance |"
            ),
            "",
            "Provider qfq/hfq histories can be revised after later corporate actions. They "
            "therefore cannot prove what was known at an earlier rebalance date.",
            "",
            "## Blocking findings",
            "",
        ]
    )
    if report.blockers:
        lines.extend(f"- {item}" for item in report.blockers)
    else:
        lines.append("- None")

    failed = [item for item in report.instrument_results if not item.passed]
    lines.extend(["", "## Instrument failures", ""])
    if not failed:
        lines.append("- None recorded.")
    else:
        lines.extend(
            [
                "| Market | Symbol | Segment | Missing rate | Anomaly rate | First error |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in failed:
            first_error = next(
                (issue.code for issue in item.issues if issue.severity == "error"),
                "unknown",
            )
            lines.append(
                f"| {item.market} | {item.symbol} | {item.segment.value} | "
                f"{item.missing_rate:.4%} | {item.anomaly_rate:.4%} | {first_error} |"
            )

    lines.extend(
        [
            "",
            "## Known limitations",
            "",
            "- A zero missing rate is meaningful only when the exchange-session calendar "
            "and listing/delisting dates are independently sourced and current.",
            "- Split/dividend continuity is not certified without a point-in-time corporate "
            "action ledger; adjusted prices alone are insufficient.",
            "- Yahoo Finance/yfinance and AKShare are research data adapters, not exchange-"
            "licensed audit feeds. Material decisions should be reconciled to a second "
            "independent or licensed source.",
            "- ADR ratio changes, rights issues, symbol changes, board transfers, suspension "
            "status, and delisting cash distributions require explicit event records.",
            "",
            "## Reproduction",
            "",
            "```powershell",
            "python -m personal_alpha_terminal.scripts.market_data_quality "
            "--history-start 2010-01-01 --report DATA_QUALITY_REPORT.md",
            "```",
            "",
            "The random seed and immutable universe snapshot IDs are persisted with the run.",
        ]
    )
    return "\n".join(lines) + "\n"
