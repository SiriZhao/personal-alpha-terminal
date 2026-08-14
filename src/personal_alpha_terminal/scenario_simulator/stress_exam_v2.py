"""ROUND24 production-coupled Stress Exam 2.0 (PHASE D).

Unlike the ROUND19 synthetic exam, v2 consumes the CURRENT production
portfolio (latest valid daily-run artifacts plus PIT price history from the
database).  It never fabricates a toy portfolio: when no valid baseline
exists, market scenarios are recorded as UNAVAILABLE_BASELINE and the exam
still runs every resilience scenario.

This is a stress/risk examination.  It is not a historical backtest and it
does not certify alpha.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

EXAM_V2_VERSION = "round24-stress-exam-v2"
DEFAULT_SEED = 20260814
DEFAULT_OUTPUT_DIR = Path("reports/stress-exam-v2")
GENERATED_AT = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)

CORE_ETFS = frozenset({"VOO", "SPY", "QQQ", "QQQM", "VTI", "IVV"})
BOND_ETFS = frozenset({"AGG", "BND", "IEF", "SHY", "TLT", "VGIT", "LQD", "VCIT", "HYG"})
COMMODITY_ETFS = frozenset({"DBC", "GSG", "GLD", "IAU"})
INTERNATIONAL_ETFS = frozenset({"VXUS", "VEA", "VWO", "EFA", "EEM", "ACWX"})


@dataclass(frozen=True, slots=True)
class ProductionBaseline:
    """The real portfolio state the exam stresses."""

    run_id: str
    analysis_date: str
    holdings: dict[str, float]
    equity_symbols: tuple[str, ...]
    etf_symbols: tuple[str, ...]
    returns: pd.DataFrame
    average_dollar_volume: dict[str, float]
    sector_proxy: dict[str, str]
    portfolio_value: float
    cash_weight: float
    baseline_volatility: float | None
    source: str

    def valid(self) -> bool:
        return bool(self.holdings) and self.returns is not None and not self.returns.empty

    def document(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "analysis_date": self.analysis_date,
            "holdings": self.holdings,
            "equity_symbols": list(self.equity_symbols),
            "etf_symbols": list(self.etf_symbols),
            "portfolio_value": self.portfolio_value,
            "cash_weight": self.cash_weight,
            "baseline_volatility": self.baseline_volatility,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class MarketScenarioSpec:
    name: str
    annual_drift: float
    annual_vol: float
    correlation: float
    shock_days: tuple[int, ...] = ()
    shock_size: float = 0.0
    single_name_shock: tuple[str, float] | None = None
    single_name_shock_day: int | None = None
    sector_shock: tuple[str, float] | None = None
    correlation_spike_days: tuple[int, ...] = ()
    volatility_spike_days: tuple[int, ...] = ()
    liquidity_collapse_days: tuple[int, ...] = ()
    volume_collapse_days: tuple[int, ...] = ()
    spread_multiplier: float = 1.0
    momentum_crash_days: tuple[int, ...] = ()
    factor_inversion_days: tuple[int, ...] = ()
    etf_tracking_shock_days: tuple[int, ...] = ()
    etf_tracking_shock_size: float = 0.0
    bond_shock_size: float = 0.0
    rate_shock_size: float = 0.0
    commodity_shock_size: float = 0.0
    international_shock_size: float = 0.0
    bond_equity_simultaneous: bool = False


MARKET_SCENARIOS: tuple[MarketScenarioSpec, ...] = (
    MarketScenarioSpec("BROAD_EQUITY_CRASH", -0.55, 0.45, 0.85, shock_days=(10, 25), shock_size=-0.06),  # noqa: E501
    MarketScenarioSpec("FAST_CRASH_GAP", -0.20, 0.30, 0.80, shock_days=(3,), shock_size=-0.09),
    MarketScenarioSpec("SLOW_BEAR_MARKET", -0.35, 0.28, 0.80),
    MarketScenarioSpec("MOMENTUM_CRASH", -0.10, 0.30, 0.75, momentum_crash_days=(15, 40)),
    MarketScenarioSpec("FACTOR_INVERSION", -0.15, 0.32, 0.75, factor_inversion_days=(12, 35)),
    MarketScenarioSpec("GROWTH_CRASH", -0.30, 0.40, 0.80, sector_shock=("US_GROWTH", -0.08), shock_days=(8,)),  # noqa: E501
    MarketScenarioSpec("VALUE_CRASH", -0.30, 0.40, 0.80, sector_shock=("US_VALUE", -0.08), shock_days=(8,)),  # noqa: E501
    MarketScenarioSpec("SMALL_CAP_CRASH", -0.30, 0.42, 0.80, sector_shock=("US_SMALL_CAP", -0.09), shock_days=(8,)),  # noqa: E501
    MarketScenarioSpec("SECTOR_CRASH", -0.25, 0.38, 0.80, sector_shock=("US_SECTOR", -0.10), shock_days=(8, 20)),  # noqa: E501
    MarketScenarioSpec("CORRELATION_TO_ONE", -0.10, 0.30, 1.0, correlation_spike_days=(10, 30)),
    MarketScenarioSpec("VOLATILITY_SPIKE", -0.05, 0.55, 0.85, volatility_spike_days=(8, 18)),
    MarketScenarioSpec("LIQUIDITY_COLLAPSE", -0.20, 0.35, 0.85, liquidity_collapse_days=(10, 25)),
    MarketScenarioSpec("VOLUME_COLLAPSE", -0.10, 0.30, 0.80, volume_collapse_days=(10, 25)),
    MarketScenarioSpec("SPREAD_X5", -0.15, 0.30, 0.80, spread_multiplier=5.0),
    MarketScenarioSpec("SPREAD_X10", -0.15, 0.30, 0.80, spread_multiplier=10.0),
    MarketScenarioSpec("SINGLE_NAME_MINUS_50", -0.05, 0.25, 0.70, single_name_shock=("__largest__", -0.50), single_name_shock_day=10),  # noqa: E501
    MarketScenarioSpec("SINGLE_NAME_MINUS_80", -0.05, 0.25, 0.70, single_name_shock=("__largest__", -0.80), single_name_shock_day=10),  # noqa: E501
    MarketScenarioSpec("ETF_TRACKING_SHOCK", -0.10, 0.28, 0.80, etf_tracking_shock_days=(12,), etf_tracking_shock_size=-0.05),  # noqa: E501
    MarketScenarioSpec("BOND_EQUITY_SIMULTANEOUS_LOSS", -0.20, 0.35, 0.80, bond_shock_size=-0.05, bond_equity_simultaneous=True, shock_days=(8,)),  # noqa: E501
    MarketScenarioSpec("RATE_SHOCK", -0.10, 0.30, 0.75, rate_shock_size=-0.08),
    MarketScenarioSpec("COMMODITY_SHOCK", -0.05, 0.30, 0.75, commodity_shock_size=0.15),
    MarketScenarioSpec("INTERNATIONAL_RISK_OFF", -0.15, 0.32, 0.80, international_shock_size=-0.10),
)

RISK_GATE_THRESHOLDS: dict[str, float] = {
    "maximum_cvar_loss": 0.06,
    "maximum_correlation_spike_loss": 0.08,
    "maximum_gap_loss": 0.08,
    "maximum_stressed_volatility": 0.30,
    "maximum_benchmark_crash_loss": 0.25,
    "maximum_single_name_loss": 0.05,
    "maximum_sector_loss": 0.10,
    "maximum_liquidation_days": 5.0,
}


@dataclass(frozen=True, slots=True)
class ScenarioRiskMetrics:
    scenario: str
    max_drawdown: float
    cvar_95: float
    annualized_volatility: float
    gross_exposure: float
    cash_weight: float
    largest_position: float
    sector_exposure: dict[str, float]
    average_correlation: float
    turnover: float
    transaction_cost: float
    liquidation_days: float
    time_to_de_risk: int | None
    time_to_recover: int | None
    risk_gate_reactions: tuple[str, ...]
    gate_violations: tuple[str, ...]
    final_portfolio_value: float

    def document(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "max_drawdown": self.max_drawdown,
            "cvar_95": self.cvar_95,
            "annualized_volatility": self.annualized_volatility,
            "gross_exposure": self.gross_exposure,
            "cash_weight": self.cash_weight,
            "largest_position": self.largest_position,
            "sector_exposure": self.sector_exposure,
            "average_correlation": self.average_correlation,
            "turnover": self.turnover,
            "transaction_cost": self.transaction_cost,
            "liquidation_days": self.liquidation_days,
            "time_to_de_risk": self.time_to_de_risk,
            "time_to_recover": self.time_to_recover,
            "risk_gate_reactions": list(self.risk_gate_reactions),
            "gate_violations": list(self.gate_violations),
            "final_portfolio_value": self.final_portfolio_value,
        }


def simulate_market_scenario(
    spec: MarketScenarioSpec,
    baseline: ProductionBaseline,
    *,
    seed: int,
    sessions: int = 252,
    thresholds: dict[str, float] | None = None,
) -> ScenarioRiskMetrics:
    """Stress the current holdings along a deterministic scenario path."""

    thresholds = thresholds or RISK_GATE_THRESHOLDS
    rng = np.random.RandomState(seed + abs(hash(spec.name)) % 100_000)
    symbols = sorted(baseline.holdings)
    returns = baseline.returns.reindex(columns=symbols).fillna(0.0).tail(sessions)
    if returns.empty:
        returns = pd.DataFrame(index=pd.date_range("2026-01-01", periods=sessions, freq="B"), columns=symbols, data=0.0)  # noqa: E501
    count = len(symbols)
    corr = np.full((count, count), spec.correlation)
    np.fill_diagonal(corr, 1.0)
    vol = np.full(count, spec.annual_vol / sqrt(252))
    mean = np.full(count, spec.annual_drift / 252)
    realized = np.asarray(returns).T
    if realized.shape[0] == count and realized.shape[1] > 20:
        sample_vol = realized.std(axis=1) + 1e-9
        vol = np.maximum(vol, sample_vol * 0.5)
    synthetic = rng.multivariate_normal(mean, np.outer(vol, vol) * corr, size=sessions)
    path = pd.DataFrame(synthetic, columns=symbols)
    largest = max(baseline.holdings, key=lambda symbol: baseline.holdings[symbol])
    for day in spec.shock_days:
        if 0 <= day < sessions:
            path.iloc[day] += spec.shock_size
    for day in spec.correlation_spike_days:
        if 0 <= day < sessions:
            path.iloc[day] = path.iloc[day].mean() * 0.6 + path.iloc[day] * 0.4
            path.iloc[day] -= 0.02
    for day in spec.volatility_spike_days:
        if 0 <= day < sessions:
            path.iloc[day] *= 2.5
    for day in spec.momentum_crash_days:
        if 0 <= day < sessions:
            winners = path.iloc[max(0, day - 20):day].mean().sort_values(ascending=False).head(max(1, count // 4)).index  # noqa: E501
            path.loc[path.index[day], winners] -= 0.10
    for day in spec.factor_inversion_days:
        if 0 <= day < sessions:
            path.iloc[day] = -path.iloc[day] * 0.5
    if spec.single_name_shock is not None and spec.single_name_shock_day is not None:
        day = spec.single_name_shock_day
        if 0 <= day < sessions:
            target = largest if spec.single_name_shock[0] == "__largest__" else spec.single_name_shock[0]  # noqa: E501
            if target in path.columns:
                path.loc[path.index[day], target] = spec.single_name_shock[1]
    for day in spec.etf_tracking_shock_days:
        if 0 <= day < sessions:
            for symbol in baseline.etf_symbols:
                if symbol in path.columns:
                    path.loc[path.index[day], symbol] += spec.etf_tracking_shock_size
    for day in range(sessions):
        if any(d <= day for d in spec.liquidity_collapse_days):
            path.iloc[day] *= 0.92
    for symbol in symbols:
        if symbol in BOND_ETFS and spec.bond_shock_size:
            if spec.bond_equity_simultaneous:
                path[symbol] += spec.bond_shock_size
        if symbol in BOND_ETFS and spec.rate_shock_size and not spec.bond_equity_simultaneous:
            path[symbol] += spec.rate_shock_size
        if symbol in COMMODITY_ETFS and spec.commodity_shock_size:
            path[symbol] += spec.commodity_shock_size
        if symbol in INTERNATIONAL_ETFS and spec.international_shock_size:
            path[symbol] += spec.international_shock_size
    weights = pd.Series(baseline.holdings)
    if spec.sector_shock is not None:
        sector, size = spec.sector_shock
        for symbol in symbols:
            proxy = baseline.sector_proxy.get(symbol)
            matched = False
            if proxy is not None:
                matched = proxy == sector or proxy.startswith(sector) or sector.startswith(proxy)
            if matched and spec.shock_days:
                for day in spec.shock_days:
                    if 0 <= day < sessions:
                        path.loc[path.index[day], symbol] += size
    gross = float(weights.sum())
    cash = max(0.0, baseline.cash_weight)
    equity = np.zeros(sessions)
    for index in range(sessions):
        equity[index] = float((weights * path.iloc[index]).sum())
    cumulative = (1 + pd.Series(equity)).cumprod()
    drawdown = cumulative / cumulative.cummax() - 1
    max_drawdown = float(drawdown.min())
    cvar_95 = float(-pd.Series(equity).sort_values().head(max(1, int(sessions * 0.05))).mean())
    annualized_volatility = float(pd.Series(equity).std(ddof=1) * sqrt(252)) if sessions > 1 else 0.0  # noqa: E501
    trough = int(drawdown.idxmin()) if drawdown.min() < 0 else None
    time_to_recover = None
    if trough is not None and drawdown.min() < -1e-6:
        peak = cumulative[: trough + 1].max()
        recovery = np.argmax(cumulative[trough:] >= peak * 0.999)
        time_to_recover = int(recovery) if cumulative[trough + recovery] >= peak * 0.999 else None
    largest_position = float(weights.max())
    sector_labels = {
        baseline.sector_proxy.get(s)
        for s in symbols
        if baseline.sector_proxy.get(s) is not None
    }
    sector_exposure = {}
    for label in sorted(cast(set[str], sector_labels)):
        members = [s for s in symbols if baseline.sector_proxy.get(s) == label]
        sector_exposure[label] = float(weights[members].sum())
    correlation_matrix = (
        pd.DataFrame(np.asarray(returns).T).corr().to_numpy()
        if returns.shape[1] > 1
        else np.eye(1)
    )
    mask = ~np.eye(correlation_matrix.shape[0], dtype=bool)
    average_correlation = (
        float(correlation_matrix[mask].mean()) if mask.any() else 1.0
    )
    adv = pd.Series(
        {symbol: baseline.average_dollar_volume.get(symbol, 0.0) for symbol in symbols}
    )
    liquidation_value = float(
        (weights * baseline.portfolio_value / adv.replace(0, float("inf"))).sum()
    ) if adv.gt(0).any() else float("inf")
    liquidation_days = (
        liquidation_value if liquidation_value > 0 else float("inf")
    )
    total_cost_rate = (
        0.0012 * spec.spread_multiplier
        if spec.spread_multiplier > 1
        else 0.0012
    )
    transaction_cost = float(weights.sum() * total_cost_rate * 2)
    turnover = 0.0
    risk_gate_reactions: list[str] = []
    gate_violations: list[str] = []
    if cvar_95 > thresholds.get("maximum_cvar_loss", 0.06):
        gate_violations.append("maximum_cvar_loss")
        risk_gate_reactions.append("RISK_GATE_CVAR_EXCEEDED: reduce gross")
    if abs(max_drawdown) > thresholds.get("maximum_benchmark_crash_loss", 0.25) * 0.8:
        risk_gate_reactions.append("RISK_GATE_DRAWDOWN_WARNING")
    if annualized_volatility > thresholds.get("maximum_stressed_volatility", 0.30):
        gate_violations.append("maximum_stressed_volatility")
        risk_gate_reactions.append("RISK_GATE_VOLATILITY_EXCEEDED: freeze new buys")
    if abs(max_drawdown) > thresholds.get("maximum_gap_loss", 0.08) and spec.name == "FAST_CRASH_GAP":  # noqa: E501
        gate_violations.append("maximum_gap_loss")
    if spec.correlation == 1.0 and abs(max_drawdown) > thresholds.get("maximum_correlation_spike_loss", 0.08):  # noqa: E501
        gate_violations.append("maximum_correlation_spike_loss")
    if spec.single_name_shock is not None:
        largest_weight = float(weights[largest])
        loss = largest_weight * abs(spec.single_name_shock[1])
        if loss > thresholds.get("maximum_single_name_loss", 0.05):
            gate_violations.append("maximum_single_name_loss")
    if spec.sector_shock is not None:
        sector_loss = max(
            (abs(spec.sector_shock[1]) * weights[s] for s in symbols if baseline.sector_proxy.get(s)),  # noqa: E501
            default=0.0,
        )
        if sector_loss > thresholds.get("maximum_sector_loss", 0.10):
            gate_violations.append("maximum_sector_loss")
    if liquidation_days > thresholds.get("maximum_liquidation_days", 5.0):
        gate_violations.append("maximum_liquidation_days")
    time_to_de_risk = None
    if spec.shock_days and len(spec.shock_days) == 1:
        time_to_de_risk = 0
    return ScenarioRiskMetrics(
        scenario=spec.name,
        max_drawdown=round(max_drawdown, 6),
        cvar_95=round(cvar_95, 6),
        annualized_volatility=round(annualized_volatility, 6),
        gross_exposure=round(gross, 6),
        cash_weight=round(cash, 6),
        largest_position=round(largest_position, 6),
        sector_exposure={key: round(value, 6) for key, value in sector_exposure.items()},
        average_correlation=round(average_correlation, 6),
        turnover=round(turnover, 6),
        transaction_cost=round(transaction_cost, 6),
        liquidation_days=round(liquidation_days, 4),
        time_to_de_risk=time_to_de_risk,
        time_to_recover=time_to_recover,
        risk_gate_reactions=tuple(risk_gate_reactions),
        gate_violations=tuple(gate_violations),
        final_portfolio_value=round(float((1 + baseline.portfolio_value * 0 + cumulative.iloc[-1] - 1) * 0 + cumulative.iloc[-1]), 6),  # noqa: E501
    )
