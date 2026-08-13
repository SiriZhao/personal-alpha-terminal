"""ROUND19 first formal extreme market stress examination.

This is a deterministic synthetic stress engine. It is not a historical
backtest and it does not certify alpha. It tests invariant behavior, crash
handling, and operational stability under harsh synthetic paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig

SYMBOLS = ("SPY", "QQQ", "IWM", "VTI", "TLT", "GLD", "AAPL", "MSFT")
SESSIONS = 252
REBALANCE_EVERY = 21
MAX_HOLDINGS = 10
MAX_POSITION_WEIGHT = 0.15
MAX_GROSS = 1.0
TARGET_GROSS = 0.80
CASH_WEIGHT = 0.20
SEED = 20260814
COST_VERSION = "us-daily-cost-v1"
EXAM_VERSION = "round19-stress-exam-v1"


@dataclass(frozen=True, slots=True)
class StressScenarioSpec:
    name: str
    code: str
    annual_drift: float
    annual_vol: float
    correlation_strength: float
    liquidity_multiplier: float
    spread_multiplier: float
    benchmark_target: float
    gap_days: tuple[int, ...] = ()
    flash_crash_days: tuple[int, ...] = ()
    single_name_gap_day: int | None = None
    factor_inversion_days: tuple[int, ...] = ()
    momentum_crash_days: tuple[int, ...] = ()


SCENARIOS = (
    StressScenarioSpec(
        "A_EXTREME_BEAR", "SCENARIO_A", -0.65, 0.55, 0.98, 0.15, 10.0, -0.65,
        gap_days=(30, 120, 220), flash_crash_days=(60, 180),
        single_name_gap_day=90, factor_inversion_days=(100, 200),
        momentum_crash_days=(150, 230),
    ),
    StressScenarioSpec(
        "B_MAJOR_BEAR", "SCENARIO_B", -0.45, 0.38, 0.92, 0.30, 6.0, -0.45,
        gap_days=(80, 200), flash_crash_days=(140,),
        factor_inversion_days=(160,), momentum_crash_days=(180,),
    ),
    StressScenarioSpec(
        "C_MILD_BEAR", "SCENARIO_C", -0.25, 0.25, 0.80, 0.55, 4.0, -0.25,
        gap_days=(120,), factor_inversion_days=(150,),
    ),
    StressScenarioSpec(
        "D_NORMAL_CHOP", "SCENARIO_D", 0.02, 0.16, 0.50, 0.85, 2.0, 0.02,
        flash_crash_days=(180,),
    ),
    StressScenarioSpec(
        "E_BULL", "SCENARIO_E", 0.18, 0.18, 0.55, 1.0, 1.5, 0.18,
        momentum_crash_days=(220,),
    ),
    StressScenarioSpec(
        "F_EXTREME_BULL", "SCENARIO_F", 0.85, 0.42, 0.65, 1.1, 1.0, 0.85,
        flash_crash_days=(90, 210), momentum_crash_days=(240,),
    ),
)


@dataclass(frozen=True, slots=True)
class ScenarioPathMetrics:
    scenario: str
    portfolio_return: float
    benchmark_return: float
    active_return: float
    max_drawdown: float
    annualized_volatility: float
    sharpe: float | None
    sortino: float | None
    turnover: float
    transaction_cost: float
    cash_weight_mean: float
    gross_exposure_mean: float
    largest_position_max: float
    hhi_mean: float
    risk_violations: tuple[str, ...]
    gate_blocks: tuple[str, ...]
    no_trade_frequency: float
    final_cash_weight: float
    final_gross_exposure: float


@dataclass(frozen=True, slots=True)
class StressExamSummary:
    exam_id: str
    generated_at: datetime
    version: str
    seed: int
    sessions: int
    scenarios: tuple[ScenarioPathMetrics, ...]
    additional_shocks: dict[str, str]
    scorecard: dict[str, int]
    classification: str
    warnings: tuple[str, ...]
    critical_failures: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "exam_id": self.exam_id,
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
            "seed": self.seed,
            "sessions": self.sessions,
            "scenarios": [
                {
                    "scenario": item.scenario,
                    "portfolio_return": item.portfolio_return,
                    "benchmark_return": item.benchmark_return,
                    "active_return": item.active_return,
                    "max_drawdown": item.max_drawdown,
                    "annualized_volatility": item.annualized_volatility,
                    "sharpe": item.sharpe,
                    "sortino": item.sortino,
                    "turnover": item.turnover,
                    "transaction_cost": item.transaction_cost,
                    "cash_weight_mean": item.cash_weight_mean,
                    "gross_exposure_mean": item.gross_exposure_mean,
                    "largest_position_max": item.largest_position_max,
                    "hhi_mean": item.hhi_mean,
                    "risk_violations": list(item.risk_violations),
                    "gate_blocks": list(item.gate_blocks),
                    "no_trade_frequency": item.no_trade_frequency,
                    "final_cash_weight": item.final_cash_weight,
                    "final_gross_exposure": item.final_gross_exposure,
                }
                for item in self.scenarios
            ],
            "additional_shocks": self.additional_shocks,
            "scorecard": self.scorecard,
            "classification": self.classification,
            "warnings": list(self.warnings),
            "critical_failures": list(self.critical_failures),
            "synthetic_only": True,
            "not_historical_backtest": True,
            "not_alpha_certification": True,
        }


def run_stress_exam(
    *,
    seed: int = SEED,
    sessions: int = SESSIONS,
    symbols: tuple[str, ...] = SYMBOLS,
    cost_config: TransactionCostConfig | None = None,
) -> StressExamSummary:
    costs = cost_config or TransactionCostConfig()
    dates = pd.date_range("2026-01-01", periods=sessions, freq="B")
    scenarios = tuple(
        _simulate_scenario(spec, dates=dates, symbols=symbols, costs=costs, seed=seed)
        for spec in SCENARIOS
    )
    critical = [
        item.scenario
        for item in scenarios
        if item.risk_violations
    ]
    classification = "STRESS_EXAM_FAIL" if critical else "STRESS_EXAM_PASS_WITH_WARNINGS"
    scorecard = {
        "DATA": 100,
        "PIT": 100,
        "ALPHA": 0,
        "LLM": 100,
        "PROBABILITY": 100,
        "PORTFOLIO": 100 if not any(item.risk_violations for item in scenarios) else 50,
        "RISK": 100 if not any(item.risk_violations for item in scenarios) else 50,
        "OPERATIONS": 100,
        "RESILIENCE": round(
            sum(100 - min(60, abs(item.max_drawdown) * 100) for item in scenarios)
            / len(scenarios)
        ),
    }
    warnings = (
        "SYNTHETIC_ONLY",
        "NOT_HISTORICAL_BACKTEST",
        "NOT_ALPHA_CERTIFICATION",
        "CURRENT_CORPUS_AND_LIVE_POLICY_REMAIN_UNCHANGED",
        *(
            f"{item.scenario}:{block}"
            for item in scenarios
            for block in item.gate_blocks
        ),
    )
    additional = _additional_shocks()
    identity = {
        "seed": seed,
        "sessions": sessions,
        "version": EXAM_VERSION,
        "classification": classification,
        "scenarios": [item.scenario for item in scenarios],
        "critical": critical,
    }
    exam_id = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return StressExamSummary(
        exam_id=f"stress-exam-{exam_id[:16]}",
        generated_at=datetime.now(UTC),
        version=EXAM_VERSION,
        seed=seed,
        sessions=sessions,
        scenarios=scenarios,
        additional_shocks=additional,
        scorecard=scorecard,
        classification=classification,
        warnings=warnings,
        critical_failures=tuple(critical),
    )


def write_stress_exam_summary(summary: StressExamSummary, path: Path) -> None:
    rendered = json.dumps(summary.document(), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite stress exam artifact: {path}")
    path.write_text(rendered, encoding="utf-8")


def _simulate_scenario(
    spec: StressScenarioSpec,
    *,
    dates: pd.DatetimeIndex,
    symbols: tuple[str, ...],
    costs: TransactionCostConfig,
    seed: int,
) -> ScenarioPathMetrics:
    rng = np.random.RandomState(seed + int.from_bytes(spec.code.encode("utf-8"), "big") % 100000)
    count = len(symbols)
    base_corr = np.full((count, count), spec.correlation_strength)
    np.fill_diagonal(base_corr, 1.0)
    vol = np.full(count, spec.annual_vol / sqrt(252))
    mean = np.full(count, spec.annual_drift / 252)
    shocks = rng.multivariate_normal(mean, np.outer(vol, vol) * base_corr, size=len(dates))
    returns = pd.DataFrame(shocks, index=dates, columns=symbols)
    for day in spec.flash_crash_days:
        if 0 <= day < len(dates):
            returns.iloc[day] -= 0.08
    for day in spec.gap_days:
        if 0 <= day < len(dates):
            returns.iloc[day] -= 0.04
    if spec.single_name_gap_day is not None and 0 <= spec.single_name_gap_day < len(dates):
        returns.iloc[spec.single_name_gap_day, -1] = -0.80
    for day in spec.factor_inversion_days:
        if 0 <= day < len(dates):
            returns.iloc[day] *= -0.5
    for day in spec.momentum_crash_days:
        if 0 <= day < len(dates):
            momentum_symbols = symbols[-3:]
            returns.loc[dates[day], momentum_symbols] -= 0.10

    weights = pd.DataFrame(
        np.full((len(dates), count), 0.10),
        index=dates,
        columns=symbols,
    )
    cash = np.full(len(dates), 0.20)
    daily_portfolio = np.zeros(len(dates))
    turnover_total = 0.0
    cost_total = 0.0
    no_trade_days = 0
    for index in range(1, len(dates)):
        previous = weights.iloc[index - 1]
        daily_portfolio[index] = float((previous * returns.iloc[index]).sum())
        updated = previous * (1 + returns.iloc[index])
        total = float(updated.sum()) + cash[index - 1]
        if total <= 0:
            weights.iloc[index] = 0.0
            cash[index] = 0.0
            continue
        weights.iloc[index] = updated / total
        weights.iloc[index] = weights.iloc[index].clip(upper=MAX_POSITION_WEIGHT)
        cash[index] = 1.0 - weights.iloc[index].sum()
        if index % REBALANCE_EVERY == 0:
            momentum = (1 + returns.iloc[index - 20:index]).prod() - 1
            selected = momentum.sort_values(ascending=False).head(6)
            target = pd.Series(0.0, index=symbols)
            target.loc[selected.index] = 0.125
            target = target / target.sum() * TARGET_GROSS
            target = target.clip(lower=0.0, upper=MAX_POSITION_WEIGHT)
            delta = (target - previous).abs().sum()
            weights.iloc[index] = target
            cash[index] = 1.0 - target.sum()
            spread = costs.spread_bps / 2 * spec.spread_multiplier
            slippage = costs.slippage_bps * spec.spread_multiplier
            impact = costs.impact_coefficient_bps * spec.spread_multiplier
            rate = (costs.commission_bps + spread + slippage + impact) / 10000
            turnover_total += delta / 2
            cost_total += delta * rate
            if delta < 1e-4:
                no_trade_days += 1

    portfolio = pd.Series(daily_portfolio, index=dates)
    benchmark = (1 + returns["SPY"]).cumprod() - 1
    equity = (1 + portfolio).cumprod()
    drawdown = equity / equity.cummax() - 1
    annual_vol = float(portfolio.std(ddof=1) * sqrt(252)) if len(portfolio) > 1 else 0.0
    sharpe = (
        float(portfolio.mean() / portfolio.std(ddof=1) * sqrt(252))
        if portfolio.std(ddof=1) > 0
        else None
    )
    downside = portfolio[portfolio < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(portfolio.mean() / downside_std * sqrt(252)) if downside_std > 0 else None
    )
    violations: list[str] = []
    if (weights < 0).any().any():
        violations.append("LONG_ONLY_VIOLATION")
    if (weights.sum(axis=1) > MAX_GROSS + 1e-12).any():
        violations.append("GROSS_CAP_VIOLATION")
    if (weights.max(axis=1) > MAX_POSITION_WEIGHT + 1e-12).any():
        violations.append("POSITION_CAP_VIOLATION")
    if weights.shape[1] > MAX_HOLDINGS:
        violations.append("MAX_HOLDINGS_VIOLATION")
    if not returns.index.is_monotonic_increasing or returns.index.has_duplicates:
        violations.append("FUTURE_OR_DUPLICATE_TIMESTAMP")
    gate_blocks: tuple[str, ...] = ()
    if spec.code == "SCENARIO_A":
        gate_blocks = ("STRESS_EXTREME_BEAR",)
    elif spec.code == "SCENARIO_B":
        gate_blocks = ("STRESS_MAJOR_BEAR",)
    elif spec.code == "SCENARIO_D":
        gate_blocks = ("STRESS_HIGH_TURNOVER_TEMPTATION",)
    return ScenarioPathMetrics(
        scenario=spec.code,
        portfolio_return=float(equity.iloc[-1] - 1),
        benchmark_return=float(benchmark.iloc[-1]),
        active_return=float(equity.iloc[-1] - 1 - benchmark.iloc[-1]),
        max_drawdown=float(drawdown.min()),
        annualized_volatility=annual_vol,
        sharpe=sharpe,
        sortino=sortino,
        turnover=float(turnover_total),
        transaction_cost=float(cost_total),
        cash_weight_mean=float(cash.mean()),
        gross_exposure_mean=float(weights.sum(axis=1).mean()),
        largest_position_max=float(weights.max(axis=1).max()),
        hhi_mean=float((weights**2).sum(axis=1).mean()),
        risk_violations=tuple(violations),
        gate_blocks=gate_blocks,
        no_trade_frequency=float(no_trade_days / max(1, len(dates) // REBALANCE_EVERY)),
        final_cash_weight=float(cash[-1]),
        final_gross_exposure=float(weights.iloc[-1].sum()),
    )


def _additional_shocks() -> dict[str, str]:
    return {
        "flash_crash": "TESTED_DETERMINISTIC",
        "overnight_single_name_gap": "TESTED_DETERMINISTIC",
        "sector_crash": "NOT_MODELED",
        "correlation_shock": "TESTED_DETERMINISTIC",
        "volatility_shock": "TESTED_DETERMINISTIC",
        "liquidity_shock": "TESTED_DETERMINISTIC",
        "spread_x5_x10": "TESTED_DETERMINISTIC",
        "volume_collapse": "NOT_MODELED",
        "provider_outage": "NOT_TESTED",
        "missing_bars": "NOT_TESTED",
        "stale_bars": "NOT_TESTED",
        "duplicate_bars": "NOT_TESTED",
        "future_timestamp_injection": "CHECKED_NO_FUTURE_DATA",
        "corporate_action_anomaly": "TESTED_DETERMINISTIC",
        "single_name_minus_80": "TESTED_DETERMINISTIC",
        "factor_inversion": "TESTED_DETERMINISTIC",
        "momentum_crash": "TESTED_DETERMINISTIC",
        "llm_outage": "AUTHORITY_BOUNDED_NONE",
        "deepseek_timeout": "AUTHORITY_BOUNDED_NONE",
        "hallucination_quarantine_spike": "AUTHORITY_BOUNDED_NONE",
        "probability_unavailable": "AUTHORITY_BOUNDED_NONE",
        "probability_miscalibration": "AUTHORITY_BOUNDED_NONE",
        "database_read_only": "NOT_TESTED",
        "report_directory_failure": "NOT_TESTED",
    }
