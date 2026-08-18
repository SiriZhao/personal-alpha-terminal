"""ROUND61 deterministic alpha and market-participation root-cause attribution.

All paths use the synthetic 2099 flagship market. A decision at session ``t``
only consumes observations through ``t`` and is evaluated from ``t + 1``.
The module is diagnostic-only and does not alter production parameters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from math import isfinite, sqrt
from typing import Any

import numpy as np

from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
    PortfolioOptimizationStage,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    portfolio_volatility,
)
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyAlphaResult,
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.scenario_simulator.flagship_stress import (
    DEFAULT_SEED,
    INITIAL_WEIGHTS,
    REBALANCE_SESSIONS,
    SCENARIOS,
    SECTOR_BY_SYMBOL,
    SYMBOLS,
    WARMUP_SESSIONS,
    SyntheticScenarioSpec,
    _authorization,
    _decision_time,
    _factor_metadata,
    _portfolio_risk_state,
    _price_frame,
    _risk_metadata,
    _synthetic_market,
)

ROUND61_VERSION = "round61-participation-attribution-v1"

CURRENT_POLICY = "A_CURRENT_PRODUCTION"
EQUAL_WEIGHT = "B_SAME_SELECTION_EQUAL_WEIGHT"
NO_DYNAMIC_RISK = "C_NO_DYNAMIC_RISK_SCALING"
BENCHMARK_BETA = "D_BENCHMARK_EQUIVALENT_BETA"
MAXIMUM_GROSS = "E_MAXIMUM_FEASIBLE_GROSS"
ALPHA_NO_OPTIMIZER = "F_ALPHA_WITHOUT_OPTIMIZER"
NO_TRANSACTION_COST = "G_OPTIMIZER_WITHOUT_TRANSACTION_COST"
PURE_MOMENTUM = "H_PURE_MOMENTUM"
PURE_TREND = "I_PURE_TREND"
PURE_LOW_VOL = "J_PURE_LOW_VOL"
SPY_BENCHMARK = "K_SPY_BENCHMARK"
QQQ_BENCHMARK = "L_QQQ_BENCHMARK"
BROAD_EQUAL_WEIGHT = "M_BROAD_ELIGIBLE_EQUAL_WEIGHT"
PRE_ROUND60 = "N_PRE_ROUND60_BLOCKED_BEHAVIOR"
DAILY_ALPHA = "O_DAILY_ALPHA_NO_OPTIMIZER"

POLICIES = (
    CURRENT_POLICY,
    EQUAL_WEIGHT,
    NO_DYNAMIC_RISK,
    BENCHMARK_BETA,
    MAXIMUM_GROSS,
    ALPHA_NO_OPTIMIZER,
    NO_TRANSACTION_COST,
    PURE_MOMENTUM,
    PURE_TREND,
    PURE_LOW_VOL,
    SPY_BENCHMARK,
    QQQ_BENCHMARK,
    BROAD_EQUAL_WEIGHT,
    PRE_ROUND60,
    DAILY_ALPHA,
)


@dataclass(slots=True)
class _PolicyState:
    weights: dict[str, float]
    pending_cost: float = 0.0
    turnover: float = 0.0
    returns: list[float] | None = None
    gross: list[float] | None = None
    beta: list[float] | None = None
    volatility: list[float] | None = None

    def __post_init__(self) -> None:
        self.returns = [] if self.returns is None else self.returns
        self.gross = [] if self.gross is None else self.gross
        self.beta = [] if self.beta is None else self.beta
        self.volatility = [] if self.volatility is None else self.volatility


@dataclass(frozen=True, slots=True)
class ParticipationStep:
    scenario: str
    session: str
    portfolio_return: float
    benchmark_return: float
    gross_exposure: float
    net_exposure: float
    cash_weight: float
    beta: float
    volatility: float
    selection_return: float
    stock_selection_return: float
    sector_allocation_return: float
    exposure_drag: float
    cash_drag: float
    transaction_cost_drag: float
    residual_return: float
    recovery_stage: str


@dataclass(frozen=True, slots=True)
class PolicyMetrics:
    policy: str
    total_return: float
    arithmetic_return: float
    benchmark_relative_return: float
    annualized_volatility: float
    mean_gross: float
    mean_cash: float
    mean_beta: float
    upside_capture: float | None
    downside_capture: float | None
    participation_gap: float | None
    turnover_l1: float


@dataclass(frozen=True, slots=True)
class ScenarioAttribution:
    scenario: str
    regime: str
    policies: tuple[PolicyMetrics, ...]
    active_return_arithmetic: float
    stock_selection: float
    sector_allocation: float
    exposure_drag: float
    transaction_cost_drag: float
    residual: float
    primary_count: int
    recovery_count: int
    blocked_count: int
    binding_constraints: dict[str, int]
    steps: tuple[ParticipationStep, ...]


@dataclass(frozen=True, slots=True)
class Round61AttributionReport:
    version: str
    seed: int
    scenarios: tuple[ScenarioAttribution, ...]
    ranked_root_causes: tuple[tuple[str, float], ...]
    maximum_absolute_residual: float
    synthetic_only: bool = True
    not_alpha_certification: bool = True

    def document(self) -> dict[str, Any]:
        return asdict(self)


def _capture_ratio(portfolio: np.ndarray, benchmark: np.ndarray, *, positive: bool) -> float | None:
    mask = benchmark > 0 if positive else benchmark < 0
    denominator = float(benchmark[mask].sum())
    if not np.any(mask) or abs(denominator) <= 1e-12:
        return None
    return float(portfolio[mask].sum() / denominator)


def _policy_metrics(
    name: str,
    state: _PolicyState,
    benchmark: np.ndarray,
) -> PolicyMetrics:
    assert state.returns is not None
    assert state.gross is not None
    assert state.beta is not None
    values = np.asarray(state.returns, dtype=float)
    wealth = float(np.prod(1 + values) - 1)
    annualized_volatility = (
        float(np.std(values, ddof=1) * sqrt(252)) if len(values) > 1 else 0.0
    )
    upside = _capture_ratio(values, benchmark, positive=True)
    downside = _capture_ratio(values, benchmark, positive=False)
    return PolicyMetrics(
        policy=name,
        total_return=wealth,
        arithmetic_return=float(values.sum()),
        benchmark_relative_return=wealth - float(np.prod(1 + benchmark) - 1),
        annualized_volatility=annualized_volatility,
        mean_gross=float(np.mean(state.gross)) if state.gross else 0.0,
        mean_cash=1 - (float(np.mean(state.gross)) if state.gross else 0.0),
        mean_beta=float(np.mean(state.beta)) if state.beta else 0.0,
        upside_capture=upside,
        downside_capture=downside,
        participation_gap=None if upside is None else 1 - upside,
        turnover_l1=state.turnover,
    )


def _update_target(
    state: _PolicyState,
    target: dict[str, float],
    *,
    cost_rate: float,
) -> None:
    turnover = sum(
        abs(target.get(symbol, 0.0) - state.weights.get(symbol, 0.0))
        for symbol in SYMBOLS
    )
    state.turnover += turnover
    state.pending_cost += turnover * cost_rate
    state.weights = {symbol: weight for symbol, weight in target.items() if weight > 1e-12}


def _drift_weights(
    weights: dict[str, float],
    row: dict[str, float],
    *,
    cost: float,
) -> dict[str, float]:
    cash = 1 - sum(weights.values())
    asset_values = {
        symbol: weight * (1 + row[symbol]) for symbol, weight in weights.items()
    }
    denominator = cash - cost + sum(asset_values.values())
    if denominator <= 0 or not isfinite(denominator):
        return {}
    return {
        symbol: value / denominator
        for symbol, value in asset_values.items()
        if value / denominator > 1e-12
    }


def _normalized_positive(values: dict[str, float]) -> dict[str, float]:
    positive = {symbol: max(0.0, value) for symbol, value in values.items() if value > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {symbol: value / total for symbol, value in positive.items()}


def _scale_ray_to_feasible(
    ray: dict[str, float],
    *,
    risk: RiskModelEstimate,
    constraints: PortfolioConstraints,
    target_beta: float | None = None,
    maximum_gross: bool = True,
) -> dict[str, float]:
    normalized = _normalized_positive(ray)
    if not normalized:
        return {}
    vector = np.asarray([normalized.get(symbol, 0.0) for symbol in risk.symbols], dtype=float)
    sector_sums = {
        sector: sum(
            vector[index]
            for index, symbol in enumerate(risk.symbols)
            if risk.sectors[symbol] == sector
        )
        for sector in sorted(set(risk.sectors.values()))
    }
    beta = np.asarray([risk.beta[symbol] for symbol in risk.symbols], dtype=float)
    size = np.asarray([risk.size_scores[symbol] for symbol in risk.symbols], dtype=float)
    limits = [
        constraints.maximum_gross_exposure,
        (1 - constraints.minimum_cash_weight),
        constraints.maximum_position_weight / max(float(vector.max()), 1e-12),
        constraints.maximum_sector_weight / max(max(sector_sums.values()), 1e-12),
        sqrt(constraints.maximum_hhi / max(float(vector @ vector), 1e-12)),
        constraints.maximum_beta / max(float(beta @ vector), 1e-12),
        constraints.target_annualized_volatility
        / max(portfolio_volatility(vector, risk.annualized_covariance), 1e-12),
        constraints.maximum_size_exposure / max(abs(float(size @ vector)), 1e-12),
    ]
    gross = max(0.0, min(limits))
    if target_beta is not None and float(beta @ vector) > 0:
        gross = min(gross, target_beta / float(beta @ vector))
    if not maximum_gross:
        gross = min(gross, sum(ray.values()))
    return {
        symbol: float(vector[index] * gross)
        for index, symbol in enumerate(risk.symbols)
        if vector[index] * gross > 1e-12
    }


def _factor_ray(alpha: StrategyAlphaResult, factor: str) -> dict[str, float]:
    return {
        item.symbol: max(0.0, item.components.get(factor, 0.0))
        for item in alpha.factors
    }


def _expected_ray(alpha: StrategyAlphaResult) -> dict[str, float]:
    return {item.symbol: max(0.0, item.expected_alpha) for item in alpha.factors}


def _same_selection_equal_weight(target: dict[str, float]) -> dict[str, float]:
    if not target:
        return {}
    gross = sum(target.values())
    weight = gross / len(target)
    return dict.fromkeys(sorted(target), weight)


def _binding_constraints(target: dict[str, object] | None) -> tuple[str, ...]:
    if not target:
        return ()
    pre = target.get("pre_solve_constraint_state")
    return tuple(str(item) for item in pre) if isinstance(pre, list) else ()


def _simulate_scenario(spec: SyntheticScenarioSpec, *, seed: int) -> ScenarioAttribution:
    returns, benchmark = _synthetic_market(spec, seed=seed)
    prices = _price_frame(returns)
    factor_metadata = _factor_metadata()
    risk_metadata = _risk_metadata(spec)
    cost_model = TransactionCostModel(
        TransactionCostConfig(
            spread_bps=4.0 * spec.spread_multiplier,
            slippage_bps=3.0 * spec.spread_multiplier,
            impact_coefficient_bps=10.0 * spec.spread_multiplier,
            version=f"round61-cost-{spec.name.lower()}",
        )
    )
    zero_cost = TransactionCostModel(
        TransactionCostConfig(
            commission_bps=0.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient_bps=0.0,
            version="round61-zero-cost",
        )
    )
    constraints = PortfolioConstraints(model_validation_id="round61-synthetic-validation")
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(
            constraints,
            cost_model,
            operational_mode=True,
        ),
        cost_model=cost_model,
        stress_config=StressRiskConfig(
            validation_id="round61-synthetic-validation",
            provisional_operational=True,
        ),
        operational_mode=True,
    )
    base_engine = PortfolioConstructionEngine(constraints, cost_model, operational_mode=True)
    zero_cost_engine = PortfolioConstructionEngine(
        constraints,
        zero_cost,
        operational_mode=True,
    )
    strategy = USAdaptiveAlphaCoreV1()
    states = {name: _PolicyState(dict(INITIAL_WEIGHTS)) for name in POLICIES}
    states[SPY_BENCHMARK] = _PolicyState({})
    states[QQQ_BENCHMARK] = _PolicyState({})
    steps: list[ParticipationStep] = []
    binding: dict[str, int] = {}
    primary_count = 0
    recovery_count = 0
    blocked_count = 0
    last_risk: RiskModelEstimate | None = None
    last_stage = "UNAVAILABLE"
    decision_indexes = set(
        range(WARMUP_SESSIONS - 1, len(returns) - 1, REBALANCE_SESSIONS)
    )

    for index in range(WARMUP_SESSIONS - 1, len(returns) - 1):
        history = returns.iloc[: index + 1]
        benchmark_history = benchmark.iloc[: index + 1]
        decision_time = _decision_time(returns.index[index])
        alpha: StrategyAlphaResult | None = None
        if index in decision_indexes:
            alpha = strategy.generate(
                prices=prices.loc[prices["trade_date"] <= returns.index[index]],
                metadata=factor_metadata,
                decision_time=decision_time,
                data_version=f"round61-{spec.name.lower()}",
                approval=None,
                operational_approval_hash="round61-synthetic-only",
            )
            output = pipeline.run(
                DailyQuantInput(
                    authorization=_authorization(
                        decision_time,
                        start_date=history.index[0].date(),
                        end_date=history.index[-1].date(),
                        data_version=f"round61-{spec.name.lower()}",
                    ),
                    decision_time=decision_time,
                    alpha_signals=alpha.signals,
                    returns=history,
                    benchmark_returns=benchmark_history,
                    risk_metadata=risk_metadata,
                    current_weights=states[CURRENT_POLICY].weights,
                    portfolio_value=100_000.0,
                    portfolio_risk_state=_portfolio_risk_state(
                        history,
                        benchmark_history,
                        states[CURRENT_POLICY].weights,
                    ),
                    regime=None,
                    pit_valid=True,
                    universe_snapshot_id="ROUND61-SYNTHETIC-PIT",
                    data_quality="CERTIFIED",
                )
            )
            if output.risk is not None:
                last_risk = output.risk
            if output.status is ProductionPipelineStatus.READY and output.target is not None:
                target = output.target
                last_stage = target.optimization_stage.value
                primary_count += int(
                    target.optimization_stage is PortfolioOptimizationStage.PRIMARY_OPTIMIZER
                )
                recovery_count += int(
                    target.optimization_stage
                    is PortfolioOptimizationStage.FEASIBILITY_RECOVERY
                )
                _update_target(
                    states[CURRENT_POLICY],
                    target.target_weights,
                    cost_rate=cost_model.conservative_rate,
                )
                for item in _binding_constraints(target.optimizer_provenance):
                    binding[item] = binding.get(item, 0) + 1
                risk = output.risk
                budget = output.risk_budget
                assert risk is not None and budget is not None
                selection = target.target_weights
                _update_target(
                    states[EQUAL_WEIGHT],
                    _same_selection_equal_weight(selection),
                    cost_rate=cost_model.conservative_rate,
                )
                base_target = base_engine.construct(
                    authorization=_authorization(
                        decision_time,
                        start_date=history.index[0].date(),
                        end_date=history.index[-1].date(),
                        data_version=f"round61-{spec.name.lower()}",
                    ),
                    alpha_signals=alpha.signals,
                    risk=risk,
                    current_weights=states[NO_DYNAMIC_RISK].weights,
                    portfolio_value=100_000.0,
                    decision_time=decision_time,
                    risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
                )
                if base_target.operational_approved:
                    _update_target(
                        states[NO_DYNAMIC_RISK],
                        base_target.target_weights,
                        cost_rate=cost_model.conservative_rate,
                    )
                _update_target(
                    states[BENCHMARK_BETA],
                    _scale_ray_to_feasible(
                        selection,
                        risk=risk,
                        constraints=constraints,
                        target_beta=1.0,
                    ),
                    cost_rate=cost_model.conservative_rate,
                )
                _update_target(
                    states[MAXIMUM_GROSS],
                    _scale_ray_to_feasible(
                        selection,
                        risk=risk,
                        constraints=constraints,
                    ),
                    cost_rate=cost_model.conservative_rate,
                )
                for policy, ray in (
                    (ALPHA_NO_OPTIMIZER, _expected_ray(alpha)),
                    (PURE_MOMENTUM, _factor_ray(alpha, "momentum")),
                    (PURE_TREND, _factor_ray(alpha, "trend")),
                    (PURE_LOW_VOL, _factor_ray(alpha, "low_volatility")),
                    (BROAD_EQUAL_WEIGHT, dict.fromkeys(SYMBOLS, 1.0)),
                ):
                    _update_target(
                        states[policy],
                        _scale_ray_to_feasible(
                            ray,
                            risk=risk,
                            constraints=constraints,
                        ),
                        cost_rate=cost_model.conservative_rate,
                    )
                zero_target = zero_cost_engine.construct(
                    authorization=_authorization(
                        decision_time,
                        start_date=history.index[0].date(),
                        end_date=history.index[-1].date(),
                        data_version=f"round61-{spec.name.lower()}",
                    ),
                    alpha_signals=alpha.signals,
                    risk=risk,
                    current_weights=states[NO_TRANSACTION_COST].weights,
                    portfolio_value=100_000.0,
                    decision_time=decision_time,
                    risk_budget=budget,
                )
                if zero_target.operational_approved:
                    _update_target(
                        states[NO_TRANSACTION_COST],
                        zero_target.target_weights,
                        cost_rate=0.0,
                    )
                if target.optimization_stage is PortfolioOptimizationStage.PRIMARY_OPTIMIZER:
                    _update_target(
                        states[PRE_ROUND60],
                        target.target_weights,
                        cost_rate=cost_model.conservative_rate,
                    )
            else:
                blocked_count += 1

        if last_risk is not None:
            daily_alpha = strategy.generate(
                prices=prices.loc[prices["trade_date"] <= returns.index[index]],
                metadata=factor_metadata,
                decision_time=decision_time,
                data_version=f"round61-daily-{spec.name.lower()}",
                approval=None,
                operational_approval_hash="round61-synthetic-only",
            )
            _update_target(
                states[DAILY_ALPHA],
                _scale_ray_to_feasible(
                    _expected_ray(daily_alpha),
                    risk=last_risk,
                    constraints=constraints,
                ),
                cost_rate=cost_model.conservative_rate,
            )

        next_index = index + 1
        if next_index < WARMUP_SESSIONS:
            continue
        row = {symbol: float(returns.iloc[next_index][symbol]) for symbol in SYMBOLS}
        benchmark_return = float(benchmark.iloc[next_index])
        qqq_return = float(np.mean([row[symbol] for symbol in SYMBOLS[:4]]))
        for policy, state in states.items():
            assert state.returns is not None
            assert state.gross is not None
            assert state.beta is not None
            assert state.volatility is not None
            if policy == SPY_BENCHMARK:
                value = benchmark_return
                gross = 1.0
                beta_value = 1.0
                volatility_value = 0.0
            elif policy == QQQ_BENCHMARK:
                value = qqq_return
                gross = 1.0
                beta_value = 1.0
                volatility_value = 0.0
            else:
                gross = sum(state.weights.values())
                value = sum(state.weights.get(symbol, 0.0) * row[symbol] for symbol in SYMBOLS)
                value -= state.pending_cost
                if last_risk is not None:
                    vector = np.asarray(
                        [state.weights.get(symbol, 0.0) for symbol in SYMBOLS],
                        dtype=float,
                    )
                    beta_vector = np.asarray(
                        [last_risk.beta[symbol] for symbol in SYMBOLS],
                        dtype=float,
                    )
                    beta_value = float(beta_vector @ vector)
                    volatility_value = portfolio_volatility(
                        vector,
                        last_risk.annualized_covariance,
                    )
                else:
                    beta_value = 0.0
                    volatility_value = 0.0
            state.returns.append(value)
            state.gross.append(gross)
            state.beta.append(beta_value)
            state.volatility.append(volatility_value)

        actual_state = states[CURRENT_POLICY]
        gross = sum(actual_state.weights.values())
        gross_return = sum(
            actual_state.weights.get(symbol, 0.0) * row[symbol] for symbol in SYMBOLS
        )
        sector_returns = {
            sector: float(
                np.mean(
                    [row[symbol] for symbol in SYMBOLS if SECTOR_BY_SYMBOL[symbol] == sector]
                )
            )
            for sector in sorted(set(SECTOR_BY_SYMBOL.values()))
        }
        stock_selection = sum(
            actual_state.weights.get(symbol, 0.0)
            * (row[symbol] - sector_returns[SECTOR_BY_SYMBOL[symbol]])
            for symbol in SYMBOLS
        )
        sector_allocation = sum(
            sum(
                actual_state.weights.get(symbol, 0.0)
                for symbol in SYMBOLS
                if SECTOR_BY_SYMBOL[symbol] == sector
            )
            * (sector_return - benchmark_return)
            for sector, sector_return in sector_returns.items()
        )
        selection_return = stock_selection + sector_allocation
        exposure = (gross - 1) * benchmark_return
        cost_drag = -actual_state.pending_cost
        active = gross_return + cost_drag - benchmark_return
        residual = active - selection_return - exposure - cost_drag
        assert abs(residual) <= 1e-10
        current_beta_history = states[CURRENT_POLICY].beta
        current_volatility_history = states[CURRENT_POLICY].volatility
        assert current_beta_history is not None
        assert current_volatility_history is not None
        steps.append(
            ParticipationStep(
                scenario=spec.name,
                session=returns.index[next_index].date().isoformat(),
                portfolio_return=gross_return + cost_drag,
                benchmark_return=benchmark_return,
                gross_exposure=gross,
                net_exposure=gross,
                cash_weight=1 - gross,
                beta=current_beta_history[-1],
                volatility=current_volatility_history[-1],
                selection_return=selection_return,
                stock_selection_return=stock_selection,
                sector_allocation_return=sector_allocation,
                exposure_drag=exposure,
                cash_drag=exposure,
                transaction_cost_drag=cost_drag,
                residual_return=residual,
                recovery_stage=last_stage,
            )
        )
        for state in states.values():
            cost = state.pending_cost
            state.pending_cost = 0.0
            if state.weights:
                state.weights = _drift_weights(state.weights, row, cost=cost)

    benchmark_values = np.asarray(states[SPY_BENCHMARK].returns, dtype=float)
    policy_metrics = tuple(
        _policy_metrics(name, states[name], benchmark_values) for name in POLICIES
    )
    return ScenarioAttribution(
        scenario=spec.name,
        regime=spec.regime,
        policies=policy_metrics,
        active_return_arithmetic=sum(
            item.portfolio_return - item.benchmark_return for item in steps
        ),
        stock_selection=sum(item.stock_selection_return for item in steps),
        sector_allocation=sum(item.sector_allocation_return for item in steps),
        exposure_drag=sum(item.exposure_drag for item in steps),
        transaction_cost_drag=sum(item.transaction_cost_drag for item in steps),
        residual=sum(item.residual_return for item in steps),
        primary_count=primary_count,
        recovery_count=recovery_count,
        blocked_count=blocked_count,
        binding_constraints=binding,
        steps=tuple(steps),
    )


def _metrics_map(scenario: ScenarioAttribution) -> dict[str, PolicyMetrics]:
    return {item.policy: item for item in scenario.policies}


@lru_cache(maxsize=2)
def run_round61_attribution(*, seed: int = DEFAULT_SEED) -> Round61AttributionReport:
    scenarios = tuple(
        _simulate_scenario(spec, seed=seed + index * 1009)
        for index, spec in enumerate(SCENARIOS)
    )
    normal_bull = tuple(
        item
        for item in scenarios
        if item.scenario in {"NORMAL_MIXED_MARKET", "STRONG_BULL_MARKET"}
    )
    causes: dict[str, float] = {
        "stock_selection": sum(item.stock_selection for item in normal_bull),
        "sector_allocation": sum(item.sector_allocation for item in normal_bull),
        "gross_cash_exposure": sum(item.exposure_drag for item in normal_bull),
        "transaction_cost": sum(item.transaction_cost_drag for item in normal_bull),
        "optimizer_effect": sum(
            _metrics_map(item)[CURRENT_POLICY].total_return
            - _metrics_map(item)[ALPHA_NO_OPTIMIZER].total_return
            for item in normal_bull
        ),
        "dynamic_risk_budget_effect": sum(
            _metrics_map(item)[CURRENT_POLICY].total_return
            - _metrics_map(item)[NO_DYNAMIC_RISK].total_return
            for item in normal_bull
        ),
        "beta_suppression_effect": sum(
            _metrics_map(item)[CURRENT_POLICY].total_return
            - _metrics_map(item)[BENCHMARK_BETA].total_return
            for item in normal_bull
        ),
        "maximum_gross_effect": sum(
            _metrics_map(item)[CURRENT_POLICY].total_return
            - _metrics_map(item)[MAXIMUM_GROSS].total_return
            for item in normal_bull
        ),
        "round60_recovery_effect": sum(
            _metrics_map(item)[CURRENT_POLICY].total_return
            - _metrics_map(item)[PRE_ROUND60].total_return
            for item in normal_bull
        ),
        "rebalance_timing_effect": sum(
            _metrics_map(item)[ALPHA_NO_OPTIMIZER].total_return
            - _metrics_map(item)[DAILY_ALPHA].total_return
            for item in normal_bull
        ),
    }
    ranked = tuple(sorted(causes.items(), key=lambda item: abs(item[1]), reverse=True))
    maximum_residual = max(
        abs(item.residual) for item in scenarios
    )
    return Round61AttributionReport(
        version=ROUND61_VERSION,
        seed=seed,
        scenarios=scenarios,
        ranked_root_causes=ranked,
        maximum_absolute_residual=maximum_residual,
    )
