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
    required = ("pit_universe", "pit_corporate_actions", "pit_total_return", "locked_oos")
    blockers = [
        name
        for name in required
        if certification["capabilities"].get(name) != "PRODUCTION_APPROVED"
    ]
    with AuditBuildLock(root, purpose="phase1-final-exam") as lock:
        output.mkdir(parents=True, exist_ok=True)
        metrics_path = output / "07_METRICS.csv"
        with metrics_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("window", "start", "end", "status", *METRICS),
            )
            writer.writeheader()
            for name, start, end in WINDOWS:
                row = {"window": name, "start": start, "end": end, "status": "BLOCKED"}
                row.update({metric: "N/A" for metric in METRICS})
                writer.writerow(row)
        for filename, fields in (
            ("08_TRADES.csv", ("window", "status", "reason")),
            ("09_DRAWDOWNS.csv", ("window", "status", "reason")),
            ("10_EXPOSURE.csv", ("window", "status", "reason")),
        ):
            with (output / filename).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for name, _start, _end in WINDOWS:
                    writer.writerow(
                        {"window": name, "status": "BLOCKED", "reason": ";".join(blockers)}
                    )
        report = {
            "protocol_version": "phase1-final-exam-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "production_source_hash": production_source_hash(root),
            "status": "BLOCKED" if blockers else "READY_TO_RUN",
            "blockers": blockers,
            "windows": [{"name": n, "start": s, "end": e} for n, s, e in WINDOWS],
            "parameter_mutation_allowed": False,
            "fixture_results_accepted_as_real": False,
        }
        (output / "FINAL_REPORT_CARD.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        lock.verify_unchanged()
    print(json.dumps(report, indent=2))
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
