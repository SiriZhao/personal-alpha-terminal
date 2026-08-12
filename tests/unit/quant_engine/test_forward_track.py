from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_alpha_terminal.quant_engine.forward_track import (
    ForwardOutcome,
    ForwardPrediction,
    append_outcome,
    append_prediction,
    load_forward_ledger,
)


def _prediction() -> ForwardPrediction:
    return ForwardPrediction(
        recommendation_id="rec-1",
        run_id="run-1",
        symbol="AAPL",
        as_of=datetime(2026, 8, 11, 20, 30, tzinfo=UTC),
        decision_time=datetime(2026, 8, 12, 12, tzinfo=UTC),
        target_weight=0.12,
        expected_alpha=0.02,
        probability=0.65,
        risk_contribution=0.3,
        benchmark="SPY",
        data_hash="abc123",
        created_at=datetime(2026, 8, 12, 12, tzinfo=UTC),
    )


def test_forward_ledger_appends_outcome_without_mutating_prediction(tmp_path) -> None:
    path = tmp_path / "forward.jsonl"
    prediction = _prediction()
    append_prediction(prediction, path)
    append_prediction(prediction, path)
    outcome = ForwardOutcome(
        recommendation_id="rec-1",
        observed_at=datetime(2026, 9, 15, 20, 30, tzinfo=UTC),
        observed_price=190.0,
        benchmark_price=550.0,
        realized_return=0.03,
        benchmark_return=0.01,
        realized_benchmark_relative_return=0.02,
        outcome_source="DB_RAW_OHLCV",
    )
    append_outcome(outcome, path)
    predictions, outcomes = load_forward_ledger(path)
    assert predictions["rec-1"].target_weight == 0.12
    assert predictions["rec-1"].probability == 0.65
    assert outcomes["rec-1"].realized_return == 0.03
    with pytest.raises(ValueError, match="unknown prediction"):
        append_outcome(
            ForwardOutcome(
                recommendation_id="missing",
                observed_at=datetime(2026, 9, 15, 20, 30, tzinfo=UTC),
                observed_price=100.0,
                benchmark_price=500.0,
                realized_return=0.0,
                benchmark_return=0.0,
                realized_benchmark_relative_return=0.0,
                outcome_source="TEST",
            ),
            path,
        )
