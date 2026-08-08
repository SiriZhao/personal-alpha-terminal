from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.intelligence.research import (
    FeatureCondition,
    HypothesisDefinition,
    HypothesisObservation,
    HypothesisStatus,
    HypothesisValidationConfig,
    HypothesisValidationEngine,
    PromotionStatus,
    ResearchBudgetConfig,
    ResearchFeatureStatus,
    ResearchPromotionGate,
    run_synthetic_noise_test,
)
from personal_alpha_terminal.intelligence.schemas import BacktestSafety

CUTOFF = datetime(2021, 1, 1, tzinfo=UTC)
START = date(2020, 1, 1)


def _definition(hypothesis_id: str = "hypothesis-1") -> HypothesisDefinition:
    return HypothesisDefinition(
        hypothesis_id=hypothesis_id,
        description="Preregistered momentum diffusion hypothesis",
        features=(FeatureCondition(feature="leader_momentum", operator=">", threshold=0.08),),
        target="AVGO",
        benchmark="SPY",
        horizon=10,
        creator="fixture-research-agent",
        model_version="fixture-hypothesis-v1",
        discovery_period=(START, START + timedelta(days=29)),
        validation_period=(START + timedelta(days=30), START + timedelta(days=59)),
        test_period=(START + timedelta(days=60), START + timedelta(days=89)),
        created_at=CUTOFF,
        data_cutoff=CUTOFF - timedelta(seconds=1),
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
        status=HypothesisStatus.FORMALIZED,
    )


def _observations(*, leak_at: int | None = None) -> tuple[HypothesisObservation, ...]:
    output: list[HypothesisObservation] = []
    for position in range(90):
        session = START + timedelta(days=position)
        signal = datetime.combine(session, datetime.min.time(), tzinfo=UTC)
        feature_time = signal - timedelta(minutes=1)
        if position == leak_at:
            feature_time = signal + timedelta(minutes=1)
        output.append(
            HypothesisObservation(
                session=session,
                condition_matched=True,
                forward_excess_return=0.010 + (position % 3) * 0.001,
                transaction_cost=0.0005,
                drawdown=-0.02,
                turnover=0.10,
                regime="RISK_ON" if position % 2 else "NEUTRAL",
                signal_time=signal,
                features_available_at=feature_time,
                outcome_available_at=signal + timedelta(days=11),
            )
        )
    return tuple(output)


def test_hypothesis_validation_is_chronological_and_never_auto_promotes() -> None:
    definition = _definition()
    result = HypothesisValidationEngine().validate_many(
        (definition,),
        {definition.hypothesis_id: _observations()},
        evaluation_cutoff=CUTOFF,
        real_data_validated=True,
    )[0]

    assert result.status is HypothesisStatus.VALIDATED
    assert result.feature_status is ResearchFeatureStatus.VALIDATED_RESEARCH_FEATURE
    assert result.oos_sample_size == 30
    assert result.after_cost_effect_size > 0
    review = ResearchPromotionGate().evaluate(result)
    assert review.status is PromotionStatus.ELIGIBLE_FOR_MANUAL_REVIEW
    assert review.requires_manual_approval
    assert ResearchPromotionGate().evaluate(
        result, manual_approval=True
    ).status is PromotionStatus.PRODUCTION_APPROVED


def test_pit_leakage_rejects_otherwise_predictive_hypothesis() -> None:
    definition = _definition()
    result = HypothesisValidationEngine().validate_many(
        (definition,),
        {definition.hypothesis_id: _observations(leak_at=65)},
        evaluation_cutoff=CUTOFF,
        real_data_validated=True,
    )[0]

    assert result.status is HypothesisStatus.REJECTED
    assert result.leakage_detected
    assert any("leakage" in blocker for blocker in result.blockers)


def test_research_budget_blocks_unregistered_search_expansion() -> None:
    engine = HypothesisValidationEngine(
        HypothesisValidationConfig(),
        ResearchBudgetConfig(max_hypotheses_per_run=1),
    )
    definitions = (_definition("h-1"), _definition("h-2"))
    with pytest.raises(RuntimeError, match="budget exceeded"):
        engine.validate_many(
            definitions,
            {item.hypothesis_id: _observations() for item in definitions},
            evaluation_cutoff=CUTOFF,
        )


def test_synthetic_noise_does_not_create_validated_alpha() -> None:
    result = run_synthetic_noise_test(
        hypothesis_count=20,
        observation_count=240,
        random_seed=42,
    )
    assert result.passed
    assert result.validated_hypotheses <= 2
