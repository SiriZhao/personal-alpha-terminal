from math import isfinite
from typing import Literal

from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    MomentumCrashInput,
    MomentumCrashResult,
)

WEIGHTS = {
    "rebound_after_drawdown": 0.18,
    "winner_loser_beta_spread": 0.13,
    "short_interest_pressure": 0.09,
    "return_dispersion": 0.10,
    "high_volatility_state": 0.12,
    "momentum_factor_drawdown": 0.15,
    "valuation_crowding": 0.08,
    "industry_concentration": 0.07,
    "correlation_spike": 0.08,
}


def evaluate_momentum_crash_risk(
    inputs: MomentumCrashInput,
    *,
    minimum_indicators: int = 5,
    maximum_momentum_reduction: float = 0.60,
    maximum_total_risk_reduction: float = 0.30,
) -> MomentumCrashResult:
    """Build a gradual, interpretable risk monitor from normalized [0, 1] inputs."""

    if minimum_indicators < 3:
        raise ValueError("minimum_indicators must be at least 3")
    if not 0 <= maximum_momentum_reduction <= 1:
        raise ValueError("maximum_momentum_reduction must be in [0, 1]")
    if not 0 <= maximum_total_risk_reduction <= 1:
        raise ValueError("maximum_total_risk_reduction must be in [0, 1]")
    raw = {
        name: getattr(inputs, name)
        for name in WEIGHTS
        if getattr(inputs, name) is not None
    }
    for name, value in raw.items():
        assert value is not None
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be normalized to [0, 1]")
    if len(raw) < minimum_indicators:
        return MomentumCrashResult(
            available=False,
            score=None,
            risk_level="unavailable",
            momentum_multiplier=0.75,
            total_risk_multiplier=0.90,
            observed_indicators=len(raw),
            contributions={},
            reasons=(
                f"observed indicators {len(raw)} < minimum {minimum_indicators}",
                "uncertainty discount applied; no binary crash call produced",
            ),
        )
    denominator = sum(WEIGHTS[name] for name in raw)
    contributions = {
        name: float(value) * WEIGHTS[name] / denominator
        for name, value in raw.items()
        if value is not None
    }
    score = sum(contributions.values())
    if score >= 0.70:
        level: Literal["low", "elevated", "high"] = "high"
    elif score >= 0.45:
        level = "elevated"
    else:
        level = "low"
    return MomentumCrashResult(
        available=True,
        score=score,
        risk_level=level,
        momentum_multiplier=max(0.0, 1 - score * maximum_momentum_reduction),
        total_risk_multiplier=max(0.0, 1 - score * maximum_total_risk_reduction),
        observed_indicators=len(raw),
        contributions=contributions,
        reasons=(
            "continuous monitor; not a deterministic market forecast",
            "missing indicators are excluded and weights are renormalized",
        ),
    )
