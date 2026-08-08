from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.market_regime.diagnostics import (
    RegimePrediction,
    evaluate_regime_operations,
)


def test_regime_diagnostics_report_errors_latency_and_log_loss() -> None:
    start = date(2020, 2, 1)
    actual = ("risk_on", "risk_off", "risk_off", "risk_on", "risk_on")
    predicted = ("risk_on", "risk_on", "risk_off", "risk_off", "risk_on")
    rows = tuple(
        RegimePrediction(
            start + timedelta(days=index),
            prediction,  # type: ignore[arg-type]
            outcome,  # type: ignore[arg-type]
            {
                "risk_on": 0.8 if prediction == "risk_on" else 0.1,
                "neutral": 0.8 if prediction == "neutral" else 0.1,
                "risk_off": 0.8 if prediction == "risk_off" else 0.1,
            },
        )
        for index, (prediction, outcome) in enumerate(zip(predicted, actual, strict=True))
    )
    result = evaluate_regime_operations(rows)
    assert result.probability_metrics_available
    assert result.log_loss == pytest.approx(1.054920, rel=1e-5)
    assert result.false_risk_on == 1
    assert result.risk_off_detection_latency == (1,)
    assert result.reentry_latency == (1,)
    assert result.transition_matrix["risk_on->risk_off"] == 1


def test_score_only_regime_does_not_report_probability_metric() -> None:
    row = RegimePrediction(date(2026, 1, 1), "neutral", "risk_on", None)
    result = evaluate_regime_operations((row,))
    assert not result.probability_metrics_available
    assert result.log_loss is None
