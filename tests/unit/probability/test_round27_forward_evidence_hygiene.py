"""ROUND27: repeated runs are occurrences, never extra OOS observations."""

from __future__ import annotations

from datetime import datetime

from personal_alpha_terminal.probability.forward_ledger import (
    ProbabilityForwardLedger,
    build_prediction,
    evaluate_forward_probability,
    outcome_from_prices,
)


def _prediction(run_id: str, *, run_type: str = "PRODUCTION_DECISION"):
    return build_prediction(
        run_id=run_id,
        decision_id=f"decision-{run_id}",
        ticker="VSTS",
        decision_cutoff=datetime.fromisoformat("2026-08-14T20:30:00+00:00"),
        factor_rank=1,
        base_alpha=0.04,
        raw_probability=0.6,
        calibrated_probability=0.6,
        model_id="probability-v1",
        model_hash="model-hash",
        cost_hurdle_bps=5.0,
        trade_date="2026-08-17",
        market_data_semantic_hash="market-hash",
        universe_semantic_hash="universe-hash",
        portfolio_predecision_hash="portfolio-hash",
        run_type=run_type,
    )


def test_same_semantic_prediction_deduplicated(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    assert ledger.append_prediction(_prediction("run-1")) is True
    assert ledger.append_prediction(_prediction("run-2")) is False
    assert len(ledger.predictions()) == 1
    assert len(ledger.occurrences_path.read_text(encoding="utf-8").splitlines()) == 2


def test_run_time_is_not_part_of_canonical_prediction_identity(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    first = _prediction("run-1")
    second = _prediction("run-2")
    assert first.created_at == second.created_at  # frozen decision cutoff, not report wall clock
    assert first.canonical_prediction_id == second.canonical_prediction_id
    assert ledger.append_prediction(first) is True
    assert ledger.append_prediction(second) is False


def test_replay_and_debug_do_not_create_prediction(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    assert ledger.append_prediction(_prediction("replay", run_type="REPLAY")) is False
    assert ledger.append_prediction(_prediction("debug", run_type="DEBUG")) is False
    assert ledger.predictions() == ()


def test_occurrence_links_canonical_prediction(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    first = _prediction("run-1")
    ledger.append_prediction(first)
    ledger.append_prediction(_prediction("run-2"))
    index = ledger.write_canonical_index()
    entry = index["canonical_predictions"][0]
    assert entry["canonical_prediction_id"] == first.canonical_prediction_id
    assert entry["occurrence_run_ids"] == ["run-1", "run-2"]


def test_one_outcome_per_canonical_prediction_and_effective_n(tmp_path) -> None:
    ledger = ProbabilityForwardLedger(tmp_path)
    prediction = _prediction("run-1")
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
        data_snapshot_id="snapshot-1",
    )
    assert ledger.append_outcome(outcome) is True
    assert ledger.append_outcome(outcome) is False
    report = evaluate_forward_probability(ledger)
    assert report["matured_canonical_predictions"] == 1
    assert report["effective_sample_size"] == 1
