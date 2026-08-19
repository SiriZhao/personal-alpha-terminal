"""ROUND 8: shadow production and deflated evidence tests."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scipy.stats import norm

from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    ShadowLedger,
    ShadowOutcome,
    ShadowPrediction,
    deflate_sharpe,
    evaluate_deflated_evidence,
    evaluate_shadow_comparison,
)

DECISION = datetime(2026, 8, 12, 12, tzinfo=UTC)


def _prediction(shadow_id: str, symbol: str, alpha: float) -> ShadowPrediction:
    return ShadowPrediction(
        shadow_id=shadow_id,
        run_id="run-1",
        decision_time=DECISION,
        challenger_id="challenger-a",
        challenger_version="1.0",
        symbol=symbol,
        rank=1,
        expected_alpha=alpha,
        target_weight=0.0,
        recommendation="BUY" if alpha > 0 else "HOLD",
        data_hash="data-1",
        created_at=DECISION,
    )


def test_shadow_ledger_is_append_only_and_immutable(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    prediction = _prediction("shadow-1", "AAPL", 0.03)
    ledger.append_prediction(prediction)
    ledger.append_prediction(prediction)  # identical re-append
    with pytest.raises(ValueError, match="refusing to mutate"):
        ledger.append_prediction(
            ShadowPrediction(
                shadow_id="shadow-1",
                run_id="run-1",
                decision_time=DECISION,
                challenger_id="challenger-a",
                challenger_version="1.0",
                symbol="AAPL",
                rank=1,
                expected_alpha=0.99,  # mutated alpha
                target_weight=0.0,
                recommendation="BUY",
                data_hash="data-1",
                created_at=DECISION,
            )
        )
    predictions, _ = ledger.load()
    assert predictions["shadow-1"].expected_alpha == 0.03


def test_shadow_outcome_requires_known_prediction_and_is_immutable(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    with pytest.raises(ValueError, match="unknown prediction"):
        ledger.append_outcome(
            ShadowOutcome(
                shadow_id="missing",
                observed_at=DECISION,
                realized_return=0.01,
                outcome_source="DB_RAW_OHLCV",
            )
        )
    ledger.append_prediction(_prediction("shadow-1", "AAPL", 0.03))
    ledger.append_outcome(
        ShadowOutcome(
            shadow_id="shadow-1",
            observed_at=DECISION,
            realized_return=0.02,
            outcome_source="DB_RAW_OHLCV",
        )
    )
    with pytest.raises(ValueError, match="refusing to overwrite"):
        ledger.append_outcome(
            ShadowOutcome(
                shadow_id="shadow-1",
                observed_at=DECISION,
                realized_return=0.99,
                outcome_source="DB_RAW_OHLCV",
            )
        )
    _predictions, outcomes = ledger.load()
    assert len(outcomes) == 1


def test_shadow_comparison_requires_minimum_outcomes(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    for index in range(5):
        ledger.append_prediction(_prediction(f"shadow-{index}", f"S{index}", 0.01))
    comparison = evaluate_shadow_comparison(ledger, challenger_id="challenger-a")
    assert comparison.outcome_count == 0
    assert comparison.mean_abs_error is None
    assert comparison.promoted is False


def test_shadow_comparison_accumulates_forward_direction_agreement(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    for index in range(12):
        ledger.append_prediction(_prediction(f"shadow-{index}", f"S{index}", 0.02))
        ledger.append_outcome(
            ShadowOutcome(
                shadow_id=f"shadow-{index}",
                observed_at=DECISION,
                realized_return=0.01,  # positive, matches positive alpha
                outcome_source="DB_RAW_OHLCV",
            )
        )
    comparison = evaluate_shadow_comparison(ledger, challenger_id="challenger-a")
    assert comparison.outcome_count == 12
    assert comparison.direction_agreement == 1.0
    assert comparison.mean_abs_error is not None


def test_deflated_evidence_punishes_many_trials() -> None:
    single = deflate_sharpe(1.5, 1)
    many = deflate_sharpe(1.5, 100)
    assert single == 1.5
    assert many < 1.5


def test_deflated_sharpe_uses_the_documented_expected_maximum_formula() -> None:
    experiments = 100
    euler = 0.5772156649
    expected_max = (
        (1 - euler) * norm.ppf(1 - 1 / experiments)
        + euler * norm.ppf(1 - 1 / (experiments * 2.718281828459045))
    )
    assert deflate_sharpe(2.0, experiments) == pytest.approx(2.0 - expected_max)


def test_deflated_evidence_detects_inflation() -> None:
    evidence = evaluate_deflated_evidence(
        experiments_run=200,
        best_sharpe=1.5,
        grid_sharpes=(1.5, 0.1, -0.2, 1.2, 0.4),
        subperiod_sharpes=(1.5, -0.3, 0.1),
        oos_subperiod_returns=(0.02, -0.01, 0.01),
    )
    # With 200 trials, the deflated Sharpe is near/below zero -> inflated.
    assert evidence.inflated is True
    assert evidence.parameter_instability > 0


def test_deflated_evidence_not_inflated_with_few_trials_and_stable() -> None:
    evidence = evaluate_deflated_evidence(
        experiments_run=1,
        best_sharpe=0.8,
        grid_sharpes=(0.8,),
        subperiod_sharpes=(0.8,),
        oos_subperiod_returns=(0.01, 0.02, 0.01),
    )
    assert evidence.inflated is False
