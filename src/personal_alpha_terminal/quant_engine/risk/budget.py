from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class RegimeRiskInput:
    risk_on_probability: float
    neutral_probability: float
    risk_off_probability: float
    confidence: float
    calibrated: bool
    model_version: str

    def __post_init__(self) -> None:
        probabilities = (
            self.risk_on_probability,
            self.neutral_probability,
            self.risk_off_probability,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in probabilities):
            raise ValueError("regime probabilities must be finite and in [0, 1]")
        if abs(sum(probabilities) - 1) > 1e-6:
            raise ValueError("regime probabilities must sum to one")
        if not 0 <= self.confidence <= 1:
            raise ValueError("regime confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PortfolioRiskState:
    current_drawdown: float
    rolling_volatility: float
    portfolio_beta: float
    concentration_hhi: float
    average_correlation: float
    baseline_average_correlation: float

    def __post_init__(self) -> None:
        values = (
            self.current_drawdown,
            self.rolling_volatility,
            self.portfolio_beta,
            self.concentration_hhi,
            self.average_correlation,
            self.baseline_average_correlation,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("portfolio risk state must be finite")
        if self.current_drawdown > 0:
            raise ValueError("drawdown must be zero or negative")


@dataclass(frozen=True, slots=True)
class RiskBudget:
    gross_exposure_multiplier: float
    volatility_multiplier: float
    position_cap_multiplier: float
    allow_new_risk: bool
    reasons: tuple[str, ...]


class DynamicRiskBudget:
    """Smoothly reduces risk; never converts a regime label into an all-out switch."""

    def evaluate(
        self,
        *,
        regime: RegimeRiskInput | None,
        state: PortfolioRiskState,
        configured_target_volatility: float,
    ) -> RiskBudget:
        if configured_target_volatility <= 0:
            raise ValueError("configured target volatility must be positive")
        gross = 1.0
        volatility = 1.0
        position = 1.0
        reasons: list[str] = []
        if regime is not None and regime.calibrated:
            risk_off_effect = regime.risk_off_probability * regime.confidence
            gross *= max(0.55, 1 - 0.40 * risk_off_effect)
            volatility *= max(0.60, 1 - 0.35 * risk_off_effect)
            position *= max(0.70, 1 - 0.25 * risk_off_effect)
            if risk_off_effect > 0.25:
                reasons.append("calibrated risk-off evidence reduced the risk budget")
        elif regime is not None:
            reasons.append("uncalibrated regime score ignored for position sizing")
        drawdown_pressure = min(1.0, abs(state.current_drawdown) / 0.20)
        if drawdown_pressure > 0:
            gross *= 1 - 0.30 * drawdown_pressure
            volatility *= 1 - 0.25 * drawdown_pressure
            reasons.append("portfolio drawdown reduced incremental risk")
        if state.rolling_volatility > configured_target_volatility:
            ratio = configured_target_volatility / state.rolling_volatility
            volatility *= max(0.55, min(1.0, ratio))
            gross *= max(0.65, min(1.0, ratio**0.5))
            reasons.append("realized volatility exceeded the configured target")
        correlation_jump = state.average_correlation - state.baseline_average_correlation
        if correlation_jump > 0.15:
            scale = max(0.65, 1 - min(0.35, correlation_jump))
            gross *= scale
            position *= scale
            reasons.append("correlation spike reduced diversification capacity")
        if state.concentration_hhi > 0.20:
            gross *= 0.9
            position *= 0.85
            reasons.append("portfolio HHI is elevated")
        allow_new_risk = state.current_drawdown > -0.25 and state.rolling_volatility < 0.60
        if not allow_new_risk:
            reasons.append("severe observed risk blocks new exposure")
        return RiskBudget(
            gross_exposure_multiplier=max(0.0, min(1.0, gross)),
            volatility_multiplier=max(0.0, min(1.0, volatility)),
            position_cap_multiplier=max(0.0, min(1.0, position)),
            allow_new_risk=allow_new_risk,
            reasons=tuple(reasons),
        )
