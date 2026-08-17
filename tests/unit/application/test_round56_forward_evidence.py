from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.application.forward_evidence import (
    AgenticForwardEvidenceLedger,
    HybridCounterfactualRecord,
    PromotionReason,
    QuantCounterfactualRecord,
    RuntimePromotionPolicy,
    SemanticForwardOutcomeRecord,
    SemanticForwardPredictionRecord,
    evaluate_runtime_promotion,
)

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def prediction() -> SemanticForwardPredictionRecord:
    return SemanticForwardPredictionRecord(
        prediction_id="prediction-1",
        observation_id="observation-1",
        counterfactual_observation_id="portfolio-observation-1",
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
        evidence_origin="REAL_FORWARD",
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
        regime="RISK_ON",
        evidence_origin="REAL_FORWARD",
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


def _seed_promotion_rows(
    ledger: AgenticForwardEvidenceLedger,
    *,
    count: int,
    hybrid_return: float,
    quant_return: float,
    turnover_delta: float = 0.001,
    model_suffix: str = "v1",
    origin: str = "REAL_FORWARD",
    prefix: str = "promote",
) -> None:
    quant, hybrid = counterfactuals()
    portfolio_observation = f"portfolio-observation-{prefix}"
    quant = quant.model_copy(
        update={
            "counterfactual_id": f"quant-counterfactual-{prefix}",
            "observation_id": portfolio_observation,
        }
    )
    hybrid = hybrid.model_copy(
        update={
            "counterfactual_id": f"hybrid-counterfactual-{prefix}",
            "observation_id": portfolio_observation,
        }
    )
    ledger.append_quant_counterfactual(quant)
    ledger.append_hybrid_counterfactual(hybrid)
    for index in range(count):
        decision_timestamp = NOW + timedelta(days=index)
        base_prediction = prediction()
        current = base_prediction.model_copy(
            update={
                "prediction_id": f"prediction-{prefix}-{index}",
                "observation_id": f"observation-{prefix}-{index}",
                "decision_timestamp": decision_timestamp,
                "information_cutoff": decision_timestamp,
                "counterfactual_observation_id": portfolio_observation,
                "llm_model": f"fixture-{model_suffix}",
                "evidence_origin": origin,
                "semantic_score": 1.0 if hybrid_return > quant_return else -1.0,
            }
        )
        ledger.append_prediction(current)
        base_outcome = SemanticForwardOutcomeRecord(
            outcome_id=f"outcome-{prefix}-{index}",
            prediction_id=current.prediction_id,
            observation_id=current.observation_id,
            decision_timestamp=decision_timestamp,
            outcome_timestamp=decision_timestamp + timedelta(days=5),
            evaluation_horizon="5d",
            security_id="PERM:AAA",
            symbol_as_of_time=NOW - timedelta(minutes=1),
            quant_net_return=quant_return,
            hybrid_net_return=hybrid_return,
            benchmark_return=0.001,
            quant_cost=0.001,
            hybrid_cost=0.0011,
            quant_turnover=0.02,
            hybrid_turnover=0.02 + turnover_delta,
            quant_drawdown=0.01,
            hybrid_drawdown=0.011,
            data_snapshot_identity={"market_data_hash": f"future-{index}"},
            source_identity="forward-bars-provider-v1",
            regime="RISK_ON" if index < count // 2 else "RISK_OFF",
            evidence_origin=origin,
        )
        ledger.append_outcome(base_outcome)


def test_runtime_promotion_is_dynamic_and_fail_closed(session_factory) -> None:
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        evaluation = evaluate_runtime_promotion(
            ledger,
            evaluated_at=NOW,
            evaluation_id="promotion-empty",
        )
        assert evaluation.reason_codes == (PromotionReason.NO_FORWARD_EVIDENCE.value,)
        assert evaluation.production_lambda == 0.0

        _seed_promotion_rows(
            ledger,
            count=1,
            hybrid_return=0.009,
            quant_return=0.019,
            origin="TEST",
            prefix="contaminated",
        )
        contaminated = evaluate_runtime_promotion(
            ledger,
            evaluated_at=NOW,
            evaluation_id="promotion-contaminated",
        )
        assert contaminated.reason_codes == (PromotionReason.DATA_CONTAMINATION.value,)
        assert contaminated.real_forward_n == 0
        assert contaminated.production_lambda == 0.0


def test_runtime_promotion_blocks_negative_samples(session_factory) -> None:
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        _seed_promotion_rows(
            ledger,
            count=120,
            hybrid_return=0.009,
            quant_return=0.019,
            prefix="negative",
        )
        negative = evaluate_runtime_promotion(
            ledger,
            evaluated_at=NOW + timedelta(days=130),
            evaluation_id="promotion-negative",
        )
        assert negative.reason_codes == (
            PromotionReason.NEGATIVE_INCREMENTAL_ALPHA.value,
        )
        assert negative.paired_sample_n == 120


def test_runtime_promotion_blocks_high_turnover_samples(session_factory) -> None:
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        _seed_promotion_rows(
            ledger,
            count=120,
            hybrid_return=0.021,
            quant_return=0.01,
            turnover_delta=0.06,
            prefix="turnover",
        )
        turnover = evaluate_runtime_promotion(
            ledger,
            evaluated_at=NOW + timedelta(days=130),
            evaluation_id="promotion-turnover",
        )
        assert turnover.reason_codes == (PromotionReason.TURNOVER_FAILURE.value,)
        assert turnover.production_lambda == 0.0


def test_runtime_promotion_can_only_reach_human_review_eligibility(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        ledger = AgenticForwardEvidenceLedger(session)
        _seed_promotion_rows(
            ledger,
            count=120,
            hybrid_return=0.021,
            quant_return=0.01,
            prefix="eligible",
        )
        evaluation = evaluate_runtime_promotion(
            ledger,
            evaluated_at=NOW + timedelta(days=130),
            evaluation_id="promotion-eligible",
            policy=RuntimePromotionPolicy(bootstrap_draws=1_000),
        )
        assert evaluation.reason_codes == (
            PromotionReason.ELIGIBLE_FOR_PROMOTION_REVIEW.value,
        )
        assert evaluation.promotion_reason == (
            PromotionReason.ELIGIBLE_FOR_PROMOTION_REVIEW.value
        )
        assert evaluation.status == "ELIGIBLE_FOR_PROMOTION_REVIEW"
        assert evaluation.real_forward_n == 120
        assert evaluation.paired_sample_n == 120
        assert evaluation.confidence_interval is not None
        assert evaluation.confidence_interval[0] > 0
        assert evaluation.production_lambda == 0.0
