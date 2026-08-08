from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import sqrt

from personal_alpha_terminal.backtest.schemas import BacktestResult

TRADING_SESSIONS_PER_YEAR = 252
REQUIRED_US_BENCHMARKS = ("SPY", "VOO", "QQQ", "QQQM", "RSP")


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    name: str
    coverage_start: date
    coverage_end: date
    observations: int
    cagr: float
    volatility: float
    sharpe: float | None
    sortino: float | None
    maximum_drawdown: float
    calmar: float | None
    beta: float | None
    annualized_alpha: float | None
    worst_day: float
    worst_month: float
    worst_year: float


@dataclass(frozen=True, slots=True)
class PerformanceComparison:
    strategy: BenchmarkMetrics
    benchmarks: tuple["RelativeBenchmarkComparison", ...]
    missing_benchmarks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelativeBenchmarkComparison:
    benchmark: BenchmarkMetrics
    strategy_beta: float | None
    strategy_annualized_alpha: float | None


def compare_with_us_benchmarks(
    result: BacktestResult,
    benchmark_levels: dict[str, tuple[tuple[date, float], ...]],
    *,
    annual_risk_free_rate: float = 0.0,
) -> PerformanceComparison:
    """Compare on exact common sessions; never forward-fill pre-inception history."""

    strategy_levels = tuple((item.trade_date, item.nav) for item in result.points)
    benchmark_results: list[RelativeBenchmarkComparison] = []
    for name in REQUIRED_US_BENCHMARKS:
        levels = benchmark_levels.get(name)
        if levels is None:
            continue
        strategy_aligned, benchmark_aligned = _align_levels(strategy_levels, levels)
        if len(strategy_aligned) < 2:
            continue
        benchmark_returns = _returns(benchmark_aligned)
        strategy_returns = _returns(strategy_aligned)
        benchmark_metric = _metrics(
                name,
                benchmark_aligned,
                annual_risk_free_rate,
            )
        beta, alpha = _relative_alpha_beta(
            strategy_returns,
            benchmark_returns,
            annual_risk_free_rate,
        )
        benchmark_results.append(RelativeBenchmarkComparison(benchmark_metric, beta, alpha))
    missing = tuple(
        name
        for name in REQUIRED_US_BENCHMARKS
        if name not in {x.benchmark.name for x in benchmark_results}
    )
    return PerformanceComparison(
        strategy=_metrics(
            result.strategy_name,
            strategy_levels,
            annual_risk_free_rate,
        ),
        benchmarks=tuple(benchmark_results),
        missing_benchmarks=missing,
    )


def _align_levels(
    left: tuple[tuple[date, float], ...],
    right: tuple[tuple[date, float], ...],
) -> tuple[tuple[tuple[date, float], ...], tuple[tuple[date, float], ...]]:
    left_map = dict(left)
    right_map = dict(right)
    common = sorted(set(left_map) & set(right_map))
    return (
        tuple((item, left_map[item]) for item in common),
        tuple((item, right_map[item]) for item in common),
    )


def _returns(levels: tuple[tuple[date, float], ...]) -> tuple[float, ...]:
    if any(value <= 0 for _, value in levels):
        raise ValueError("performance levels must be positive")
    return tuple(levels[index][1] / levels[index - 1][1] - 1 for index in range(1, len(levels)))


def _metrics(
    name: str,
    levels: tuple[tuple[date, float], ...],
    risk_free: float,
) -> BenchmarkMetrics:
    if len(levels) < 2:
        raise ValueError("at least two performance observations are required")
    returns = _returns(levels)
    years = len(returns) / TRADING_SESSIONS_PER_YEAR
    cagr = (levels[-1][1] / levels[0][1]) ** (1 / years) - 1
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / max(1, len(returns) - 1)
    volatility = sqrt(variance) * sqrt(TRADING_SESSIONS_PER_YEAR)
    daily_rf = (1 + risk_free) ** (1 / TRADING_SESSIONS_PER_YEAR) - 1
    sharpe = (
        (mean - daily_rf) / sqrt(variance) * sqrt(TRADING_SESSIONS_PER_YEAR)
        if variance > 0
        else None
    )
    downside = [min(0.0, item - daily_rf) for item in returns]
    downside_dev = sqrt(sum(item * item for item in downside) / len(downside))
    sortino = (
        (mean - daily_rf) / downside_dev * sqrt(TRADING_SESSIONS_PER_YEAR)
        if downside_dev > 0
        else None
    )
    peak = levels[0][1]
    maximum_drawdown = 0.0
    for _, value in levels:
        peak = max(peak, value)
        maximum_drawdown = min(maximum_drawdown, value / peak - 1)
    grouped_month: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    grouped_year: defaultdict[int, list[float]] = defaultdict(list)
    for (session, _), item in zip(levels[1:], returns, strict=True):
        grouped_month[(session.year, session.month)].append(item)
        grouped_year[session.year].append(item)
    return BenchmarkMetrics(
        name=name,
        coverage_start=levels[0][0],
        coverage_end=levels[-1][0],
        observations=len(levels),
        cagr=cagr,
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        maximum_drawdown=maximum_drawdown,
        calmar=cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else None,
        beta=None,
        annualized_alpha=None,
        worst_day=min(returns),
        worst_month=min(_compound(tuple(value)) for value in grouped_month.values()),
        worst_year=min(_compound(tuple(value)) for value in grouped_year.values()),
    )


def _compound(values: tuple[float, ...]) -> float:
    level = 1.0
    for value in values:
        level *= 1 + value
    return level - 1


def _relative_alpha_beta(
    strategy_returns: tuple[float, ...],
    benchmark_returns: tuple[float, ...],
    risk_free: float,
) -> tuple[float | None, float | None]:
    if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
        return None, None
    strategy_mean = sum(strategy_returns) / len(strategy_returns)
    benchmark_mean = sum(benchmark_returns) / len(benchmark_returns)
    covariance = sum(
        (strategy - strategy_mean) * (benchmark - benchmark_mean)
        for strategy, benchmark in zip(strategy_returns, benchmark_returns, strict=True)
    ) / (len(strategy_returns) - 1)
    benchmark_variance = sum(
        (item - benchmark_mean) ** 2 for item in benchmark_returns
    ) / (len(benchmark_returns) - 1)
    if benchmark_variance <= 0:
        return None, None
    beta = covariance / benchmark_variance
    daily_rf = (1 + risk_free) ** (1 / TRADING_SESSIONS_PER_YEAR) - 1
    alpha = (
        (strategy_mean - daily_rf) - beta * (benchmark_mean - daily_rf)
    ) * TRADING_SESSIONS_PER_YEAR
    return beta, alpha
