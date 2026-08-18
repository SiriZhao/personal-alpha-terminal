"""ROUND64 adaptive market-participation challenger.

The controller emits bounded preferences only. It does not replace the
portfolio optimizer, risk recovery chain, drift monitor, or manual execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite, sqrt

import numpy as np

from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioConstraints
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    DynamicRiskBudget,
    PortfolioRiskState,
    RegimeRiskInput,
)


class ParticipationPolicy(StrEnum):
    CURRENT_PRODUCTION = "A_CURRENT_PRODUCTION"
    DYNAMIC_GROSS = "B_DYNAMIC_GROSS"
    DYNAMIC_BETA = "C_DYNAMIC_BETA"
    DYNAMIC_CASH = "D_DYNAMIC_CASH"
    CORE_ACTIVE_ALPHA = "E_CORE_PLUS_ACTIVE_ALPHA"
    CONVEX_DEFENSIVE = "F_CONVEX_DEFENSIVE_OVERLAY"


class ParticipationState(StrEnum):
    OFFENSIVE = "OFFENSIVE"
    NEUTRAL = "NEUTRAL"
    DEFENSIVE = "DEFENSIVE"


@dataclass(frozen=True, slots=True)
class AdaptiveParticipationInputs:
    risk_on_probability: float
    neutral_probability: float
    risk_off_probability: float
    regime_confidence: float
    regime_calibrated: bool
    breadth: float
    trend_persistence: float
    reversal_risk: float
    realized_volatility: float
    forecast_volatility: float
    correlation_jump: float | None
    dispersion: float
    liquidity_score: float
    drawdown: float
    benchmark_drawdown: float
    probability_risk_on: float | None
    probability_confidence: float
    llm_risk_on: float | None
    llm_confidence: float
    model_disagreement: float
    current_gross: float
    current_beta: float

    def __post_init__(self) -> None:
        probabilities = (
            self.risk_on_probability,
            self.neutral_probability,
            self.risk_off_probability,
        )
        bounded = (
            self.regime_confidence,
            self.breadth,
            self.trend_persistence,
            self.reversal_risk,
            self.dispersion,
            self.liquidity_score,
            self.probability_confidence,
            self.llm_confidence,
            self.model_disagreement,
            self.current_gross,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in probabilities):
            raise ValueError("participation regime probabilities must be in [0, 1]")
        if abs(sum(probabilities) - 1.0) > 1e-6:
            raise ValueError("participation regime probabilities must sum to one")
        if any(not isfinite(value) or not 0 <= value <= 1 for value in bounded):
            raise ValueError("participation bounded inputs must be in [0, 1]")
        if any(
            not isfinite(value) or value < 0
            for value in (self.realized_volatility, self.forecast_volatility)
        ):
            raise ValueError("participation volatility inputs must be non-negative")
        if not -1 <= self.drawdown <= 0 or not -1 <= self.benchmark_drawdown <= 0:
            raise ValueError("participation drawdowns must be in [-1, 0]")
        if not isfinite(self.current_beta) or self.current_beta < 0:
            raise ValueError("participation current beta must be non-negative")
        for value in (self.probability_risk_on, self.llm_risk_on, self.correlation_jump):
            if value is not None and not isfinite(value):
                raise ValueError("optional participation inputs must be finite")
        if self.probability_risk_on is not None and not 0 <= self.probability_risk_on <= 1:
            raise ValueError("probability risk-on input must be in [0, 1]")
        if self.llm_risk_on is not None and not 0 <= self.llm_risk_on <= 1:
            raise ValueError("LLM risk-on input must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class AdaptiveParticipationTarget:
    policy: ParticipationPolicy
    state: ParticipationState
    desired_gross: float
    desired_beta: float
    desired_cash: float
    volatility_multiplier: float
    turnover_budget: float
    expected_shortfall_proxy: float
    risk_reduction_only: bool
    formal_probability_used: bool
    formal_llm_used: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        bounded = (
            self.desired_gross,
            self.desired_cash,
            self.volatility_multiplier,
            self.turnover_budget,
        )
        if any(not isfinite(value) or value < 0 for value in bounded):
            raise ValueError("participation target values must be finite and non-negative")
        if not isfinite(self.desired_beta) or self.desired_beta < 0:
            raise ValueError("participation target beta must be finite and non-negative")
        if self.desired_gross + self.desired_cash > 1.000001:
            raise ValueError("participation target gross and cash cannot exceed one")
        if self.risk_reduction_only and self.state is not ParticipationState.DEFENSIVE:
            raise ValueError("risk-reduction-only target must be defensive")

    def document(self) -> dict[str, object]:
        return {
            "policy": self.policy.value,
            "state": self.state.value,
            "desired_gross": self.desired_gross,
            "desired_beta": self.desired_beta,
            "desired_cash": self.desired_cash,
            "volatility_multiplier": self.volatility_multiplier,
            "turnover_budget": self.turnover_budget,
            "expected_shortfall_proxy": self.expected_shortfall_proxy,
            "risk_reduction_only": self.risk_reduction_only,
            "formal_probability_used": self.formal_probability_used,
            "formal_llm_used": self.formal_llm_used,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ParticipationPolicyMetrics:
    policy: ParticipationPolicy
    total_return: float
    benchmark_relative_return: float
    annualized_volatility: float
    sharpe: float | None
    maximum_drawdown: float
    expected_shortfall_5pct: float
    upside_capture: float | None
    downside_capture: float | None
    mean_gross: float
    mean_beta: float
    mean_cash: float
    annualized_turnover: float
    total_cost: float
    hard_limit_violations: int
    severe_risk_non_reduction_violations: int


@dataclass(frozen=True, slots=True)
class ParticipationScenarioResult:
    scenario: str
    regime: str
    policies: tuple[ParticipationPolicyMetrics, ...]


@dataclass(slots=True)
class _ParticipationSimulationState:
    current_gross: float = 0.0
    current_beta: float = 0.0
    gross_history: list[float] = field(default_factory=list)
    beta_history: list[float] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)
    turnover: float = 0.0
    cost: float = 0.0
    hard_limit_violations: int = 0
    severe_risk_non_reduction_violations: int = 0


class AdaptiveParticipationController:
    """State-dependent participation preferences using existing risk semantics."""

    def __init__(
        self,
        constraints: PortfolioConstraints | None = None,
        *,
        target_volatility: float | None = None,
    ) -> None:
        self.constraints = constraints or PortfolioConstraints()
        self.target_volatility = target_volatility or self.constraints.target_annualized_volatility
        if self.target_volatility <= 0:
            raise ValueError("adaptive participation target volatility must be positive")
        self._risk_budget = DynamicRiskBudget()

    def decide(
        self,
        inputs: AdaptiveParticipationInputs,
        *,
        policy: ParticipationPolicy,
        formal_probability: bool = False,
        formal_llm: bool = False,
    ) -> AdaptiveParticipationTarget:
        regime = RegimeRiskInput(
            risk_on_probability=inputs.risk_on_probability,
            neutral_probability=inputs.neutral_probability,
            risk_off_probability=inputs.risk_off_probability,
            confidence=inputs.regime_confidence,
            calibrated=inputs.regime_calibrated,
            model_version="adaptive-participation-regime-v1",
        )
        correlation_jump = inputs.correlation_jump
        correlation_valid = correlation_jump is not None
        risk_state = PortfolioRiskState(
            current_drawdown=inputs.drawdown,
            rolling_volatility=inputs.realized_volatility,
            portfolio_beta=inputs.current_beta,
            concentration_hhi=0.0,
            average_correlation=(0.0 if correlation_valid else None),
            baseline_average_correlation=(
                -correlation_jump if correlation_jump is not None else None
            ),
            correlation_status=(
                CorrelationRiskStatus.VALID
                if correlation_valid
                else CorrelationRiskStatus.NOT_VALIDATED
            ),
        )
        budget = self._risk_budget.evaluate(
            regime=regime,
            state=risk_state,
            configured_target_volatility=self.target_volatility,
        )
        probability_used = (
            formal_probability
            and inputs.probability_risk_on is not None
            and inputs.probability_confidence > 0
        )
        llm_used = (
            formal_llm and inputs.llm_risk_on is not None and inputs.llm_confidence > 0
        )
        risk_on = _effective_risk_on(
            inputs,
            formal_probability=probability_used,
            formal_llm=llm_used,
        )
        severe = (
            not budget.allow_new_risk
            or inputs.drawdown <= -0.20
            or inputs.risk_off_probability >= 0.70
            or inputs.realized_volatility >= max(0.45, self.target_volatility * 2.5)
            or inputs.liquidity_score <= 0.20
        )
        state = (
            ParticipationState.DEFENSIVE
            if severe
            else ParticipationState.OFFENSIVE
            if risk_on >= 0.65
            and inputs.breadth >= 0.60
            and inputs.trend_persistence >= 0.60
            and inputs.reversal_risk <= 0.45
            else ParticipationState.NEUTRAL
        )
        capacity = min(
            self.constraints.maximum_gross_exposure,
            1 - self.constraints.minimum_cash_weight,
        )
        base_gross = capacity * budget.gross_exposure_multiplier
        favorable = _favorable_score(inputs, risk_on)
        desired_gross = _policy_gross(
            policy,
            base_gross=base_gross,
            capacity=capacity,
            favorable=favorable,
            state=state,
            current_gross=inputs.current_gross,
        )
        current_cap = max(self.constraints.minimum_beta, inputs.current_beta)
        desired_beta = _policy_beta(
            policy,
            desired_gross=desired_gross,
            current_beta=current_cap,
            max_beta=self.constraints.maximum_beta,
            risk_on=risk_on,
            state=state,
        )
        desired_cash = max(self.constraints.minimum_cash_weight, 1 - desired_gross)
        desired_gross = min(desired_gross, 1 - desired_cash)
        turnover_budget = min(
            self.constraints.maximum_turnover,
            max(0.0, abs(desired_gross - inputs.current_gross) + 0.10),
        )
        risk_reduction_only = state is ParticipationState.DEFENSIVE and severe
        if risk_reduction_only:
            desired_gross = min(desired_gross, inputs.current_gross)
            desired_beta = min(desired_beta, inputs.current_beta)
            desired_cash = max(desired_cash, 1 - inputs.current_gross)
        reasons = list(budget.reasons)
        reasons.append(f"participation_state={state.value}")
        reasons.append(f"favorable_score={favorable:.4f}")
        if probability_used:
            reasons.append("formal_probability_context_used")
        if llm_used:
            reasons.append("formal_llm_context_used")
        if risk_reduction_only:
            reasons.append("severe_risk_reduction_only")
        return AdaptiveParticipationTarget(
            policy=policy,
            state=state,
            desired_gross=_finite_clamp(desired_gross, 0.0, capacity),
            desired_beta=_finite_clamp(
                desired_beta,
                self.constraints.minimum_beta,
                self.constraints.maximum_beta,
            ),
            desired_cash=_finite_clamp(desired_cash, self.constraints.minimum_cash_weight, 1.0),
            volatility_multiplier=budget.volatility_multiplier,
            turnover_budget=turnover_budget,
            expected_shortfall_proxy=_expected_shortfall_proxy(inputs),
            risk_reduction_only=risk_reduction_only,
            formal_probability_used=probability_used,
            formal_llm_used=llm_used,
            reasons=tuple(reasons),
        )


def run_synthetic_participation_evaluation(
    *,
    seed: int = 20260818,
    constraints: PortfolioConstraints | None = None,
) -> tuple[ParticipationScenarioResult, ...]:
    """Evaluate six participation policies on the existing 2099 synthetic market."""

    from personal_alpha_terminal.scenario_simulator.flagship_stress import (
        SCENARIOS,
        _synthetic_market,
    )

    configured = constraints or PortfolioConstraints()
    controller = AdaptiveParticipationController(configured)
    results: list[ParticipationScenarioResult] = []
    for scenario_index, spec in enumerate(SCENARIOS):
        returns, benchmark = _synthetic_market(spec, seed=seed + scenario_index * 1009)
        states = {policy: _ParticipationSimulationState() for policy in ParticipationPolicy}
        benchmark_values: list[float] = []
        start = min(64, len(returns) - 2)
        for index in range(start, len(returns) - 1):
            history = benchmark.iloc[: index + 1]
            market_momentum = float(np.prod(1 + history.tail(21).to_numpy()) - 1)
            market_volatility = float(history.tail(21).std(ddof=1) * sqrt(252))
            market_wealth = float(np.prod(1 + history.to_numpy()))
            market_peak = float(np.maximum.accumulate(np.cumprod(1 + history.to_numpy()))[-1])
            benchmark_drawdown = min(0.0, market_wealth / market_peak - 1)
            row = returns.iloc[index].astype(float)
            breadth = float(np.mean(row.to_numpy() > 0))
            dispersion = float(np.std(row.to_numpy(), ddof=1))
            risk_on, neutral, risk_off = _synthetic_regime(
                market_momentum,
                market_volatility,
                breadth,
            )
            liquidity = _synthetic_liquidity(spec.spread_multiplier)
            benchmark_return = float(benchmark.iloc[index + 1])
            benchmark_values.append(benchmark_return)
            for policy in ParticipationPolicy:
                current = states[policy]
                portfolio_returns = np.asarray(current.returns, dtype=float)
                current_wealth = (
                    float(np.prod(1 + portfolio_returns))
                    if len(portfolio_returns)
                    else 1.0
                )
                current_peak = (
                    float(np.maximum.accumulate(np.cumprod(1 + portfolio_returns))[-1])
                    if len(portfolio_returns)
                    else 1.0
                )
                drawdown = min(0.0, current_wealth / current_peak - 1)
                inputs = AdaptiveParticipationInputs(
                    risk_on_probability=risk_on,
                    neutral_probability=neutral,
                    risk_off_probability=risk_off,
                    regime_confidence=0.75,
                    regime_calibrated=True,
                    breadth=breadth,
                    trend_persistence=_clip(0.5 + 4 * market_momentum, 0, 1),
                    reversal_risk=_clip(0.5 + 6 * max(0.0, -market_momentum), 0, 1),
                    realized_volatility=market_volatility,
                    forecast_volatility=market_volatility,
                    correlation_jump=0.20 if dispersion > 0.025 else 0.0,
                    dispersion=_clip(dispersion * 20, 0, 1),
                    liquidity_score=liquidity,
                    drawdown=drawdown,
                    benchmark_drawdown=benchmark_drawdown,
                    probability_risk_on=None,
                    probability_confidence=0.0,
                    llm_risk_on=None,
                    llm_confidence=0.0,
                    model_disagreement=0.0,
                    current_gross=current.current_gross,
                    current_beta=current.current_beta,
                )
                target = controller.decide(inputs, policy=policy)
                turnover = abs(target.desired_gross - current.current_gross)
                cost = turnover * (0.0007 * spec.spread_multiplier)
                value = target.desired_gross * benchmark_return - cost
                if (
                    target.desired_gross > configured.maximum_gross_exposure + 1e-9
                    or target.desired_cash < configured.minimum_cash_weight - 1e-9
                    or target.desired_beta > configured.maximum_beta + 1e-9
                ):
                    current.hard_limit_violations += 1
                if target.risk_reduction_only and (
                    target.desired_gross > current.current_gross + 1e-9
                    or target.desired_beta > current.current_beta + 1e-9
                    or target.desired_cash < 1 - current.current_gross - 1e-9
                ):
                    current.severe_risk_non_reduction_violations += 1
                current.returns.append(value)
                current.current_gross = target.desired_gross
                current.current_beta = target.desired_beta
                current.gross_history.append(target.desired_gross)
                current.beta_history.append(target.desired_beta)
                current.turnover += turnover
                current.cost += cost

        benchmark_array = np.asarray(benchmark_values, dtype=float)
        policy_metrics: list[ParticipationPolicyMetrics] = []
        for policy in ParticipationPolicy:
            state = states[policy]
            values = np.asarray(state.returns, dtype=float)
            gross_history = np.asarray(state.gross_history, dtype=float)
            beta_history = np.asarray(state.beta_history, dtype=float)
            total = float(np.prod(1 + values) - 1) if len(values) else 0.0
            benchmark_total = (
                float(np.prod(1 + benchmark_array) - 1)
                if len(benchmark_array)
                else 0.0
            )
            annualized_vol = (
                float(values.std(ddof=1) * sqrt(252)) if len(values) > 1 else 0.0
            )
            sharpe = (
                float(values.mean() * sqrt(252) / values.std(ddof=1))
                if len(values) > 1 and values.std(ddof=1) > 0
                else None
            )
            equity = np.cumprod(1 + values) if len(values) else np.asarray([1.0])
            peak = np.maximum.accumulate(equity)
            maximum_drawdown = float(np.max(1 - equity / peak))
            negative = values[values < 0]
            expected_shortfall = (
                float(np.mean(np.sort(negative)[: max(1, int(len(negative) * 0.05))]))
                if len(negative)
                else 0.0
            )
            upside = _capture(values, benchmark_array, positive=True)
            downside = _capture(values, benchmark_array, positive=False)
            policy_metrics.append(
                ParticipationPolicyMetrics(
                    policy=policy,
                    total_return=total,
                    benchmark_relative_return=total - benchmark_total,
                    annualized_volatility=annualized_vol,
                    sharpe=sharpe,
                    maximum_drawdown=maximum_drawdown,
                    expected_shortfall_5pct=expected_shortfall,
                    upside_capture=upside,
                    downside_capture=downside,
                    mean_gross=float(np.mean(gross_history)) if len(gross_history) else 0.0,
                    mean_beta=float(np.mean(beta_history)) if len(beta_history) else 0.0,
                    mean_cash=1 - (
                        float(np.mean(gross_history)) if len(gross_history) else 0.0
                    ),
                    annualized_turnover=(
                        state.turnover * 252 / max(1, len(values))
                    ),
                    total_cost=state.cost,
                    hard_limit_violations=state.hard_limit_violations,
                    severe_risk_non_reduction_violations=(
                        state.severe_risk_non_reduction_violations
                    ),
                )
            )
        results.append(
            ParticipationScenarioResult(
                scenario=spec.name,
                regime=spec.regime,
                policies=tuple(policy_metrics),
            )
        )
    return tuple(results)


def _effective_risk_on(
    inputs: AdaptiveParticipationInputs,
    *,
    formal_probability: bool,
    formal_llm: bool,
) -> float:
    values = [inputs.risk_on_probability]
    weights = [0.70]
    if formal_probability and inputs.probability_risk_on is not None:
        values.append(inputs.probability_risk_on)
        weights.append(0.20 * inputs.probability_confidence)
    if formal_llm and inputs.llm_risk_on is not None:
        values.append(inputs.llm_risk_on)
        weights.append(0.10 * inputs.llm_confidence)
    total = sum(weights)
    return float(sum(value * weight for value, weight in zip(values, weights, strict=True)) / total)


def _favorable_score(inputs: AdaptiveParticipationInputs, risk_on: float) -> float:
    score = (
        0.35 * risk_on
        + 0.20 * inputs.breadth
        + 0.20 * inputs.trend_persistence
        + 0.10 * inputs.liquidity_score
        + 0.10 * (1 - inputs.reversal_risk)
        + 0.05 * (1 - inputs.model_disagreement)
    )
    return _clip(score, 0, 1)


def _policy_gross(
    policy: ParticipationPolicy,
    *,
    base_gross: float,
    capacity: float,
    favorable: float,
    state: ParticipationState,
    current_gross: float,
) -> float:
    if state is ParticipationState.DEFENSIVE:
        return min(base_gross, current_gross)
    if policy is ParticipationPolicy.CURRENT_PRODUCTION:
        return base_gross
    if policy is ParticipationPolicy.DYNAMIC_GROSS:
        return min(capacity, base_gross + (capacity - base_gross) * favorable * 0.70)
    if policy is ParticipationPolicy.DYNAMIC_BETA:
        return min(capacity, base_gross + (capacity - base_gross) * favorable * 0.45)
    if policy is ParticipationPolicy.DYNAMIC_CASH:
        return min(capacity, base_gross + (capacity - base_gross) * favorable * 0.55)
    if policy is ParticipationPolicy.CORE_ACTIVE_ALPHA:
        return min(capacity, max(base_gross, capacity * (0.70 + 0.25 * favorable)))
    convex = favorable * favorable
    return min(capacity, base_gross + (capacity - base_gross) * convex * 0.80)


def _policy_beta(
    policy: ParticipationPolicy,
    *,
    desired_gross: float,
    current_beta: float,
    max_beta: float,
    risk_on: float,
    state: ParticipationState,
) -> float:
    if state is ParticipationState.DEFENSIVE:
        return min(current_beta, desired_gross)
    if policy is ParticipationPolicy.DYNAMIC_BETA:
        return min(max_beta, desired_gross * (0.65 + 0.35 * risk_on))
    if policy is ParticipationPolicy.CORE_ACTIVE_ALPHA:
        return min(max_beta, desired_gross * 0.90)
    return min(max_beta, desired_gross * 0.80)


def _synthetic_regime(
    momentum: float,
    volatility: float,
    breadth: float,
) -> tuple[float, float, float]:
    score = _clip(
        0.50
        + 7 * momentum
        + 0.50 * (breadth - 0.50)
        - 0.50 * max(0, volatility - 0.20),
        0,
        1,
    )
    risk_off = _clip(1 - score, 0, 1)
    neutral = 0.20
    risk_on = max(0.0, score - neutral * risk_off)
    total = risk_on + neutral + risk_off
    return risk_on / total, neutral / total, risk_off / total


def _synthetic_liquidity(spread_multiplier: float) -> float:
    return _clip(1 / max(1.0, spread_multiplier), 0, 1)


def _expected_shortfall_proxy(inputs: AdaptiveParticipationInputs) -> float:
    return max(
        0.0,
        2.33 * max(inputs.forecast_volatility, inputs.realized_volatility)
        + abs(inputs.drawdown)
        + inputs.reversal_risk * 0.10,
    )


def _capture(values: np.ndarray, benchmark: np.ndarray, *, positive: bool) -> float | None:
    mask = benchmark > 0 if positive else benchmark < 0
    if not bool(mask.any()):
        return None
    denominator = float(benchmark[mask].sum())
    return float(values[mask].sum() / denominator) if abs(denominator) > 1e-12 else None


def _finite_clamp(value: float, lower: float, upper: float) -> float:
    if not isfinite(value):
        raise ValueError("adaptive participation value is not finite")
    return max(lower, min(upper, value))


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
