import csv

from scripts.run_phase1_final_exam import (
    METRICS,
    REGIME_DIAGNOSTICS,
    ROBUSTNESS_SCENARIOS,
    WINDOWS,
    write_blocked_outputs,
)


def test_blocked_exam_outputs_na_without_fabricated_metrics(tmp_path) -> None:
    write_blocked_outputs(tmp_path, ("pit_universe", "pit_total_return"))
    with (tmp_path / "07_METRICS.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(WINDOWS)
    assert all(row[metric] == "N/A" for row in rows for metric in METRICS)
    assert all(row["status"] == "BLOCKED" for row in rows)

    with (tmp_path / "12_ROBUSTNESS_MATRIX.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        robustness = list(csv.DictReader(stream))
    assert {row["scenario"] for row in robustness} == set(ROBUSTNESS_SCENARIOS)
    assert all(row["result"] == "N/A" for row in robustness)

    with (tmp_path / "13_REGIME_CALIBRATION.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        calibration = list(csv.DictReader(stream))
    assert {row["diagnostic"] for row in calibration} == set(REGIME_DIAGNOSTICS)
    assert all(row["value"] == "N/A" for row in calibration)
