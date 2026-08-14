"""ROUND19 deterministic stress exam tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_alpha_terminal.scenario_simulator.exam import (
    SCENARIOS,
    run_stress_exam,
    write_stress_exam_summary,
)


def test_stress_exam_is_deterministic_and_has_six_scenarios() -> None:
    first = run_stress_exam()
    second = run_stress_exam()
    assert first.exam_id == second.exam_id
    assert {item.scenario for item in first.scenarios} == {item.code for item in SCENARIOS}


def test_stress_exam_preserves_long_only_and_caps() -> None:
    summary = run_stress_exam()
    for scenario in summary.scenarios:
        assert not scenario.risk_violations
        assert scenario.largest_position_max <= 0.15 + 1e-12
        assert scenario.gross_exposure_mean <= 1.0 + 1e-12
        assert scenario.final_gross_exposure <= 1.0 + 1e-12


def test_stress_exam_has_no_fixed_cardinality_cap_for_25_symbols() -> None:
    symbols = ("SPY", *(f"S{index:02d}" for index in range(1, 25)))
    summary = run_stress_exam(symbols=symbols)
    assert all("MAX_HOLDINGS_VIOLATION" not in item.risk_violations for item in summary.scenarios)
    assert all(item.largest_position_max <= 0.15 + 1e-12 for item in summary.scenarios)
    assert all(item.gross_exposure_mean <= 1.0 + 1e-12 for item in summary.scenarios)


def test_stress_exam_classification_is_pass_with_warnings() -> None:
    summary = run_stress_exam()
    assert summary.classification == "STRESS_EXAM_PASS_WITH_WARNINGS"
    assert "SYNTHETIC_ONLY" in summary.warnings
    assert "NOT_ALPHA_CERTIFICATION" in summary.warnings
    assert not summary.critical_failures


def test_stress_exam_summary_is_immutable(tmp_path: Path) -> None:
    summary = run_stress_exam()
    path = tmp_path / "stress_exam_summary.json"
    write_stress_exam_summary(summary, path)
    write_stress_exam_summary(summary, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["synthetic_only"] is True
    assert document["not_historical_backtest"] is True
    with pytest.raises(FileExistsError):
        write_stress_exam_summary(summary, path)
        write_stress_exam_summary(summary, path)
        from dataclasses import replace

        write_stress_exam_summary(replace(summary, seed=1), path)
