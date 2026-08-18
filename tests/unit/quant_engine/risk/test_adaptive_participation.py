from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
)
from personal_alpha_terminal.quant_engine.risk.adaptive_participation import (
    AdaptiveParticipationController,
    AdaptiveParticipationInputs,
    ParticipationPolicy,
    ParticipationState,
    run_synthetic_participation_evaluation,
)


def _inputs(**overrides: object) -> AdaptiveParticipationInputs:
    base = AdaptiveParticipationInputs(
        risk_on_probability=0.80,
        neutral_probability=0.10,
        risk_off_probability=0.10,
        regime_confidence=0.90,
        regime_calibrated=True,
        breadth=0.80,
        trend_persistence=0.80,
        reversal_risk=0.10,
        realized_volatility=0.12,
        forecast_volatility=0.12,
        correlation_jump=0.0,
        dispersion=0.30,
        liquidity_score=0.90,
        drawdown=0.0,
        benchmark_drawdown=0.0,
        probability_risk_on=None,
        probability_confidence=0.0,
        llm_risk_on=None,
        llm_confidence=0.0,
        model_disagreement=0.10,
        current_gross=0.40,
        current_beta=0.35,
    )
    return replace(base, **cast(dict[str, Any], overrides))


def test_offensive_participation_stays_inside_existing_limits() -> None:
    constraints = PortfolioConstraints()
    target = AdaptiveParticipationController(constraints).decide(
        _inputs(),
        policy=ParticipationPolicy.DYNAMIC_GROSS,
    )

    assert target.state is ParticipationState.OFFENSIVE
    assert target.desired_gross > 0.40
    assert target.desired_gross <= constraints.maximum_gross_exposure
    assert target.desired_cash >= constraints.minimum_cash_weight
    assert target.desired_gross + target.desired_cash <= 1.000001
    assert target.desired_beta <= constraints.maximum_beta
    assert not target.risk_reduction_only


def test_severe_risk_is_reduction_only() -> None:
    current_gross = 0.82
    current_beta = 0.78
    target = AdaptiveParticipationController().decide(
        _inputs(
            risk_on_probability=0.05,
            neutral_probability=0.10,
            risk_off_probability=0.85,
            realized_volatility=0.70,
            forecast_volatility=0.70,
            liquidity_score=0.10,
            drawdown=-0.25,
            benchmark_drawdown=-0.30,
            current_gross=current_gross,
            current_beta=current_beta,
        ),
        policy=ParticipationPolicy.DYNAMIC_GROSS,
    )

    assert target.state is ParticipationState.DEFENSIVE
    assert target.risk_reduction_only
    assert target.desired_gross <= current_gross + 1e-12
    assert target.desired_beta <= current_beta + 1e-12
    assert target.desired_cash >= 1 - current_gross - 1e-12


def test_formal_challenger_context_is_explicit_and_evidence_gated() -> None:
    inputs = _inputs(
        risk_on_probability=0.60,
        neutral_probability=0.20,
        risk_off_probability=0.20,
        probability_risk_on=0.95,
        probability_confidence=1.0,
        llm_risk_on=0.95,
        llm_confidence=1.0,
    )
    controller = AdaptiveParticipationController()
    shadow = controller.decide(
        inputs,
        policy=ParticipationPolicy.DYNAMIC_GROSS,
    )
    challenger = controller.decide(
        inputs,
        policy=ParticipationPolicy.DYNAMIC_GROSS,
        formal_probability=True,
        formal_llm=True,
    )
    missing_evidence = controller.decide(
        replace(inputs, probability_risk_on=None, llm_risk_on=None),
        policy=ParticipationPolicy.DYNAMIC_GROSS,
        formal_probability=True,
        formal_llm=True,
    )

    assert not shadow.formal_probability_used
    assert not shadow.formal_llm_used
    assert challenger.formal_probability_used
    assert challenger.formal_llm_used
    assert challenger.state is ParticipationState.OFFENSIVE
    assert not missing_evidence.formal_probability_used
    assert not missing_evidence.formal_llm_used


def test_synthetic_evaluation_is_deterministic_and_respects_limits() -> None:
    first = run_synthetic_participation_evaluation(seed=20260818)
    second = run_synthetic_participation_evaluation(seed=20260818)

    assert first == second
    assert len(first) == 10
    by_scenario = {result.scenario: result.policies for result in first}
    for scenario in first:
        assert len(scenario.policies) == len(ParticipationPolicy)
        for metric in scenario.policies:
            assert metric.hard_limit_violations == 0
            assert metric.severe_risk_non_reduction_violations == 0
            assert metric.mean_gross <= 0.90 + 1e-12
            assert metric.mean_cash >= 0.10 - 1e-12
            assert metric.total_cost >= 0.0
    for scenario_name in ("NORMAL_MIXED_MARKET", "STRONG_BULL_MARKET"):
        by_policy = {item.policy: item for item in by_scenario[scenario_name]}
        assert (
            by_policy[ParticipationPolicy.DYNAMIC_GROSS].mean_gross
            >= by_policy[ParticipationPolicy.CURRENT_PRODUCTION].mean_gross
        )
