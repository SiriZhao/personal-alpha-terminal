from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite, sqrt

import numpy as np

from personal_alpha_terminal.quant_engine.risk.model import RiskModelEstimate


class StressStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCKED = "BLOCKED"
    NOT_VALIDATED = "NOT_VALIDATED"


@dataclass(frozen=True, slots=True)
class StressRiskConfig:
    production_validated: bool = False
    validation_id: str | None = None
    provisional_operational: bool = False
    maximum_cvar_loss: float = 0.06
    maximum_liquidation_days: float = 5.0
    maximum_correlation_spike_loss: float = 0.08
    maximum_gap_loss: float = 0.08
    maximum_stressed_volatility: float = 0.30
    maximum_benchmark_crash_loss: float = 0.25
    maximum_single_name_loss: float = 0.05
    maximum_sector_loss: float = 0.10
    warning_ratio: float = 0.80
    model_version: str = "deterministic-stress-v1"

    def __post_init__(self) -> None:
        limits = (
            self.maximum_cvar_loss,
            self.maximum_liquidation_days,
            self.maximum_correlation_spike_loss,
            self.maximum_gap_loss,
            self.maximum_stressed_volatility,
            self.maximum_benchmark_crash_loss,
            self.maximum_single_name_loss,
            self.maximum_sector_loss,
        )
        if any(not isfinite(value) or value <= 0 for value in limits):
            raise ValueError("stress limits must be finite and positive")
        if not 0 < self.warning_ratio < 1:
            raise ValueError("stress warning ratio must be in (0, 1)")
        if self.production_validated and not self.validation_id:
            raise ValueError("validated stress configuration requires validation_id")
        if self.provisional_operational and not self.validation_id:
            raise ValueError("provisional operational stress requires validation_id")


@dataclass(frozen=True, slots=True)
class PortfolioStressReport:
    historical_cvar_95: float
    parametric_cvar_95: float
    liquidity_liquidation_days: float
    correlation_spike_loss: float
    gap_down_loss: float
    volatility_shock_volatility: float
    benchmark_crash_loss: float
    single_name_shock_loss: float
    sector_shock_loss: float
    hhi: float
    status: StressStatus
    hard_failures: tuple[str, ...]
    warnings: tuple[str, ...]
    validation_id: str | None
    model_version: str
    limitations: tuple[str, ...]


def evaluate_portfolio_stress(
    *,
    weights: dict[str, float],
    portfolio_returns: tuple[float, ...],
    risk: RiskModelEstimate,
    portfolio_value: float,
    maximum_adv_participation: float,
    benchmark_crash: float = -0.20,
    single_name_shock: float = -0.30,
    sector_shock: float = -0.20,
    gap_down: float = -0.08,
    volatility_multiplier: float = 2.0,
    config: StressRiskConfig | None = None,
) -> PortfolioStressReport:
    config = config or StressRiskConfig()
    if not risk.valid_for_optimization:
        raise ValueError("stress testing requires a valid risk model")
    if set(weights) - set(risk.symbols):
        raise ValueError("stress weights are outside the risk universe")
    if portfolio_value <= 0 or not 0 < maximum_adv_participation <= 1:
        raise ValueError("portfolio value and ADV participation are invalid")
    if any(not isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("long-only weights must be finite and non-negative")
    vector = np.asarray([weights.get(symbol, 0.0) for symbol in risk.symbols], dtype=float)
    gross = float(vector.sum())
    if gross > 1 + 1e-12:
        raise ValueError("stress portfolio cannot use leverage")
    values = np.asarray(portfolio_returns, dtype=float)
    if len(values) < 30 or np.any(~np.isfinite(values)):
        raise ValueError("at least 30 finite portfolio returns are required")
    threshold = float(np.quantile(values, 0.05))
    historical_cvar = float(values[values <= threshold].mean())
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    # Normal expected shortfall at 95%; reported alongside empirical CVaR, not optimized.
    parametric_cvar = mean - std * 2.0627128075074253
    liquidation_days = max(
        (
            portfolio_value * weights.get(symbol, 0.0)
            / (risk.average_daily_dollar_volume[symbol] * maximum_adv_participation)
            for symbol in risk.symbols
        ),
        default=0.0,
    )
    stressed_correlation = np.full_like(risk.correlation, 0.9)
    np.fill_diagonal(stressed_correlation, 1.0)
    vol = np.sqrt(np.diag(risk.annualized_covariance))
    stressed_covariance = stressed_correlation * np.outer(vol, vol)
    correlation_variance = max(0.0, float(vector @ stressed_covariance @ vector))
    correlation_loss = -2.33 * sqrt(correlation_variance) / sqrt(252)
    beta = sum(weights.get(symbol, 0.0) * risk.beta[symbol] for symbol in risk.symbols)
    sector_weights: dict[str, float] = {}
    for symbol in risk.symbols:
        sector = risk.sectors[symbol]
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weights.get(symbol, 0.0)
    hhi = float(sum(value**2 for value in weights.values()))
    portfolio_variance = float(vector @ risk.annualized_covariance @ vector)
    metrics = {
        "historical_cvar_95": abs(historical_cvar),
        "liquidity_liquidation_days": float(liquidation_days),
        "correlation_spike_loss": abs(correlation_loss),
        "gap_down_loss": abs(gap_down * gross),
        "volatility_shock_volatility": sqrt(max(0.0, portfolio_variance))
        * volatility_multiplier,
        "benchmark_crash_loss": abs(benchmark_crash * beta),
        "single_name_shock_loss": abs(single_name_shock * max(weights.values(), default=0.0)),
        "sector_shock_loss": abs(sector_shock * max(sector_weights.values(), default=0.0)),
    }
    limits = {
        "historical_cvar_95": config.maximum_cvar_loss,
        "liquidity_liquidation_days": config.maximum_liquidation_days,
        "correlation_spike_loss": config.maximum_correlation_spike_loss,
        "gap_down_loss": config.maximum_gap_loss,
        "volatility_shock_volatility": config.maximum_stressed_volatility,
        "benchmark_crash_loss": config.maximum_benchmark_crash_loss,
        "single_name_shock_loss": config.maximum_single_name_loss,
        "sector_shock_loss": config.maximum_sector_loss,
    }
    failures = tuple(name for name, value in metrics.items() if value > limits[name])
    warnings = tuple(
        name
        for name, value in metrics.items()
        if name not in failures and value > limits[name] * config.warning_ratio
    )
    if not config.production_validated and not config.provisional_operational:
        status = StressStatus.NOT_VALIDATED
    elif failures:
        status = StressStatus.BLOCKED
    elif warnings:
        status = StressStatus.WARN
    else:
        status = StressStatus.PASS
    return PortfolioStressReport(
        historical_cvar_95=historical_cvar,
        parametric_cvar_95=parametric_cvar,
        liquidity_liquidation_days=float(liquidation_days),
        correlation_spike_loss=correlation_loss,
        gap_down_loss=gap_down * gross,
        volatility_shock_volatility=sqrt(max(0.0, portfolio_variance)) * volatility_multiplier,
        benchmark_crash_loss=benchmark_crash * beta,
        single_name_shock_loss=single_name_shock * max(weights.values(), default=0.0),
        sector_shock_loss=sector_shock * max(sector_weights.values(), default=0.0),
        hhi=hhi,
        status=status,
        hard_failures=failures,
        warnings=warnings,
        validation_id=config.validation_id,
        model_version=config.model_version,
        limitations=("scenario losses are deterministic guardrails, not forecasts",),
    )
