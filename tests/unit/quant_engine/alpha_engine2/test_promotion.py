"""ROUND 8: promotion gate and probability challenger tests."""
from __future__ import annotations

from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    ProbabilityVerdict,
    PromotionPolicy,
    PromotionVerdict,
    StrategyMetrics,
    evaluate_probability_challenger,
    evaluate_promotion,
)


def _champion() -> StrategyMetrics:
    return StrategyMetrics(
        oos_net_alpha=0.03,
        oos_sharpe=0.7,
        oos_ir=0.6,
        max_drawdown=0.20,
        annual_turnover=3.0,
        cost_bps=60.0,
        stability=0.7,
        forward_consistency=0.6,
        robustness=0.6,
    )


def _better_challenger() -> StrategyMetrics:
    return StrategyMetrics(
        oos_net_alpha=0.05,
        oos_sharpe=0.9,
        oos_ir=0.8,
        max_drawdown=0.15,
        annual_turnover=2.5,
        cost_bps=55.0,
        stability=0.8,
        forward_consistency=0.7,
        robustness=0.7,
    )


def test_champion_retained_when_challenger_only_slightly_better() -> None:
    champion = _champion()
    slightly = StrategyMetrics(
        oos_net_alpha=0.031,
        oos_sharpe=0.71,
        oos_ir=0.61,
        max_drawdown=0.19,
        annual_turnover=3.0,
        cost_bps=60.0,
        stability=0.70,
        forward_consistency=0.60,
        robustness=0.60,
    )
    evaluation = evaluate_promotion(
        challenger_id="challenger-x",
        champion=champion,
        challenger=slightly,
    )
    assert evaluation.verdict is PromotionVerdict.CLASSICAL_CHAMPION_RETAINED
    assert evaluation.failures


def test_champion_retained_when_metrics_worse() -> None:
    evaluation = evaluate_promotion(
        challenger_id="challenger-y",
        champion=_champion(),
        challenger=StrategyMetrics(
            oos_net_alpha=0.05,
            oos_sharpe=0.9,
            oos_ir=0.8,
            max_drawdown=0.30,  # worse drawdown
            annual_turnover=5.0,  # worse turnover
            cost_bps=120.0,  # worse cost
            stability=0.8,
            forward_consistency=0.7,
            robustness=0.7,
        ),
    )
    assert evaluation.verdict is PromotionVerdict.CLASSICAL_CHAMPION_RETAINED
    assert any("DRAWDOWN" in item for item in evaluation.failures)
    assert any("TURNOVER" in item for item in evaluation.failures)
    assert any("COST" in item for item in evaluation.failures)


def test_challenger_promoted_only_when_all_gates_pass() -> None:
    evaluation = evaluate_promotion(
        challenger_id="challenger-z",
        champion=_champion(),
        challenger=_better_challenger(),
    )
    assert evaluation.verdict is PromotionVerdict.CHALLENGER_PROMOTED
    assert evaluation.failures == ()


def test_promotion_policy_is_pre_fixed_and_bounded() -> None:
    policy = PromotionPolicy()
    assert policy.min_oos_net_alpha == 0.02
    assert policy.min_oos_sharpe == 0.50
    assert policy.max_drawdown == 0.25
    try:
        PromotionPolicy(min_oos_net_alpha=-1.0)
        raise AssertionError("expected invalid policy rejection")
    except ValueError:
        pass


def test_probability_promoted_only_when_all_six_gates_pass() -> None:
    evidence = evaluate_probability_challenger(
        brier_score=0.20,
        baseline_brier_score=0.25,
        roc_auc=0.58,
        oos_classical_net_return=0.01,
        oos_probability_net_return=0.02,
        target_change_count=5,
        cost_delta=0.002,
        stability=0.7,
    )
    assert evidence.promoted is True
    assert evidence.verdict() is ProbabilityVerdict.PROBABILITY_PROMOTED


def test_probability_stays_research_only_when_any_gate_fails() -> None:
    evidence = evaluate_probability_challenger(
        brier_score=0.26,  # worse than baseline -> calibration fails
        baseline_brier_score=0.25,
        roc_auc=0.58,
        oos_classical_net_return=0.01,
        oos_probability_net_return=0.02,
        target_change_count=5,
        cost_delta=0.002,
        stability=0.7,
    )
    assert evidence.promoted is False
    assert evidence.verdict() is ProbabilityVerdict.RESEARCH_ONLY
    # Even with good calibration, no target-weight change blocks promotion.
    no_change = evaluate_probability_challenger(
        brier_score=0.20,
        baseline_brier_score=0.25,
        roc_auc=0.58,
        oos_classical_net_return=0.01,
        oos_probability_net_return=0.02,
        target_change_count=0,
        cost_delta=0.002,
        stability=0.7,
    )
    assert no_change.verdict() is ProbabilityVerdict.RESEARCH_ONLY
