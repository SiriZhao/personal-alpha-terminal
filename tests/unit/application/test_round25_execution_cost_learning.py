"""ROUND25 PHASE 15: realized execution cost observations stay research-only."""

from __future__ import annotations

import pytest

from personal_alpha_terminal.application.execution_cost_learning import (
    MINIMUM_SAMPLES_FOR_RECALIBRATION,
    CostObservation,
    _slippage_bps,
    summarize_cost_observations,
)


def _observation(slippage: float, fee: float = 1.0) -> CostObservation:
    return CostObservation(
        recommendation_id="rec-1",
        symbol="VSTS",
        side="BUY",
        decision_price=100.0,
        planned_quantity=10,
        fill_price=100.0 + slippage / 10_000 * 100.0,
        fill_quantity=10,
        fee=fee,
        slippage_bps=slippage,
        executed_at="2026-08-14T13:35:00+00:00",
    )


def test_buy_slippage_is_positive_when_paying_up() -> None:
    # Buying 1% above the decision price = +100 bps of slippage.
    assert _slippage_bps("BUY", 100.0, 101.0) == pytest.approx(100.0)


def test_sell_slippage_sign_flips() -> None:
    # Selling 1% below the decision price = +100 bps of slippage.
    assert _slippage_bps("SELL", 100.0, 99.0) == pytest.approx(100.0)


def test_zero_decision_price_is_ignored() -> None:
    assert _slippage_bps("BUY", 0.0, 101.0) == 0.0


def test_empty_observations_are_honest() -> None:
    summary = summarize_cost_observations(())
    assert summary["status"] == "NO_REALIZED_EXECUTION_OBSERVATIONS"
    assert summary["production_cost_model_updated"] is False
    assert summary["recalibration_candidate"] is False


def test_small_sample_is_observation_not_recalibration() -> None:
    observations = tuple(_observation(5.0 + index) for index in range(5))
    summary = summarize_cost_observations(observations)
    assert summary["status"] == "REALIZED_EXECUTION_COST_OBSERVATION"
    assert summary["sample_size"] == 5
    assert summary["production_cost_model_updated"] is False
    assert summary["recalibration_candidate"] is False


def test_sufficient_sample_emits_candidate_but_never_updates() -> None:
    observations = tuple(
        _observation(2.0 + index % 7) for index in range(MINIMUM_SAMPLES_FOR_RECALIBRATION)
    )
    summary = summarize_cost_observations(observations)
    assert summary["status"] == "COST_MODEL_RECALIBRATION_CANDIDATE"
    # A candidate is not an update: human approval remains mandatory.
    assert summary["production_cost_model_updated"] is False
    assert summary["recalibration_requires_human_approval"] is True
