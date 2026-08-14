"""ROUND24 drawdown governor research (D7).

The governor suggests reduce-gross / freeze-buys / raise-cash actions from
portfolio drawdown, benchmark drawdown, volatility and correlation spikes.
It applies hysteresis so risk-on/risk-off flipping cannot create churn.
It is a promotion candidate only: it never modifies production risk limits.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION = "drawdown-governor-v1"
MODEL_STATUS = "RISK_OVERLAY_PROMOTION_CANDIDATE"


@dataclass(frozen=True, slots=True)
class GovernorInputs:
    portfolio_drawdown: float
    benchmark_drawdown: float
    realized_volatility: float
    correlation_spike: bool

    def __post_init__(self) -> None:
        if not -1.0 <= self.portfolio_drawdown <= 0.0:
            raise ValueError("portfolio drawdown must be in [-1, 0]")
        if self.realized_volatility < 0:
            raise ValueError("volatility must be non-negative")


@dataclass(frozen=True, slots=True)
class GovernorAdvice:
    action: str
    reduce_gross: bool
    freeze_new_buys: bool
    increase_cash: bool
    severity: int
    reasons: tuple[str, ...]
    model_version: str = MODEL_VERSION
    model_status: str = MODEL_STATUS

    def document(self) -> dict[str, object]:
        return {
            "action": self.action,
            "reduce_gross": self.reduce_gross,
            "freeze_new_buys": self.freeze_new_buys,
            "increase_cash": self.increase_cash,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "model_version": self.model_version,
            "model_status": self.model_status,
        }


@dataclass(frozen=True, slots=True)
class GovernorState:
    active: bool
    severity: int
    consecutive_observations: int

    def document(self) -> dict[str, object]:
        return {
            "active": self.active,
            "severity": self.severity,
            "consecutive_observations": self.consecutive_observations,
        }


def evaluate_governor(
    inputs: GovernorInputs,
    *,
    previous: GovernorState | None = None,
    activation_observations: int = 3,
    deactivation_observations: int = 5,
) -> tuple[GovernorAdvice, GovernorState]:
    """Hysteresis-governed de-risking advice (research only)."""

    state = previous or GovernorState(False, 0, 0)
    reasons: list[str] = []
    severity = 0
    if inputs.portfolio_drawdown <= -0.25:
        severity = max(severity, 3)
        reasons.append("PORTFOLIO_DRAWDOWN_25PCT")
    elif inputs.portfolio_drawdown <= -0.15:
        severity = max(severity, 2)
        reasons.append("PORTFOLIO_DRAWDOWN_15PCT")
    elif inputs.portfolio_drawdown <= -0.08:
        severity = max(severity, 1)
        reasons.append("PORTFOLIO_DRAWDOWN_8PCT")
    if inputs.portfolio_drawdown < inputs.benchmark_drawdown - 0.10:
        severity = max(severity, 1)
        reasons.append("UNDERPERFORMING_BENCHMARK_DRAWDOWN")
    if inputs.realized_volatility > 0.45:
        severity = max(severity, 2)
        reasons.append("EXTREME_VOLATILITY")
    elif inputs.realized_volatility > 0.30:
        severity = max(severity, 1)
        reasons.append("ELEVATED_VOLATILITY")
    if inputs.correlation_spike:
        severity = max(severity, 2)
        reasons.append("CORRELATION_SPIKE")
    trigger = severity >= 2
    if trigger:
        consecutive = min(state.consecutive_observations + 1, activation_observations + 10)
        active = state.active or consecutive >= activation_observations
    else:
        consecutive = max(0, state.consecutive_observations - 1)
        active = state.active and not (
            state.consecutive_observations <= -deactivation_observations
        )
        if not active:
            consecutive = 0
    if not trigger and state.active:
        # Keep the overlay active until deactivation hysteresis clears.
        active = state.consecutive_observations > -deactivation_observations
        consecutive = state.consecutive_observations - 1
    next_state = GovernorState(active, severity if active else 0, consecutive)
    if not active:
        advice = GovernorAdvice(
            action="NO_ACTION",
            reduce_gross=False,
            freeze_new_buys=False,
            increase_cash=False,
            severity=0,
            reasons=tuple(reasons),
        )
    elif severity >= 3:
        advice = GovernorAdvice(
            action="REDUCE_GROSS_AND_INCREASE_CASH",
            reduce_gross=True,
            freeze_new_buys=True,
            increase_cash=True,
            severity=severity,
            reasons=tuple(reasons),
        )
    else:
        advice = GovernorAdvice(
            action="FREEZE_NEW_BUYS",
            reduce_gross=False,
            freeze_new_buys=True,
            increase_cash=False,
            severity=severity,
            reasons=tuple(reasons),
        )
    return advice, next_state
