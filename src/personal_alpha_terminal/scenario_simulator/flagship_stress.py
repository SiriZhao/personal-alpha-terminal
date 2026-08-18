"""Deterministic synthetic flagship stress test through the production quant chain.

The generated paths are synthetic and intentionally use a fictitious 2099 calendar.
No historical crisis data or historical market trend is queried or reproduced.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from hashlib import sha256
from math import sqrt
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from personal_alpha_terminal.intelligence.agentic_engine import fuse_alpha
from personal_alpha_terminal.intelligence.agentic_models import (
    LLMInfluencePolicy,
    PromotionEvaluation,
    PromotionStatus,
)
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
    PortfolioOptimizationStage,
)
from personal_alpha_terminal.quant_engine.probability_overlay import (
    ProbabilityOverlayIdentity,
    apply_probability_overlay,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
)
from personal_alpha_terminal.quant_engine.risk.drift import RiskDriftStatus
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

STRESS_VERSION = "flagship-synthetic-stress-v2"
DEFAULT_SEED = 20260817
SYMBOLS = tuple(f"S{index:02d}" for index in range(24))
SECTORS = (
    "TECH",
    "HEALTH",
    "FINANCIALS",
    "INDUSTRIALS",
    "ENERGY",
    "DEFENSIVE",
)
SECTOR_BY_SYMBOL = {
    symbol: SECTORS[index // 4] for index, symbol in enumerate(SYMBOLS)
}
SYNTHETIC_START = "2099-01-05"
WARMUP_SESSIONS = 260
EVALUATION_SESSIONS = 105
REBALANCE_SESSIONS = 21
INITIAL_WEIGHTS = {symbol: 0.04 for symbol in SYMBOLS[:12]}


@dataclass(frozen=True, slots=True)
class SyntheticScenarioSpec:
    name: str
    regime: str
    annual_drift: float
    annual_volatility: float
    correlation: float
    target_benchmark_return: float
    shocks: tuple[tuple[int, float], ...] = ()
    liquidity_multiplier: float = 1.0
    spread_multiplier: float = 1.0
    style_mode: Literal["none", "invert", "alternate", "sector", "dispersion"] = "none"
    adversarial_conditions: tuple[str, ...] = ()


SCENARIOS: tuple[SyntheticScenarioSpec, ...] = (
    SyntheticScenarioSpec(
        "EXTREME_SYSTEMIC_CRASH",
        "极端系统性崩盘",
        -1.20,
        0.95,
        0.995,
        -0.75,
        shocks=((0, -0.22), (1, -0.16), (2, -0.12), (20, 0.12), (38, -0.18), (39, -0.12)),
        liquidity_multiplier=0.03,
        spread_multiplier=20.0,
        style_mode="dispersion",
        adversarial_conditions=(
            "overnight_gap",
            "volatility_explosion",
            "correlation_near_one",
            "repeated_limit_like_moves",
            "liquidity_collapse",
            "slippage_explosion",
            "dead_cat_bounce",
            "repeated_crash_waves",
        ),
    ),
    SyntheticScenarioSpec(
        "SEVERE_BEAR_MARKET",
        "严重熊市",
        -0.65,
        0.55,
        0.95,
        -0.50,
        shocks=((5, -0.10), (35, 0.07), (52, -0.09), (78, -0.08)),
        liquidity_multiplier=0.20,
        spread_multiplier=8.0,
        adversarial_conditions=("prolonged_drawdown", "crash_waves", "partial_recovery"),
    ),
    SyntheticScenarioSpec(
        "MODERATE_BEAR_MARKET",
        "中度熊市",
        -0.25,
        0.32,
        0.80,
        -0.22,
        shocks=((12, -0.06), (54, -0.05)),
        liquidity_multiplier=0.55,
        spread_multiplier=4.0,
        adversarial_conditions=("gap_down", "false_recovery"),
    ),
    SyntheticScenarioSpec(
        "NORMAL_MIXED_MARKET",
        "正常混合市场",
        0.05,
        0.18,
        0.45,
        0.04,
        shocks=((50, -0.035), (55, 0.035)),
        style_mode="alternate",
        adversarial_conditions=("mixed_signals", "false_breakout"),
    ),
    SyntheticScenarioSpec(
        "STRONG_BULL_MARKET",
        "强势牛市",
        0.45,
        0.25,
        0.60,
        0.45,
        shocks=((45, -0.055), (47, 0.065)),
        adversarial_conditions=("bull_run", "v_shaped_recovery", "breakout_reversal"),
    ),
    SyntheticScenarioSpec(
        "FACTOR_INVERSION_MOMENTUM_CRASH",
        "因子反转与动量崩溃",
        -0.05,
        0.45,
        0.65,
        -0.12,
        shocks=((8, -0.07), (9, 0.04)),
        style_mode="invert",
        adversarial_conditions=("factor_inversion", "momentum_crash", "conflicting_factors"),
    ),
    SyntheticScenarioSpec(
        "RAPID_ALTERNATING_FALSE_BREAKOUTS",
        "快速交替与假突破",
        0.00,
        0.40,
        0.75,
        0.00,
        shocks=((18, 0.08), (19, -0.10), (60, 0.09), (61, -0.11)),
        style_mode="alternate",
        adversarial_conditions=("rapid_regime_switch", "false_breakouts", "turnover_temptation"),
    ),
    SyntheticScenarioSpec(
        "CONCENTRATED_SECTOR_COLLAPSE_ROTATION",
        "集中行业崩盘与风格轮动",
        -0.10,
        0.35,
        0.70,
        -0.18,
        shocks=((15, -0.05),),
        style_mode="sector",
        adversarial_conditions=("sector_collapse", "quality_value_growth_rotation"),
    ),
    SyntheticScenarioSpec(
        "LIQUIDITY_AND_SLIPPAGE_EXPLOSION",
        "流动性与滑点爆炸",
        -0.10,
        0.38,
        0.85,
        -0.20,
        shocks=((25, -0.08),),
        liquidity_multiplier=0.015,
        spread_multiplier=25.0,
        adversarial_conditions=("volume_collapse", "spread_x25", "market_impact_explosion"),
    ),
    SyntheticScenarioSpec(
        "EXTREME_DISPERSION_OPTIMIZER_STABILITY",
        "极端离散与优化器稳定性",
        0.00,
        0.55,
        0.98,
        0.08,
        shocks=((30, -0.06), (70, 0.07)),
        style_mode="dispersion",
        adversarial_conditions=(
            "extreme_dispersion",
            "near_singular_covariance",
            "optimizer_stability",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ScenarioMetrics:
    scenario: str
    regime: str
    synthetic_return: float
    benchmark_return: float
    excess_return: float
    annualized_volatility: float
    sharpe_like: float | None
    maximum_drawdown: float
    worst_period_loss: float
    recovery_sessions: int | None
    turnover_l1: float
    transaction_cost_drag: float
    mean_cash_weight: float
    mean_gross_exposure: float
    mean_holdings: float
    maximum_position_weight: float
    maximum_hhi: float
    ready_decisions: int
    blocked_decisions: int
    fail_closed_reasons: tuple[str, ...]
    risk_reactions: tuple[str, ...]
    long_only_preserved: bool
    gross_cap_preserved: bool
    numerical_stability: bool
    no_fixed_cardinality_cap: bool
    probability_formal_influence: float
    llm_formal_influence: float
    primary_optimizer_passes: int
    feasibility_recovery_passes: int
    sell_only_fallback_passes: int
    optimizer_blocked: int
    risk_drift_warnings: int
    risk_drift_hard_breaches: int
    classification: str
    adversarial_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SyntheticStressSummary:
    stress_id: str
    version: str
    seed: int
    generated_at: datetime
    scenarios: tuple[ScenarioMetrics, ...]
    resilience_checks: dict[str, str]
    classification: str
    warnings: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "stress_id": self.stress_id,
            "version": self.version,
            "seed": self.seed,
            "generated_at": self.generated_at.isoformat(),
            "scenarios": [asdict(item) for item in self.scenarios],
            "resilience_checks": self.resilience_checks,
            "classification": self.classification,
            "warnings": list(self.warnings),
            "synthetic_only": True,
            "not_historical_performance": True,
            "not_alpha_certification": True,
            "production_components_exercised": [
                "USAdaptiveAlphaCoreV1",
                "DailyQuantPipeline",
                "PortfolioRiskModel",
                "DynamicRiskBudget",
                "RiskDriftMonitor",
                "PortfolioConstructionEngine",
                "PortfolioStressReport",
                "TradeGenerator",
                "ProductionDecisionEngine",
            ],
        }


@lru_cache(maxsize=4)
def run_flagship_synthetic_stress(*, seed: int = DEFAULT_SEED) -> SyntheticStressSummary:
    scenario_metrics = tuple(
        _simulate_scenario(spec, seed=seed + index * 1009)
        for index, spec in enumerate(SCENARIOS)
    )
    resilience = _run_resilience_checks(seed=seed + 50_000)
    invariant_failure = any(
        not item.long_only_preserved
        or not item.gross_cap_preserved
        or not item.numerical_stability
        or not item.no_fixed_cardinality_cap
        for item in scenario_metrics
    )
    resilience_failure = any(not value.startswith("PASS") for value in resilience.values())
    classification = (
        "SYNTHETIC_STRESS_FAIL"
        if invariant_failure or resilience_failure
        else "SYNTHETIC_STRESS_PASS_WITH_WARNINGS"
    )
    identity = {
        "version": STRESS_VERSION,
        "seed": seed,
        "classification": classification,
        "scenario_specs": [asdict(item) for item in SCENARIOS],
        "scenario_metrics": [asdict(item) for item in scenario_metrics],
        "resilience": resilience,
    }
    digest = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return SyntheticStressSummary(
        stress_id=f"flagship-stress-{digest[:16]}",
        version=STRESS_VERSION,
        seed=seed,
        generated_at=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
        scenarios=scenario_metrics,
        resilience_checks=resilience,
        classification=classification,
        warnings=(
            "SYNTHETIC_ONLY",
            "NO_HISTORICAL_CRISIS_DATA_USED",
            "NOT_HISTORICAL_PERFORMANCE",
            "NOT_ALPHA_CERTIFICATION",
            "SYNTHETIC_2099_TIMELINE_HAS_NO_MARKET_MEANING",
        ),
    )


def write_flagship_stress_summary(summary: SyntheticStressSummary, path: Path) -> None:
    rendered = json.dumps(summary.document(), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite flagship stress artifact: {path}")
    path.write_text(rendered, encoding="utf-8")


def _simulate_scenario(spec: SyntheticScenarioSpec, *, seed: int) -> ScenarioMetrics:
    returns, benchmark = _synthetic_market(spec, seed=seed)
    prices = _price_frame(returns)
    metadata = _factor_metadata()
    risk_metadata = _risk_metadata(spec)
    cost_model = TransactionCostModel(
        TransactionCostConfig(
            spread_bps=4.0 * spec.spread_multiplier,
            slippage_bps=3.0 * spec.spread_multiplier,
            impact_coefficient_bps=10.0 * spec.spread_multiplier,
            version=f"synthetic-cost-{spec.name.lower()}",
        )
    )
    construction = PortfolioConstructionEngine(
        PortfolioConstraints(model_validation_id="synthetic-stress-validation-v1"),
        cost_model,
        operational_mode=True,
    )
    pipeline = DailyQuantPipeline(
        construction=construction,
        cost_model=cost_model,
        stress_config=StressRiskConfig(
            validation_id="synthetic-stress-validation-v1",
            provisional_operational=True,
        ),
        operational_mode=True,
    )
    strategy = USAdaptiveAlphaCoreV1()
    weights = dict(INITIAL_WEIGHTS)
    equity = 1.0
    daily_returns: list[float] = []
    benchmark_evaluation: list[float] = []
    cash_observations: list[float] = []
    gross_observations: list[float] = []
    holding_observations: list[int] = []
    hhi_observations: list[float] = []
    position_observations: list[float] = []
    ready = 0
    blocked = 0
    turnover = 0.0
    cost_drag = 0.0
    pending_cost = 0.0
    fail_closed: list[str] = []
    risk_reactions: list[str] = []
    long_only = True
    gross_cap = True
    numerical = True
    no_fixed_cap = True
    primary_optimizer_passes = 0
    feasibility_recovery_passes = 0
    sell_only_fallback_passes = 0
    optimizer_blocked = 0
    risk_drift_warnings = 0
    risk_drift_hard_breaches = 0
    decision_indexes = set(
        range(WARMUP_SESSIONS - 1, len(returns) - 1, REBALANCE_SESSIONS)
    )

    for index in range(WARMUP_SESSIONS - 1, len(returns) - 1):
        if index in decision_indexes:
            decision_time = _decision_time(returns.index[index])
            history = returns.iloc[: index + 1]
            benchmark_history = benchmark.iloc[: index + 1]
            alpha = strategy.generate(
                prices=prices.loc[prices["trade_date"] <= returns.index[index]],
                metadata=metadata,
                decision_time=decision_time,
                data_version=f"synthetic-{spec.name.lower()}",
                approval=None,
                operational_approval_hash="synthetic-stress-only",
            )
            output = pipeline.run(
                DailyQuantInput(
                    authorization=_authorization(
                        decision_time,
                        start_date=history.index[0].date(),
                        end_date=history.index[-1].date(),
                        data_version=f"synthetic-{spec.name.lower()}",
                    ),
                    decision_time=decision_time,
                    alpha_signals=alpha.signals,
                    returns=history,
                    benchmark_returns=benchmark_history,
                    risk_metadata=risk_metadata,
                    current_weights=weights,
                    portfolio_value=max(1.0, 100_000.0 * equity),
                    portfolio_risk_state=_portfolio_risk_state(
                        history,
                        benchmark_history,
                        weights,
                    ),
                    regime=None,
                    pit_valid=True,
                    universe_snapshot_id="SYNTHETIC-PIT-UNIVERSE-V1",
                    data_quality="CERTIFIED",
                )
            )
            if output.risk_drift is not None:
                risk_drift_warnings += int(
                    output.risk_drift.status is RiskDriftStatus.WARNING
                )
                risk_drift_hard_breaches += int(
                    output.risk_drift.status is RiskDriftStatus.HARD_BREACH
                )
            if output.target is not None:
                stage = output.target.optimization_stage
                primary_optimizer_passes += int(
                    stage is PortfolioOptimizationStage.PRIMARY_OPTIMIZER
                )
                feasibility_recovery_passes += int(
                    stage is PortfolioOptimizationStage.FEASIBILITY_RECOVERY
                )
                sell_only_fallback_passes += int(
                    stage is PortfolioOptimizationStage.SELL_ONLY_FALLBACK
                )
                optimizer_blocked += int(stage is PortfolioOptimizationStage.BLOCKED)
            risk_reactions.extend(
                stage.detail for stage in output.stages if stage.name == "Risk Budget"
            )
            if output.status is ProductionPipelineStatus.READY and output.target is not None:
                ready += 1
                turnover += output.target.turnover
                pending_cost += output.target.estimated_transaction_cost / max(
                    1.0, 100_000.0 * equity
                )
                cost_drag += output.target.estimated_transaction_cost / max(
                    1.0, 100_000.0 * equity
                )
                weights = dict(output.target.target_weights)
                provenance = output.target.optimizer_provenance or {}
                no_fixed_cap = no_fixed_cap and provenance.get("pre_optimizer_top_n") is None
            else:
                blocked += 1
                fail_closed.extend(output.blockers)

        next_index = index + 1
        if next_index < WARMUP_SESSIONS:
            continue
        row = returns.iloc[next_index]
        gross_before = sum(weights.values())
        portfolio_return = sum(weights.get(symbol, 0.0) * float(row[symbol]) for symbol in SYMBOLS)
        applied_cost = pending_cost
        net_return = portfolio_return - applied_cost
        pending_cost = 0.0
        if not np.isfinite(net_return) or net_return <= -1.0:
            numerical = False
            net_return = max(-0.999999, float(np.nan_to_num(net_return, nan=-0.999999)))
        equity *= 1.0 + net_return
        daily_returns.append(net_return)
        benchmark_evaluation.append(float(benchmark.iloc[next_index]))

        cash_before = 1.0 - gross_before
        asset_values = {
            symbol: weight * (1.0 + float(row[symbol]))
            for symbol, weight in weights.items()
        }
        denominator = cash_before - applied_cost + sum(asset_values.values())
        if not np.isfinite(denominator) or denominator <= 0:
            numerical = False
            weights = {}
        else:
            weights = {
                symbol: value / denominator
                for symbol, value in asset_values.items()
                if value / denominator > 1e-12
            }
        gross = sum(weights.values())
        long_only = long_only and all(
            np.isfinite(value) and value >= -1e-12 for value in weights.values()
        )
        gross_cap = gross_cap and gross <= 1.0 + 1e-8
        numerical = numerical and bool(np.isfinite(equity)) and equity > 0
        cash_observations.append(1.0 - gross)
        gross_observations.append(gross)
        holding_observations.append(len(weights))
        hhi_observations.append(sum(value * value for value in weights.values()))
        position_observations.append(max(weights.values(), default=0.0))

    portfolio_series = np.asarray(daily_returns, dtype=float)
    benchmark_series = np.asarray(benchmark_evaluation, dtype=float)
    wealth = np.cumprod(1.0 + portfolio_series)
    benchmark_wealth = np.cumprod(1.0 + benchmark_series)
    drawdown = wealth / np.maximum.accumulate(wealth) - 1.0
    volatility = float(np.std(portfolio_series, ddof=1) * sqrt(252))
    standard_deviation = float(np.std(portfolio_series, ddof=1))
    sharpe = (
        float(np.mean(portfolio_series) / standard_deviation * sqrt(252))
        if standard_deviation > 0
        else None
    )
    recovery = _recovery_sessions(wealth)
    classification = (
        "FAIL_INVARIANT"
        if not (long_only and gross_cap and numerical and no_fixed_cap)
        else "PASS_FAIL_CLOSED"
        if blocked
        else "PASS"
    )
    return ScenarioMetrics(
        scenario=spec.name,
        regime=spec.regime,
        synthetic_return=float(wealth[-1] - 1.0),
        benchmark_return=float(benchmark_wealth[-1] - 1.0),
        excess_return=float(wealth[-1] - benchmark_wealth[-1]),
        annualized_volatility=volatility,
        sharpe_like=sharpe,
        maximum_drawdown=float(drawdown.min()),
        worst_period_loss=float(portfolio_series.min()),
        recovery_sessions=recovery,
        turnover_l1=float(turnover),
        transaction_cost_drag=float(cost_drag),
        mean_cash_weight=float(np.mean(cash_observations)),
        mean_gross_exposure=float(np.mean(gross_observations)),
        mean_holdings=float(np.mean(holding_observations)),
        maximum_position_weight=float(max(position_observations, default=0.0)),
        maximum_hhi=float(max(hhi_observations, default=0.0)),
        ready_decisions=ready,
        blocked_decisions=blocked,
        fail_closed_reasons=tuple(dict.fromkeys(fail_closed)),
        risk_reactions=tuple(dict.fromkeys(risk_reactions)),
        long_only_preserved=long_only,
        gross_cap_preserved=gross_cap,
        numerical_stability=numerical,
        no_fixed_cardinality_cap=no_fixed_cap,
        probability_formal_influence=0.0,
        llm_formal_influence=0.0,
        primary_optimizer_passes=primary_optimizer_passes,
        feasibility_recovery_passes=feasibility_recovery_passes,
        sell_only_fallback_passes=sell_only_fallback_passes,
        optimizer_blocked=optimizer_blocked,
        risk_drift_warnings=risk_drift_warnings,
        risk_drift_hard_breaches=risk_drift_hard_breaches,
        classification=classification,
        adversarial_conditions=spec.adversarial_conditions,
    )


def _synthetic_market(
    spec: SyntheticScenarioSpec,
    *,
    seed: int,
) -> tuple[pd.DataFrame, pd.Series]:
    total_sessions = WARMUP_SESSIONS + EVALUATION_SESSIONS
    index = pd.bdate_range(SYNTHETIC_START, periods=total_sessions)
    rng = np.random.RandomState(seed)
    symbol_count = len(SYMBOLS)
    style = np.linspace(-1.0, 1.0, symbol_count)
    baseline_common = rng.normal(0.00025, 0.008, WARMUP_SESSIONS)
    baseline_idiosyncratic = rng.normal(0.0, 0.009, (WARMUP_SESSIONS, symbol_count))
    baseline = (
        baseline_common[:, None]
        + baseline_idiosyncratic
        + 0.00035 * style[None, :]
    )
    common = rng.normal(0.0, 1.0, EVALUATION_SESSIONS)
    idiosyncratic = rng.normal(0.0, 1.0, (EVALUATION_SESSIONS, symbol_count))
    daily_volatility = spec.annual_volatility / sqrt(252)
    segment = (
        spec.annual_drift / 252
        + daily_volatility
        * (
            sqrt(spec.correlation) * common[:, None]
            + sqrt(max(0.0, 1.0 - spec.correlation)) * idiosyncratic
        )
        + 0.00025 * style[None, :]
    )
    benchmark = np.concatenate(
        [
            baseline_common,
            spec.annual_drift / 252 + daily_volatility * common,
        ]
    )
    if spec.style_mode == "invert":
        segment[:50] -= 0.0045 * style[None, :]
        segment[50:] += 0.0015 * style[None, :]
    elif spec.style_mode == "alternate":
        for block_start in range(0, EVALUATION_SESSIONS, 5):
            sign = -1.0 if (block_start // 5) % 2 else 1.0
            segment[block_start : block_start + 5] += sign * 0.0025 * style[None, :]
            benchmark[WARMUP_SESSIONS + block_start : WARMUP_SESSIONS + block_start + 5] += (
                sign * 0.0015
            )
    elif spec.style_mode == "sector":
        segment[10:28, 0:4] -= 0.025
        segment[10:28, 4:8] += 0.008
        segment[35:60, 16:20] += 0.006
        segment[35:60, 20:24] -= 0.006
    elif spec.style_mode == "dispersion":
        for shock_day in (10, 11, 45, 46, 80):
            segment[shock_day, ::2] += 0.12
            segment[shock_day, 1::2] -= 0.14
    for shock_day, shock in spec.shocks:
        if 0 <= shock_day < EVALUATION_SESSIONS:
            segment[shock_day] += shock
            benchmark[WARMUP_SESSIONS + shock_day] += shock
    segment = np.clip(segment, -0.85, 0.50)
    evaluation_benchmark = np.clip(benchmark[WARMUP_SESSIONS:], -0.85, 0.50)
    current_log_return = float(np.log1p(evaluation_benchmark).sum())
    target_log_return = float(np.log1p(spec.target_benchmark_return))
    daily_shift = (target_log_return - current_log_return) / EVALUATION_SESSIONS
    evaluation_benchmark = np.expm1(np.log1p(evaluation_benchmark) + daily_shift)
    segment = np.expm1(np.log1p(segment) + daily_shift)
    benchmark[WARMUP_SESSIONS:] = evaluation_benchmark
    values = np.vstack([baseline, np.clip(segment, -0.85, 0.50)])
    return (
        pd.DataFrame(values, index=index, columns=SYMBOLS),
        pd.Series(benchmark, index=index, name="SYNTHETIC_BENCHMARK"),
    )


def _price_frame(returns: pd.DataFrame) -> pd.DataFrame:
    prices = 100.0 * (1.0 + returns).cumprod()
    frames: list[pd.DataFrame] = []
    for symbol in SYMBOLS:
        frames.append(
            pd.DataFrame(
                {
                    "permanent_security_id": symbol,
                    "ticker": symbol,
                    "trade_date": returns.index,
                    "available_time": [
                        datetime.combine(item.date(), time(20, 30), tzinfo=UTC)
                        for item in returns.index
                    ],
                    "close": prices[symbol].to_numpy(dtype=float),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _factor_metadata() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "permanent_security_id": SYMBOLS,
            "ticker": SYMBOLS,
            "sector": [SECTOR_BY_SYMBOL[symbol] for symbol in SYMBOLS],
            "market_cap": [5_000_000_000.0 * (index + 1) for index in range(len(SYMBOLS))],
        }
    )


def _risk_metadata(spec: SyntheticScenarioSpec) -> tuple[AssetRiskMetadata, ...]:
    market_caps = np.asarray(
        [5_000_000_000.0 * (index + 1) for index in range(len(SYMBOLS))],
        dtype=float,
    )
    log_caps = np.log(market_caps)
    size_scores = (log_caps - log_caps.mean()) / log_caps.std(ddof=1)
    return tuple(
        AssetRiskMetadata(
            symbol=symbol,
            sector=SECTOR_BY_SYMBOL[symbol],
            average_daily_dollar_volume=max(
                50_000.0,
                (80_000_000.0 + index * 5_000_000.0) * spec.liquidity_multiplier,
            ),
            size_score=float(size_scores[index]),
            market_cap=float(market_caps[index]),
        )
        for index, symbol in enumerate(SYMBOLS)
    )


def _authorization(
    decision_time: datetime,
    *,
    start_date: date,
    end_date: date,
    data_version: str,
) -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        purpose=ResearchPurpose.PORTFOLIO_DECISION,
        market="US",
        asset_type="stock",
        start_date=start_date,
        end_date=end_date,
        decision_time=decision_time,
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="SYNTHETIC-PIT-UNIVERSE-V1",
    )
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="synthetic-first-principles",
        provider="deterministic-local-generator",
        source_ids=("flagship-synthetic-stress",),
        latest_available_time=decision_time - timedelta(minutes=1),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="SYNTHETIC-PIT-UNIVERSE-V1",
        universe_available_time=decision_time - timedelta(days=1),
        corporate_actions_complete=True,
        trading_calendar_complete=True,
        missing_rate=0.0,
        anomaly_rate=0.0,
        maximum_missing_rate=0.02,
        maximum_anomaly_rate=0.01,
        data_version=data_version,
        allow_backtest=False,
        allow_display=True,
        allow_portfolio_decision=True,
        dual_source_verified=False,
    )
    return ResearchDataGate().authorize(
        request,
        evidence,
        evaluated_at=decision_time,
    )


def _portfolio_risk_state(
    returns: pd.DataFrame,
    benchmark: pd.Series,
    weights: dict[str, float],
) -> PortfolioRiskState:
    symbols = tuple(symbol for symbol in weights if symbol in returns.columns)
    vector = np.asarray([weights[symbol] for symbol in symbols], dtype=float)
    aligned = returns.loc[:, list(symbols)].dropna(how="any")
    portfolio = aligned.to_numpy(dtype=float) @ vector
    rolling = float(np.std(portfolio[-63:], ddof=1) * sqrt(252))
    wealth = np.cumprod(1.0 + portfolio)
    drawdown = float(wealth[-1] / np.maximum.accumulate(wealth).max() - 1.0)
    pair = pd.concat(
        [pd.Series(portfolio, index=aligned.index, name="portfolio"), benchmark],
        axis=1,
        join="inner",
    ).dropna()
    variance = float(pair.iloc[:, 1].var(ddof=1))
    beta = float(pair.iloc[:, 0].cov(pair.iloc[:, 1]) / variance) if variance > 0 else 0.0
    recent = aligned.iloc[-63:]
    baseline = aligned.iloc[-189:-63]
    if len(symbols) < 2:
        status = CorrelationRiskStatus.NOT_APPLICABLE
        recent_correlation = None
        baseline_correlation = None
    elif len(recent) < 63 or len(baseline) < 126:
        status = CorrelationRiskStatus.NOT_VALIDATED
        recent_correlation = None
        baseline_correlation = None
    else:
        status = CorrelationRiskStatus.VALID
        recent_correlation = _average_correlation(recent)
        baseline_correlation = _average_correlation(baseline)
    return PortfolioRiskState(
        current_drawdown=drawdown,
        rolling_volatility=rolling,
        portfolio_beta=beta,
        concentration_hhi=sum(value * value for value in weights.values()),
        average_correlation=recent_correlation,
        baseline_average_correlation=baseline_correlation,
        correlation_status=status,
        correlation_recent_window=63,
        correlation_baseline_window=126,
        correlation_recent_samples=len(recent),
        correlation_baseline_samples=len(baseline),
    )


def _average_correlation(frame: pd.DataFrame) -> float:
    matrix = frame.corr().to_numpy(dtype=float)
    values = matrix[np.triu_indices(len(frame.columns), 1)]
    return float(np.mean(values))


def _decision_time(timestamp: pd.Timestamp) -> datetime:
    return datetime.combine(timestamp.date(), time(21, 0), tzinfo=UTC)


def _recovery_sessions(wealth: np.ndarray) -> int | None:
    if not len(wealth):
        return None
    peaks = np.maximum.accumulate(wealth)
    drawdowns = wealth / peaks - 1.0
    trough = int(np.argmin(drawdowns))
    prior_peak = float(peaks[trough])
    for index in range(trough + 1, len(wealth)):
        if wealth[index] >= prior_peak:
            return index - trough
    return None


def _run_resilience_checks(*, seed: int) -> dict[str, str]:
    spec = next(item for item in SCENARIOS if item.name == "NORMAL_MIXED_MARKET")
    returns, benchmark = _synthetic_market(spec, seed=seed)
    prices = _price_frame(returns)
    decision_index = WARMUP_SESSIONS - 1
    decision_time = _decision_time(returns.index[decision_index])
    history = returns.iloc[: decision_index + 1]
    benchmark_history = benchmark.iloc[: decision_index + 1]
    strategy_result = USAdaptiveAlphaCoreV1().generate(
        prices=prices.loc[prices["trade_date"] <= returns.index[decision_index]],
        metadata=_factor_metadata(),
        decision_time=decision_time,
        data_version="synthetic-resilience",
        approval=None,
        operational_approval_hash="synthetic-stress-only",
    )
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(
            PortfolioConstraints(model_validation_id="synthetic-stress-validation-v1"),
            operational_mode=True,
        ),
        stress_config=StressRiskConfig(
            validation_id="synthetic-stress-validation-v1",
            provisional_operational=True,
        ),
        operational_mode=True,
    )
    base_input = DailyQuantInput(
        authorization=_authorization(
            decision_time,
            start_date=history.index[0].date(),
            end_date=history.index[-1].date(),
            data_version="synthetic-resilience",
        ),
        decision_time=decision_time,
        alpha_signals=strategy_result.signals,
        returns=history,
        benchmark_returns=benchmark_history,
        risk_metadata=_risk_metadata(spec),
        current_weights=dict(INITIAL_WEIGHTS),
        portfolio_value=100_000.0,
        portfolio_risk_state=_portfolio_risk_state(
            history,
            benchmark_history,
            dict(INITIAL_WEIGHTS),
        ),
        regime=None,
        pit_valid=True,
        universe_snapshot_id="SYNTHETIC-PIT-UNIVERSE-V1",
        data_quality="CERTIFIED",
    )
    future_returns = pd.concat(
        [
            history,
            pd.DataFrame(
                [np.zeros(len(SYMBOLS))],
                index=[returns.index[decision_index] + pd.Timedelta(days=1)],
                columns=SYMBOLS,
            ),
        ]
    )
    future_output = pipeline.run(replace(base_input, returns=future_returns))
    missing_returns = history.copy()
    missing_returns.loc[missing_returns.index[:220], SYMBOLS[0]] = np.nan
    missing_output = pipeline.run(replace(base_input, returns=missing_returns))
    severe_output = pipeline.run(
        replace(
            base_input,
            portfolio_risk_state=replace(
                base_input.portfolio_risk_state,
                current_drawdown=-0.30,
                rolling_volatility=0.70,
            ),
        )
    )
    drift_weights = dict(INITIAL_WEIGHTS)
    drift_weights[SYMBOLS[0]] = 0.123
    drift_output = pipeline.run(replace(base_input, current_weights=drift_weights))
    stale_request = base_input.authorization.request
    stale_evidence = base_input.authorization.evidence
    assert stale_evidence is not None
    stale_decision = ResearchDataGate().evaluate(
        stale_request,
        replace(
            stale_evidence,
            latest_available_time=decision_time - timedelta(days=10),
        ),
        evaluated_at=decision_time,
    )
    identity = ProbabilityOverlayIdentity(
        strategy_version="synthetic",
        strategy_parameter_hash="synthetic",
        research_data_version="synthetic",
        research_data_hash="synthetic",
        universe_version="synthetic",
        probability_model_version="synthetic",
        calibration_version="synthetic",
    )
    probability = apply_probability_overlay(
        strategy_result.signals,
        (),
        artifact=None,
        expected_identity=identity,
        decision_time=decision_time,
    )
    promotion = PromotionEvaluation(
        status=PromotionStatus.PROMOTION_PASS,
        observations=500,
        sample_n=500,
        paired_sample_n=500,
        unique_sessions=200,
        unique_symbols=100,
        unique_events=100,
    )
    llm = fuse_alpha(
        symbol="S00",
        mu_quant=0.02,
        delta_mu_event=-0.50,
        policy=LLMInfluencePolicy(),
        promotion=promotion,
    )
    return {
        "future_timestamp_injection": (
            "PASS_BLOCKED" if future_output.status is ProductionPipelineStatus.BLOCKED else "FAIL"
        ),
        "missing_data_collapse": (
            "PASS_BLOCKED" if missing_output.status is ProductionPipelineStatus.BLOCKED else "FAIL"
        ),
        "severe_risk_sell_only": (
            "PASS_SELL_ONLY_NO_NEW_RISK"
            if severe_output.status is ProductionPipelineStatus.READY
            and severe_output.target is not None
            and severe_output.target.optimization_stage
            is PortfolioOptimizationStage.SELL_ONLY_FALLBACK
            and all(
                severe_output.target.target_weights.get(symbol, 0.0)
                <= base_input.current_weights.get(symbol, 0.0) + 1e-8
                for symbol in SYMBOLS
            )
            and sum(severe_output.target.target_weights.values())
            <= sum(base_input.current_weights.values()) + 1e-8
            else "FAIL"
        ),
        "risk_drift_repair": (
            "PASS_HARD_BREACH_REPAIRED_MANUAL_ONLY"
            if drift_output.status is ProductionPipelineStatus.READY
            and drift_output.risk_drift is not None
            and drift_output.risk_drift.status is RiskDriftStatus.HARD_BREACH
            and drift_output.target is not None
            and drift_output.target.target_weights.get(SYMBOLS[0], 0.0)
            <= pipeline.construction.constraints.maximum_position_weight + 1e-8
            and drift_output.decision is not None
            and not drift_output.decision.automatic_execution_allowed
            else "FAIL"
        ),
        "stale_data_authorization": (
            "PASS_BLOCKED" if stale_decision.blockers else "FAIL"
        ),
        "probability_unavailable_fallback": (
            "PASS_CLASSICAL_UNCHANGED"
            if not probability.active and probability.signals == strategy_result.signals
            else "FAIL"
        ),
        "llm_quant_disagreement": (
            "PASS_ZERO_FORMAL_INFLUENCE"
            if llm.lambda_applied == 0.0 and llm.mu_final == llm.mu_quant
            else "FAIL"
        ),
    }
if __name__ == "__main__":
    output = Path(
        "reports/round60-quant-reliability/flagship_synthetic_stress_after.json"
    )
    write_flagship_stress_summary(run_flagship_synthetic_stress(), output)
    print(output)
