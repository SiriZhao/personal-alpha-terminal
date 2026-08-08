from typing import Literal

from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    RegimeBudgetDecision,
    RegimeBudgetInput,
)

TARGET_MULTIPLIERS = {
    "risk_on": 1.00,
    "neutral": 0.75,
    "risk_off": 0.40,
    "crisis_rebound": 0.45,
    "momentum_crash_risk": 0.50,
    "high_correlation_stress": 0.40,
}


def decide_regime_budget(
    inputs: RegimeBudgetInput,
    *,
    required_confirmations: int = 3,
    cooldown_sessions: int = 5,
    maximum_session_change: float = 0.10,
) -> RegimeBudgetDecision:
    """Translate regime evidence into a gradual total-risk multiplier."""

    if inputs.regime not in TARGET_MULTIPLIERS:
        raise ValueError(f"unsupported regime: {inputs.regime}")
    if not 0 <= inputs.previous_multiplier <= 1:
        raise ValueError("previous_multiplier must be in [0, 1]")
    if required_confirmations < 1 or cooldown_sessions < 0:
        raise ValueError("confirmation and cooldown parameters are invalid")
    if not 0 < maximum_session_change <= 1:
        raise ValueError("maximum_session_change must be in (0, 1]")
    display: Literal["Market Regime Probability", "Market Regime Score"] = (
        "Market Regime Probability"
        if inputs.calibration_status == "calibrated" and inputs.probability is not None
        else "Market Regime Score"
    )
    reasons: list[str] = []
    target = TARGET_MULTIPLIERS[inputs.regime]
    if inputs.calibration_status != "calibrated":
        reasons.append("probability gate not passed; using Market Regime Score")
        if target > inputs.previous_multiplier:
            target = min(target, 0.85)
            reasons.append("score-only state cannot restore full risk budget")
    if inputs.confirmation_count < required_confirmations:
        target = min(target, inputs.previous_multiplier)
        reasons.append("state change is awaiting confirmation")
    if inputs.sessions_since_change < cooldown_sessions and target > inputs.previous_multiplier:
        target = inputs.previous_multiplier
        reasons.append("risk increase is blocked during cooldown")
    delta = target - inputs.previous_multiplier
    limited_delta = max(-maximum_session_change, min(maximum_session_change, delta))
    applied = max(0.0, min(1.0, inputs.previous_multiplier + limited_delta))
    transition_limited = abs(applied - target) > 1e-12
    if transition_limited:
        reasons.append("position transition limited to avoid one-day switching")
    return RegimeBudgetDecision(
        display_name=display,
        target_multiplier=target,
        applied_multiplier=applied,
        transition_limited=transition_limited,
        reasons=tuple(reasons),
    )
