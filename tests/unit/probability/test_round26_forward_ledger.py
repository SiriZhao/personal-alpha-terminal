"""ROUND26 P0: forward probability evidence ledger tests."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from personal_alpha_terminal.probability.forward_ledger import (
    PRIMARY_PRODUCTION_RESEARCH_HORIZON,
    ProbabilityForwardLedger,
    ProbabilityPromotionPolicy,
    build_prediction,
    evaluate_forward_probability,
    outcome_from_prices,
)


def _prediction(tmp_path, ticker: str = "VSTS", cutoff: str = "2026-08-14T20:30:00+00:00"):
    return build_prediction(
        run_id="daily-r1",
        decision_id="decision-r1",
        ticker=ticker,
        decision_cutoff=datetime.fromisoformat(cutoff),
        factor_rank=1,
        base_alpha=0.04,
        raw_probability=None,
        calibrated_probability=None,
        model_id="PROBABILITY_FALLBACK_CLASSICAL",
        model_hash="h1",
        cost_hurdle_bps=5.0,
    )


def test_prediction_created_before_outcome(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    prediction = _prediction(tmp_path)
    ledger.append_prediction(prediction)
    outcome = outcome_from_prices(
        prediction=prediction.document(),
        entry_price=100.0,
        exit_price=103.0,
        benchmark_entry=100.0,
        benchmark_exit=101.0,
        cost_bps=5.0,
        entry_time="2026-08-14T20:30:00+00:00",
        exit_time="2026-09-14T20:30:00+00:00",
        available_at="2026-09-14T20:30:00+00:00",
        data_snapshot_id="s1",
    )
    ledger.append_outcome(outcome)
    assert len(ledger.predictions()) == 1
    assert len(ledger.outcomes()) == 1


def test_prediction_is_immutable_and_hash_linked(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    prediction = _prediction(tmp_path)
    ledger.append_prediction(prediction)
    row = ledger.predictions()[0]
    assert row["immutable_hash"]
    assert row["primary_horizon"] == PRIMARY_PRODUCTION_RESEARCH_HORIZON
    assert row["benchmark"] == "SPY"


def test_outcome_target_hit_uses_net_after_cost(tmp_path) -> None:
    prediction = _prediction(tmp_path)
    # asset +3%, benchmark +1% -> relative +2%, cost 5bps -> net +1.95% > 0
    outcome = outcome_from_prices(
        prediction=prediction.document(),
        entry_price=100.0,
        exit_price=103.0,
        benchmark_entry=100.0,
        benchmark_exit=101.0,
        cost_bps=5.0,
        entry_time="t1",
        exit_time="t2",
        available_at="t2",
        data_snapshot_id="s1",
    )
    assert outcome.target_hit is True
    assert outcome.net_relative_return == pytest.approx(0.0195, abs=1e-9)


def test_outcome_miss_when_cost_swamps_edge(tmp_path) -> None:
    prediction = _prediction(tmp_path)
    outcome = outcome_from_prices(
        prediction=prediction.document(),
        entry_price=100.0,
        exit_price=100.2,
        benchmark_entry=100.0,
        benchmark_exit=100.0,
        cost_bps=50.0,
        entry_time="t1",
        exit_time="t2",
        available_at="t2",
        data_snapshot_id="s1",
    )
    assert outcome.target_hit is False


def test_no_matured_outcomes_is_honest_pass(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    ledger.append_prediction(_prediction(tmp_path))
    report = evaluate_forward_probability(ledger)
    assert report["status"] == "NO_MATURED_OUTCOMES"
    assert report["production_influence"] == 0


def test_evaluation_uses_date_clustered_bootstrap_and_metrics(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    for index, (hit, probability) in enumerate(
        [(1, 0.7), (0, 0.3), (1, 0.6), (0, 0.4)], start=1
    ):
        cutoff = f"2026-08-{index:02d}T20:30:00+00:00"
        prediction = build_prediction(
            run_id=f"r{index}",
            decision_id=f"d{index}",
            ticker=f"T{index}",
            decision_cutoff=datetime.fromisoformat(cutoff),
            factor_rank=1,
            base_alpha=0.03,
            raw_probability=probability,
            calibrated_probability=probability,
            model_id="m",
            model_hash="h",
            cost_hurdle_bps=5.0,
        )
        ledger.append_prediction(prediction)
        outcome = outcome_from_prices(
            prediction=prediction.document(),
            entry_price=100.0,
            exit_price=110.0 if hit else 95.0,
            benchmark_entry=100.0,
            benchmark_exit=101.0,
            cost_bps=5.0,
            entry_time=cutoff,
            exit_time=f"2026-09-{index:02d}T20:30:00+00:00",
            available_at=f"2026-09-{index:02d}T20:30:00+00:00",
            data_snapshot_id="s1",
        )
        ledger.append_outcome(outcome)
    report = evaluate_forward_probability(ledger)
    assert report["status"] == "FORWARD_EVIDENCE_AVAILABLE"
    assert report["row_level_n"] == 4
    assert report["decision_date_n"] == 4
    assert report["bootstrap"] == "decision-date clustered"
    assert math.isfinite(report["brier_score"])
    assert math.isfinite(report["ece_5_buckets"])
    assert report["production_influence"] == 0
    assert report["auto_promote"] is False


def test_promotion_policy_defaults_to_zero_and_human_approval() -> None:
    policy = ProbabilityPromotionPolicy()
    assert policy.production_influence == 0.0
    assert policy.human_approval_required is True
    assert policy.auto_promote is False
    assert any("human approval" in condition for condition in policy.conditions())
    assert any("no future leakage" in condition for condition in policy.conditions())
