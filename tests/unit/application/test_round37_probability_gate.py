from __future__ import annotations

from personal_alpha_terminal.application.round37_audit import (
    build_round37_promotion_gate,
)


def test_probability_promotion_gate_stays_research_without_mature_outcomes() -> None:
    calibration = {
        "matured_canonical_predictions": 0,
        "decision_date_n": 0,
    }
    incremental = {"status": "INSUFFICIENT_SAMPLE"}
    gate = build_round37_promotion_gate(calibration, incremental)
    assert gate["verdict"] == "PROBABILITY_FORWARD_SAMPLE_INSUFFICIENT"
    assert gate["production_weight"] == 0.0
