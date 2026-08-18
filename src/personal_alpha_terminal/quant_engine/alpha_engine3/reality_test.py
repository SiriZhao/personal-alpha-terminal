"""ROUND68 aligned Alpha Engine 3 economic diagnostics.

The calculations are research diagnostics only.  They do not alter the
production champion or authorize promotion.  Inputs must already share the
same universe, decision cutoffs, raw execution assumptions, costs, benchmarks,
and accounting rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, sqrt
from random import Random

import numpy as np

from personal_alpha_terminal.research.data_evidence import (
    DataEvidenceInventory,
    EvidenceStatus,
    LockedOOSManifest,
    assess_locked_oos,
    default_inventory,
    evaluate_data_evidence,
)


class RealityTestVerdict(StrEnum):
    PROMOTE = "PROMOTE"
    RETAIN_CHAMPION = "RETAIN_CHAMPION"
    CHALLENGER_ONLY = "CHALLENGER_ONLY"
    BLOCKED_INSUFFICIENT_OOS = "BLOCKED_INSUFFICIENT_OOS"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"


class MarketRegime(StrEnum):
    CRISIS = "CRISIS"
    BEAR = "BEAR"
    DEFENSIVE = "DEFENSIVE"
    NORMAL = "NORMAL"
    BULL = "BULL"
    STRONG_BULL = "STRONG_BULL"


@dataclass(frozen=True, slots=True)
class AlignedPerformanceObservation:
    session: date
    champion_return: float
    challenger_return: float
    spy_return: float
    qqq_return: float
    champion_exposure: float
    challenger_exposure: float
    champion_turnover: float
    challenger_turnover: float
    champion_cost: float
    challenger_cost: float
    champion_concentration: float
    challenger_concentration: float
    decisions: int = 0
    risk_targeted_exposure: float | None = None
    adaptive_exposure: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.champion_return,
            self.challenger_return,
            self.spy_return,
            self.qqq_return,
            self.champion_exposure,
            self.challenger_exposure,
            self.champion_turnover,
            self.challenger_turnover,
            self.champion_cost,
            self.challenger_cost,
            self.champion_concentration,
            self.challenger_concentration,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("aligned observation values must be finite")
        if any(not 0 <= value <= 1 for value in (
            self.champion_exposure,
            self.challenger_exposure,
            self.champion_concentration,
            self.challenger_concentration,
        )):
            raise ValueError("exposure and concentration must be in [0, 1]")
        if min(self.champion_turnover, self.challenger_turnover) < 0:
            raise ValueError("turnover cannot be negative")
        if min(self.champion_cost, self.challenger_cost) < 0:
            raise ValueError("cost cannot be negative")
        if self.decisions < 0:
            raise ValueError("decision count cannot be negative")
        for value in (self.risk_targeted_exposure, self.adaptive_exposure):
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError("counterfactual exposure must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class EconomicMetrics:
    observations: int
    total_return: float
    annualized_return: float | None
    excess_vs_spy: float
    excess_vs_qqq: float
    sharpe: float | None
    sortino: float | None
    information_ratio: float | None
    maximum_drawdown: float
    volatility: float | None
    downside_deviation: float | None
    turnover: float
    estimated_cost: float
    average_invested_exposure: float
    average_cash_allocation: float
    average_concentration: float
    hit_rate: float | None
    average_winner: float | None
    average_loser: float | None
    benchmark_beta: float | None
    tracking_error: float | None
    upside_capture: float | None
    downside_capture: float | None
    up_market_participation: float | None
    down_market_protection: float | None
    bull_market_opportunity_loss: float
    cash_drag: float
    underexposure_drag: float
    selection_alpha: float
    timing_alpha: float
    cost_drag: float
    bootstrap_active_interval: tuple[float, float] | None


@dataclass(frozen=True, slots=True)
class RegimeMetrics:
    regime: MarketRegime
    observations: int
    return_value: float
    benchmark_return: float
    excess_return: float
    exposure: float
    drawdown: float
    turnover: float
    decisions: int
    opportunity_loss: float
    downside_protection: float | None


@dataclass(frozen=True, slots=True)
class ExposureCounterfactual:
    name: str
    total_return: float
    excess_vs_spy: float
    average_exposure: float
    cash_drag: float
    underexposure_drag: float


@dataclass(frozen=True, slots=True)
class AlphaEngine3RealityTest:
    verdict: RealityTestVerdict
    evidence_status: EvidenceStatus
    locked_oos_status: EvidenceStatus
    diagnostic_only: bool
    blockers: tuple[str, ...]
    champion: EconomicMetrics
    challenger: EconomicMetrics
    challenger_minus_champion: dict[str, float | None]
    champion_regimes: tuple[RegimeMetrics, ...]
    challenger_regimes: tuple[RegimeMetrics, ...]
    challenger_counterfactuals: tuple[ExposureCounterfactual, ...]

    def document(self) -> dict[str, object]:
        return asdict(self)


def run_alpha_engine3_reality_test(
    observations: tuple[AlignedPerformanceObservation, ...],
    *,
    inventory: DataEvidenceInventory | None = None,
    locked_oos_manifest: LockedOOSManifest | None = None,
    bootstrap_samples: int = 400,
    random_seed: int = 20260818,
) -> AlphaEngine3RealityTest:
    """Evaluate aligned performance without opening or tuning locked OOS data."""

    if len(observations) < 2:
        raise ValueError("reality test requires at least two aligned observations")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")
    ordered = tuple(sorted(observations, key=lambda item: item.session))
    if len({item.session for item in ordered}) != len(ordered):
        raise ValueError("aligned observations must have unique sessions")
    evidence = evaluate_data_evidence(inventory or default_inventory())
    locked = assess_locked_oos(locked_oos_manifest)
    champion = _metrics(
        ordered,
        strategy="champion",
        bootstrap_samples=bootstrap_samples,
        seed=random_seed,
    )
    challenger = _metrics(
        ordered,
        strategy="challenger",
        bootstrap_samples=bootstrap_samples,
        seed=random_seed + 1,
    )
    blockers = list(evidence.blockers)
    if locked is not EvidenceStatus.PASS:
        blockers.append("LOCKED_OOS_NOT_CERTIFIABLE")
    if evidence.overall_status is EvidenceStatus.BLOCKED_DATA_QUALITY:
        verdict = RealityTestVerdict.BLOCKED_DATA_QUALITY
    elif locked is not EvidenceStatus.PASS:
        verdict = RealityTestVerdict.BLOCKED_INSUFFICIENT_OOS
    else:
        verdict = RealityTestVerdict.CHALLENGER_ONLY
    return AlphaEngine3RealityTest(
        verdict=verdict,
        evidence_status=evidence.overall_status,
        locked_oos_status=locked,
        diagnostic_only=verdict is not RealityTestVerdict.PROMOTE,
        blockers=tuple(dict.fromkeys(blockers)),
        champion=champion,
        challenger=challenger,
        challenger_minus_champion=_difference(challenger, champion),
        champion_regimes=_regime_metrics(ordered, strategy="champion"),
        challenger_regimes=_regime_metrics(ordered, strategy="challenger"),
        challenger_counterfactuals=_counterfactuals(ordered),
    )


def compact_reality_status(result: AlphaEngine3RealityTest) -> str:
    """Return the compact operator-facing diagnostic; details stay in research reports."""

    return (
        "ALPHA ENGINE 3 REALITY | "
        f"status={result.verdict.value} | "
        f"participation={result.challenger.average_invested_exposure:.1%} | "
        f"cash_drag={result.challenger.cash_drag:.2%} | "
        f"upside_capture={_display(result.challenger.upside_capture)} | "
        f"downside_capture={_display(result.challenger.downside_capture)}"
    )


def classify_market_regime_as_of(
    benchmark_returns: tuple[float, ...],
    *,
    index: int,
) -> MarketRegime:
    """Classify ``index`` using only prior benchmark observations."""

    if not 0 <= index < len(benchmark_returns):
        raise ValueError("regime index is outside benchmark return history")
    values = np.asarray(benchmark_returns, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("benchmark returns must be finite")
    return _regime_as_of(values, index)


def _metrics(
    observations: tuple[AlignedPerformanceObservation, ...],
    *,
    strategy: str,
    bootstrap_samples: int,
    seed: int,
) -> EconomicMetrics:
    returns = np.asarray([_value(item, strategy, "return") for item in observations], dtype=float)
    spy = np.asarray([item.spy_return for item in observations], dtype=float)
    qqq = np.asarray([item.qqq_return for item in observations], dtype=float)
    exposure = np.asarray(
        [_value(item, strategy, "exposure") for item in observations],
        dtype=float,
    )
    turnover = np.asarray(
        [_value(item, strategy, "turnover") for item in observations],
        dtype=float,
    )
    costs = np.asarray([_value(item, strategy, "cost") for item in observations], dtype=float)
    concentration = np.asarray(
        [_value(item, strategy, "concentration") for item in observations],
        dtype=float,
    )
    active = returns - spy
    selection = returns + costs - exposure * spy
    timing = exposure * spy - spy
    annualized = _annualized_return(returns) if len(returns) >= 126 else None
    volatility = _annualized_std(returns)
    downside = _annualized_std(returns[returns < 0]) if np.any(returns < 0) else 0.0
    return EconomicMetrics(
        observations=len(returns),
        total_return=_compound(returns),
        annualized_return=annualized,
        excess_vs_spy=_compound(returns) - _compound(spy),
        excess_vs_qqq=_compound(returns) - _compound(qqq),
        sharpe=_ratio(np.mean(returns), np.std(returns, ddof=1), sqrt(252)),
        sortino=_ratio(np.mean(returns), np.std(returns[returns < 0], ddof=1), sqrt(252)),
        information_ratio=_ratio(np.mean(active), np.std(active, ddof=1), sqrt(252)),
        maximum_drawdown=_maximum_drawdown(returns),
        volatility=volatility,
        downside_deviation=downside,
        turnover=float(np.sum(turnover)),
        estimated_cost=float(np.sum(costs)),
        average_invested_exposure=float(np.mean(exposure)),
        average_cash_allocation=float(np.mean(1.0 - exposure)),
        average_concentration=float(np.mean(concentration)),
        hit_rate=float(np.mean(returns > 0)) if len(returns) else None,
        average_winner=_mean_or_none(returns[returns > 0]),
        average_loser=_mean_or_none(returns[returns < 0]),
        benchmark_beta=_beta(returns, spy),
        tracking_error=_annualized_std(active),
        upside_capture=_capture(returns, spy, positive=True),
        downside_capture=_capture(returns, spy, positive=False),
        up_market_participation=_participation(exposure, spy, positive=True),
        down_market_protection=_participation(exposure, spy, positive=False),
        bull_market_opportunity_loss=float(np.sum((1.0 - exposure) * np.maximum(spy, 0.0))),
        cash_drag=float(np.sum((1.0 - exposure) * spy)),
        underexposure_drag=float(np.sum((1.0 - exposure) * np.maximum(spy, 0.0))),
        selection_alpha=float(np.sum(selection)),
        timing_alpha=float(np.sum(timing)),
        cost_drag=float(-np.sum(costs)),
        bootstrap_active_interval=_block_bootstrap_interval(
            active,
            samples=bootstrap_samples,
            seed=seed,
        ),
    )


def _regime_metrics(
    observations: tuple[AlignedPerformanceObservation, ...],
    *,
    strategy: str,
) -> tuple[RegimeMetrics, ...]:
    returns = np.asarray([item.spy_return for item in observations], dtype=float)
    regimes = tuple(_regime_as_of(returns, index) for index in range(len(observations)))
    result: list[RegimeMetrics] = []
    for regime in MarketRegime:
        rows = [
            item
            for item, item_regime in zip(observations, regimes, strict=True)
            if item_regime is regime
        ]
        if not rows:
            result.append(RegimeMetrics(regime, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, None))
            continue
        portfolio = np.asarray([_value(item, strategy, "return") for item in rows], dtype=float)
        benchmark = np.asarray([item.spy_return for item in rows], dtype=float)
        exposure = np.asarray([_value(item, strategy, "exposure") for item in rows], dtype=float)
        turnover = np.asarray([_value(item, strategy, "turnover") for item in rows], dtype=float)
        result.append(
            RegimeMetrics(
                regime=regime,
                observations=len(rows),
                return_value=_compound(portfolio),
                benchmark_return=_compound(benchmark),
                excess_return=_compound(portfolio) - _compound(benchmark),
                exposure=float(np.mean(exposure)),
                drawdown=_maximum_drawdown(portfolio),
                turnover=float(np.sum(turnover)),
                decisions=sum(item.decisions for item in rows),
                opportunity_loss=float(np.sum((1.0 - exposure) * np.maximum(benchmark, 0.0))),
                downside_protection=_capture(portfolio, benchmark, positive=False),
            )
        )
    return tuple(result)


def _counterfactuals(
    observations: tuple[AlignedPerformanceObservation, ...],
) -> tuple[ExposureCounterfactual, ...]:
    scenarios: dict[str, tuple[float, ...]] = {
        "current_exposure": tuple(item.challenger_exposure for item in observations),
        "80%": tuple(0.80 for _ in observations),
        "90%": tuple(0.90 for _ in observations),
        "100%": tuple(1.00 for _ in observations),
        "risk_targeted": tuple(
            item.risk_targeted_exposure
            if item.risk_targeted_exposure is not None
            else item.challenger_exposure
            for item in observations
        ),
        "adaptive_exposure": tuple(
            (
                item.adaptive_exposure
                if item.adaptive_exposure is not None
                else item.challenger_exposure
            )
            for item in observations
        ),
    }
    output: list[ExposureCounterfactual] = []
    benchmark = np.asarray([item.spy_return for item in observations], dtype=float)
    for name, values in scenarios.items():
        exposure = np.asarray(values, dtype=float)
        selection = np.asarray(
            [
                item.challenger_return
                + item.challenger_cost
                - item.challenger_exposure * item.spy_return
                for item in observations
            ],
            dtype=float,
        )
        costs = np.asarray([item.challenger_cost for item in observations], dtype=float)
        returns = selection + exposure * benchmark - costs
        output.append(
            ExposureCounterfactual(
                name=name,
                total_return=_compound(returns),
                excess_vs_spy=_compound(returns) - _compound(benchmark),
                average_exposure=float(np.mean(exposure)),
                cash_drag=float(np.sum((1.0 - exposure) * benchmark)),
                underexposure_drag=float(np.sum((1.0 - exposure) * np.maximum(benchmark, 0.0))),
            )
        )
    return tuple(output)


def _difference(challenger: EconomicMetrics, champion: EconomicMetrics) -> dict[str, float | None]:
    fields = (
        "total_return",
        "annualized_return",
        "excess_vs_spy",
        "excess_vs_qqq",
        "sharpe",
        "sortino",
        "information_ratio",
        "maximum_drawdown",
        "volatility",
        "turnover",
        "estimated_cost",
        "average_invested_exposure",
        "average_cash_allocation",
        "average_concentration",
        "upside_capture",
        "downside_capture",
    )
    return {
        field: _optional_difference(getattr(challenger, field), getattr(champion, field))
        for field in fields
    }


def _value(item: AlignedPerformanceObservation, strategy: str, field: str) -> float:
    return float(getattr(item, f"{strategy}_{field}"))


def _compound(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def _annualized_return(values: np.ndarray) -> float | None:
    total = _compound(values)
    if total <= -1.0:
        return -1.0
    return float((1.0 + total) ** (252.0 / len(values)) - 1.0)


def _annualized_std(values: np.ndarray) -> float | None:
    return float(np.std(values, ddof=1) * sqrt(252)) if len(values) > 1 else None


def _ratio(mean: float, deviation: float, scale: float) -> float | None:
    return float(mean / deviation * scale) if isfinite(deviation) and deviation > 1e-15 else None


def _maximum_drawdown(values: np.ndarray) -> float:
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(equity)
    return float(np.min(equity / peaks - 1.0)) if len(equity) else 0.0


def _mean_or_none(values: np.ndarray) -> float | None:
    return float(np.mean(values)) if len(values) else None


def _beta(values: np.ndarray, benchmark: np.ndarray) -> float | None:
    if len(values) < 2:
        return None
    variance = float(np.var(benchmark, ddof=1))
    return float(np.cov(values, benchmark, ddof=1)[0, 1] / variance) if variance > 1e-15 else None


def _capture(values: np.ndarray, benchmark: np.ndarray, *, positive: bool) -> float | None:
    mask = benchmark > 0 if positive else benchmark < 0
    if not np.any(mask):
        return None
    benchmark_total = _compound(benchmark[mask])
    if abs(benchmark_total) <= 1e-15:
        return None
    return float(_compound(values[mask]) / benchmark_total)


def _participation(exposure: np.ndarray, benchmark: np.ndarray, *, positive: bool) -> float | None:
    mask = benchmark > 0 if positive else benchmark < 0
    return float(np.mean(exposure[mask])) if np.any(mask) else None


def _regime_as_of(benchmark: np.ndarray, index: int) -> MarketRegime:
    """Classify only from returns known before the current session."""

    history = benchmark[max(0, index - 21) : index]
    if len(history) < 10:
        return MarketRegime.NORMAL
    cumulative = _compound(history)
    volatility = float(np.std(history, ddof=1) * sqrt(252)) if len(history) > 1 else 0.0
    if cumulative <= -0.12:
        return MarketRegime.CRISIS
    if cumulative <= -0.05:
        return MarketRegime.BEAR
    if volatility >= 0.30:
        return MarketRegime.DEFENSIVE
    if cumulative >= 0.15:
        return MarketRegime.STRONG_BULL
    if cumulative >= 0.05:
        return MarketRegime.BULL
    return MarketRegime.NORMAL


def _block_bootstrap_interval(
    values: np.ndarray,
    *,
    samples: int,
    seed: int,
    block_size: int = 5,
) -> tuple[float, float] | None:
    if len(values) < 20:
        return None
    rng = Random(seed)
    draws: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < len(values):
            start = rng.randrange(len(values))
            sample.extend(values[start : min(len(values), start + block_size)].tolist())
        draws.append(_compound(np.asarray(sample[: len(values)], dtype=float)))
    return (
        float(np.percentile(draws, 2.5)),
        float(np.percentile(draws, 97.5)),
    )


def _optional_difference(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def _display(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}x"
