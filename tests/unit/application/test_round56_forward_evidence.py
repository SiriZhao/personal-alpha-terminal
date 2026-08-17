from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.application.forward_evidence import (
    AgenticForwardEvidenceLedger,
    HybridCounterfactualRecord,
    QuantCounterfactualRecord,
    SemanticForwardOutcomeRecord,
    SemanticForwardPredictionRecord,
)

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def prediction() -> SemanticForwardPredictionRecord:
    return SemanticForwardPredictionRecord(
        prediction_id="prediction-1",
        observation_id="observation-1",
        decision_timestamp=NOW,
        information_cutoff=NOW,
        security_id="PERM:AAA",
        company_id="company-aaa",
        symbol="AAA",
        symbol_as_of_time=NOW - timedelta(minutes=1),
        quant_score=0.8,
        quant_probability=0.6,
        expected_alpha_value=0.02,
        expected_alpha_semantics="DETERMINISTIC_QUANT_ENGINE_ESTIMATE",
        event_ids=("event-1",),
        event_provenance=({"event_id": "event-1", "content_hash": "hash-1"},),
        llm_provider="fixture",
        llm_model="fixture-v1",
        llm_schema_version="company-thesis-v1",
        prompt_version="company-thesis-v2",
        structured_thesis={"symbol": "AAA"},
        debate_result={"decision": "AGREE"},
        semantic_score=0.7,
        semantic_alpha=0.001,
        shadow_lambda=0.2,
        quant_target_weight=0.04,
        hybrid_target_weight=0.05,
        quant_risk_result={"status": "VALID"},
        hybrid_risk_result={"status": "VALID"},
        data_snapshot_identity={
            "market_data_hash": "data-1",
            "universe_snapshot_id": "universe-1",
        },
        status="SHADOW",
    )


def counterfactuals() -> tuple[QuantCounterfactualRecord, HybridCounterfactualRecord]:
    common = {
        "observation_id": "portfolio-observation-1",
        "decision_timestamp": NOW,
        "information_cutoff": NOW,
        "security_ids": ("PERM:AAA",),
        "universe_identity": "universe-1",
        "evaluation_horizon": "1d|5d|10d|20d",
        "execution_assumptions_hash": "execution-1",
        "transaction_cost_model": "cost-1",
        "slippage_model": "slippage-1",
        "benchmark_convention": "SPY",
        "data_version": "data-1",
        "current_weights": {"PERM:AAA": 0.02},
        "risk_result": {"status": "VALID"},
        "optimizer_result": {"target_weights": {"AAA": 0.04}},
    }
    return (
        QuantCounterfactualRecord(
            counterfactual_id="quant-counterfactual-1",
            target_weights={"PERM:AAA": 0.04},
            **common,
        ),
        HybridCounterfactualRecord(
            counterfactual_id="hybrid-counterfactual-1",
            target_weights={"PERM:AAA": 0.05},
            **common,
        ),
    )


def test_forward_ledger_is_append_only_and_persists_separate_records(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        first = prediction()
        assert ledger.append_prediction(first) is True
        assert ledger.append_prediction(first) is False
        assert ledger.append_prediction(
            first.model_copy(update={"prediction_id": "prediction-rerun"})
        ) is False
        assert len(ledger.records("SEMANTIC_FORWARD_PREDICTION")) == 1

        with pytest.raises(ValueError, match="immutable"):
            ledger.append_prediction(
                first.model_copy(update={"prediction_id": "prediction-1", "semantic_alpha": 0.9})
            )

        quant, hybrid = counterfactuals()
        assert ledger.append_quant_counterfactual(quant) is True
        assert ledger.append_hybrid_counterfactual(hybrid) is True
        assert len(ledger.records("QUANT_COUNTERFACTUAL")) == 1
        assert len(ledger.records("HYBRID_COUNTERFACTUAL")) == 1
        assert ledger.records("QUANT_COUNTERFACTUAL")[0]["observation_id"] == (
            ledger.records("HYBRID_COUNTERFACTUAL")[0]["observation_id"]
        )


def test_outcome_requires_existing_identity_bound_prediction(session_factory) -> None:
    outcome = SemanticForwardOutcomeRecord(
        outcome_id="outcome-1",
        prediction_id="prediction-1",
        observation_id="observation-1",
        decision_timestamp=NOW,
        outcome_timestamp=NOW + timedelta(days=5),
        evaluation_horizon="5d",
        security_id="PERM:AAA",
        symbol_as_of_time=NOW - timedelta(minutes=1),
        quant_net_return=0.01,
        hybrid_net_return=0.012,
        benchmark_return=0.004,
        quant_cost=0.001,
        hybrid_cost=0.0012,
        quant_turnover=0.02,
        hybrid_turnover=0.025,
        quant_drawdown=0.03,
        hybrid_drawdown=0.031,
        data_snapshot_identity={"market_data_hash": "future-data-1"},
        source_identity="forward-bars-provider-v1",
    )
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        with pytest.raises(ValueError, match="unknown prediction"):
            ledger.append_outcome(outcome)
        ledger.append_prediction(prediction())
        assert ledger.append_outcome(outcome) is True
        assert ledger.append_outcome(outcome) is False
        assert len(ledger.records("SEMANTIC_FORWARD_OUTCOME")) == 1

        with pytest.raises(ValueError, match="identity"):
            ledger.append_outcome(
                outcome.model_copy(
                    update={
                        "outcome_id": "outcome-2",
                        "security_id": "PERM:WRONG",
                    }
                )
            )
