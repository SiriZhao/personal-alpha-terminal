from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.core.audit_lock import AuditBuildLock, production_source_hash

WINDOWS = (
    ("great_bear", "2007-10-09", "2009-03-09"),
    ("dot_com_reference", "2000-03-24", "2002-10-09"),
    ("bear_2022", "2022-01-03", "2022-10-12"),
    ("q4_2018", "2018-10-01", "2018-12-24"),
    ("sideways", "2015-01-02", "2016-12-30"),
    ("bull_2017", "2017-01-03", "2017-12-29"),
    ("bull_rotation_2023_2024", "2023-01-03", "2024-12-31"),
    ("crash_v", "2020-02-19", "2020-08-31"),
)

METRICS = (
    "total_return", "annualized_return", "excess_return", "max_drawdown",
    "drawdown_duration", "volatility", "sharpe", "sortino", "calmar", "cvar",
    "beta", "correlation", "up_capture", "down_capture", "gross_exposure", "cash",
    "turnover", "trades", "holding_period", "cost_drag", "regime_switches",
    "risk_reduction", "exit_latency", "re_entry_latency", "attribution",
)

BENCHMARKS = (
    ("SPY", "PRIMARY_TRADABLE_TOTAL_RETURN_PROXY"),
    ("QQQ", "SECONDARY_GROWTH_BENCHMARK_PROXY"),
)

ROBUSTNESS_SCENARIOS = (
    "rolling_3_year",
    "rolling_5_year",
    "walk_forward",
    "remove_top_contributor",
    "exclude_mega_cap",
    "cost_x2",
    "execution_delay_plus_1_session",
    "rebalance_frequency_minus_20pct",
    "rebalance_frequency_plus_20pct",
    "parameters_minus_20pct",
    "parameters_minus_10pct",
    "parameters_plus_10pct",
    "parameters_plus_20pct",
)

REGIME_DIAGNOSTICS = (
    "brier",
    "log_loss",
    "baseline_comparison",
    "transition_matrix",
    "false_risk_off",
    "false_risk_on",
    "whipsaw_count",
    "risk_off_detection_latency",
    "re_entry_latency",
    "momentum_crash_protection",
    "v_recovery_lag",
    "opportunity_cost",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the immutable Phase I quant exam")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    default_output = root / "docs" / "reports" / "validation" / "phase1_exam"
    output = (arguments.output or default_output).resolve()
    certification = json.loads(
        (root / "docs" / "development" / "DATA_CERTIFICATION_STATUS.json").read_text(
            encoding="utf-8"
        )
    )
    # The final exam *creates* locked-OOS evidence; it must not require that result
    # as an input. Parameters are frozen by the ExperimentRegistry/source lock.
    required = ("pit_universe", "pit_corporate_actions", "pit_total_return")
    blockers = [
        name
        for name in required
        if certification["capabilities"].get(name) != "PRODUCTION_APPROVED"
    ]
    with AuditBuildLock(root, purpose="phase1-final-exam") as lock:
        output.mkdir(parents=True, exist_ok=True)
        if blockers:
            write_blocked_outputs(output, tuple(blockers))
        report = {
            "protocol_version": "phase1-final-exam-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "production_source_hash": production_source_hash(root),
            "status": "BLOCKED" if blockers else "READY_TO_RUN",
            "blockers": blockers,
            "windows": [{"name": n, "start": s, "end": e} for n, s, e in WINDOWS],
            "parameter_mutation_allowed": False,
            "locked_oos_is_exam_output_not_prerequisite": True,
            "fixture_results_accepted_as_real": False,
        }
        _write_text_atomic(output / "FINAL_REPORT_CARD.json", json.dumps(report, indent=2))
        lock.verify_unchanged()
    print(json.dumps(report, indent=2))
    return 2 if blockers else 0


def write_blocked_outputs(output: Path, blockers: tuple[str, ...]) -> None:
    reason = ";".join(blockers)
    metric_rows: list[dict[str, str]] = []
    for name, start, end in WINDOWS:
        row = {"window": name, "start": start, "end": end, "status": "BLOCKED"}
        row.update({metric: "N/A" for metric in METRICS})
        metric_rows.append(row)
    _write_csv_atomic(
        output / "07_METRICS.csv",
        ("window", "start", "end", "status", *METRICS),
        metric_rows,
    )
    for filename in ("08_TRADES.csv", "09_DRAWDOWNS.csv", "10_EXPOSURE.csv"):
        _write_csv_atomic(
            output / filename,
            ("window", "status", "reason"),
            [
                {"window": name, "status": "BLOCKED", "reason": reason}
                for name, _start, _end in WINDOWS
            ],
        )
    _write_csv_atomic(
        output / "11_BENCHMARK_COMPARISON.csv",
        ("window", "benchmark", "definition", "status", "return", "reason"),
        [
            {
                "window": window,
                "benchmark": benchmark,
                "definition": definition,
                "status": "BLOCKED",
                "return": "N/A",
                "reason": reason,
            }
            for window, _start, _end in WINDOWS
            for benchmark, definition in BENCHMARKS
        ],
    )
    _write_csv_atomic(
        output / "12_ROBUSTNESS_MATRIX.csv",
        ("scenario", "status", "result", "reason"),
        [
            {"scenario": scenario, "status": "BLOCKED", "result": "N/A", "reason": reason}
            for scenario in ROBUSTNESS_SCENARIOS
        ],
    )
    _write_csv_atomic(
        output / "13_REGIME_CALIBRATION.csv",
        ("diagnostic", "status", "value", "reason"),
        [
            {"diagnostic": diagnostic, "status": "BLOCKED", "value": "N/A", "reason": reason}
            for diagnostic in REGIME_DIAGNOSTICS
        ],
    )


def _write_csv_atomic(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, str]],
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
