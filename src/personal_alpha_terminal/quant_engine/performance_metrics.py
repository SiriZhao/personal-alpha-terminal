"""Frequency-aware performance metrics for daily and holding-period evidence.

The project previously annualized every return series with ``sqrt(252)``.
ROUND33 makes the return frequency and ``periods_per_year`` part of every
metric calculation.  Sparse rebalance-point series must not be passed here as
if they were daily observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, sqrt


class PerformanceFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    HOLDING_PERIOD = "HOLDING_PERIOD"


@dataclass(frozen=True, slots=True)
class FrequencySpec:
    """Explicit return-frequency contract for every performance metric."""

    frequency: PerformanceFrequency
    periods_per_year: float
    horizon_sessions: int | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.periods_per_year) or self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be finite and positive")
        if self.frequency is PerformanceFrequency.DAILY:
            if abs(self.periods_per_year - 252) > 1e-9:
                raise ValueError("DAILY frequency requires periods_per_year=252")
        elif self.frequency is PerformanceFrequency.WEEKLY:
            if abs(self.periods_per_year - 52) > 1e-9:
                raise ValueError("WEEKLY frequency requires periods_per_year=52")
        elif self.frequency is PerformanceFrequency.HOLDING_PERIOD:
            if self.horizon_sessions is None or self.horizon_sessions <= 0:
                raise ValueError("HOLDING_PERIOD frequency requires horizon_sessions")
            expected = 252 / self.horizon_sessions
            if abs(self.periods_per_year - expected) > 1e-9:
                raise ValueError(
                    "HOLDING_PERIOD periods_per_year must equal 252 / horizon_sessions"
                )
        else:
            raise ValueError(f"unsupported performance frequency: {self.frequency}")

    @classmethod
    def daily(cls) -> FrequencySpec:
        return cls(PerformanceFrequency.DAILY, 252)

    @classmethod
    def holding(cls, horizon_sessions: int) -> FrequencySpec:
        if horizon_sessions <= 0:
            raise ValueError("horizon_sessions must be positive")
        return cls(PerformanceFrequency.HOLDING_PERIOD, 252 / horizon_sessions, horizon_sessions)


@dataclass(frozen=True, slots=True)
class EquityPerformance:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    maximum_drawdown: float
    drawdown_duration_sessions: int
    alpha: float | None
    beta: float | None
    tracking_error: float | None
    information_ratio: float | None
    return_frequency: PerformanceFrequency
    periods_per_year: float
    horizon_sessions: int | None
    observation_count: int
    effective_independent_periods: int
    short_sample_annualization: bool

    def document(self) -> dict[str, object]:
        return {
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "maximum_drawdown": self.maximum_drawdown,
            "drawdown_duration_sessions": self.drawdown_duration_sessions,
            "alpha": self.alpha,
            "beta": self.beta,
            "tracking_error": self.tracking_error,
            "information_ratio": self.information_ratio,
            "return_frequency": self.return_frequency.value,
            "periods_per_year": self.periods_per_year,
            "horizon_sessions": self.horizon_sessions,
            "observation_count": self.observation_count,
            "effective_independent_periods": self.effective_independent_periods,
            "short_sample_annualization": self.short_sample_annualization,
        }


def calculate_equity_performance(
    equity_points: tuple[tuple[date, float], ...],
    *,
    frequency_spec: FrequencySpec,
    annual_risk_free_rate: float = 0.0,
    benchmark_returns: tuple[tuple[date, float], ...] = (),
) -> EquityPerformance:
    """Calculate metrics from an explicit-frequency equity curve.

    The equity curve must be sampled at the frequency described by
    ``frequency_spec``.  A 21-session holding-period equity curve must use
    ``FrequencySpec.holding(21)`` rather than pretending it is daily.
    """

    if len(equity_points) < 2:
        raise ValueError("equity performance requires at least two points")
    ordered = tuple(sorted(equity_points, key=lambda item: item[0]))
    values = [float(value) for _, value in ordered]
    if any(not isfinite(value) or value <= 0 for value in values):
        raise ValueError("equity values must be finite and positive")
    returns = [
        values[index] / values[index - 1] - 1.0 for index in range(1, len(values))
    ]
    total_return = values[-1] / values[0] - 1.0
    periods = frequency_spec.periods_per_year
    annualized_return = (
        -1.0 if total_return <= -1.0 else (1.0 + total_return) ** (periods / len(returns)) - 1.0
    )
    annualized_volatility = _sample_std(returns) * sqrt(periods)
    risk_free_period = (1.0 + annual_risk_free_rate) ** (1.0 / periods) - 1.0
    excess = [item - risk_free_period for item in returns]
    excess_std = _sample_std(excess)
    sharpe = (
        (sum(excess) / len(excess)) / excess_std * sqrt(periods)
        if excess and excess_std > 0
        else None
    )
    downside = sqrt(sum(min(item, 0.0) ** 2 for item in excess) / len(excess)) if excess else 0.0
    sortino = (
        (sum(excess) / len(excess)) / downside * sqrt(periods)
        if excess and downside > 0
        else None
    )
    drawdowns = _drawdown_series(values)
    maximum_drawdown = min(drawdowns)
    duration = _maximum_drawdown_duration(drawdowns)
    calmar = (
        annualized_return / abs(maximum_drawdown)
        if maximum_drawdown < 0 and abs(maximum_drawdown) > 1e-15
        else None
    )
    alpha, beta, tracking, information = _benchmark_metrics(
        ordered,
        benchmark_returns=benchmark_returns,
        periods_per_year=periods,
        annual_risk_free_rate=annual_risk_free_rate,
    )
    sample_days = (ordered[-1][0] - ordered[0][0]).days
    independent_periods = max(
        1,
        len(returns) // max(1, int(frequency_spec.horizon_sessions or 1)),
    )
    return EquityPerformance(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        maximum_drawdown=maximum_drawdown,
        drawdown_duration_sessions=duration,
        alpha=alpha,
        beta=beta,
        tracking_error=tracking,
        information_ratio=information,
        return_frequency=frequency_spec.frequency,
        periods_per_year=periods,
        horizon_sessions=frequency_spec.horizon_sessions,
        observation_count=len(returns),
        effective_independent_periods=independent_periods,
        short_sample_annualization=sample_days < 252,
    )


def annualize_volatility(
    returns: list[float],
    *,
    periods_per_year: float,
) -> float:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    return _sample_std(returns) * sqrt(periods_per_year)


def annualize_sharpe(
    returns: list[float],
    *,
    periods_per_year: float,
    annual_risk_free_rate: float = 0.0,
) -> float | None:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if not returns:
        return None
    risk_free_period = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess = [item - risk_free_period for item in returns]
    std = _sample_std(excess)
    if std <= 0:
        return None
    return float((sum(excess) / len(excess)) / std * sqrt(periods_per_year))


def annualized_return_from_periods(
    total_return: float,
    *,
    observation_count: int,
    periods_per_year: float,
) -> float:
    if observation_count <= 0 or periods_per_year <= 0:
        raise ValueError("annualized return requires positive observation count and periods")
    if total_return <= -1.0:
        return -1.0
    return float(
        (1.0 + total_return) ** (periods_per_year / observation_count) - 1.0
    )


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return sqrt(variance)


def _drawdown_series(values: list[float]) -> list[float]:
    peak = values[0]
    output: list[float] = []
    for value in values:
        peak = max(peak, value)
        output.append(value / peak - 1.0)
    return output


def _maximum_drawdown_duration(drawdowns: list[float]) -> int:
    longest = 0
    current = 0
    for value in drawdowns:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _benchmark_metrics(
    points: tuple[tuple[date, float], ...],
    *,
    benchmark_returns: tuple[tuple[date, float], ...],
    periods_per_year: float,
    annual_risk_free_rate: float,
) -> tuple[float | None, float | None, float | None, float | None]:
    benchmark = dict(benchmark_returns)
    aligned = [
        (points[index][1] / points[index - 1][1] - 1.0, benchmark[points[index][0]])
        for index in range(1, len(points))
        if points[index][0] in benchmark
    ]
    if len(aligned) < 2:
        return None, None, None, None
    strategy = [item[0] for item in aligned]
    market = [item[1] for item in aligned]
    variance = _sample_std(market) ** 2
    covariance = _sample_covariance(strategy, market)
    beta = covariance / variance if variance > 0 else None
    risk_free_period = (1.0 + annual_risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    alpha = (
        (
            (sum(strategy) / len(strategy) - risk_free_period)
            - beta * (sum(market) / len(market) - risk_free_period)
        )
        * periods_per_year
        if beta is not None
        else None
    )
    active = [left - right for left, right in aligned]
    tracking = _sample_std(active) * sqrt(periods_per_year)
    information = (
        (sum(active) / len(active) * periods_per_year) / tracking
        if tracking > 0
        else None
    )
    return alpha, beta, tracking, information


def _sample_covariance(left: list[float], right: list[float]) -> float:
    if len(left) < 2:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum(
        (first - left_mean) * (second - right_mean)
        for first, second in zip(left, right, strict=True)
    ) / (len(left) - 1)
