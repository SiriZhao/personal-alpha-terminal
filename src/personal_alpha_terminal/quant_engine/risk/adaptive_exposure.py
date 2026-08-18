"""ROUND69 explicit, evidence-driven capital-participation controller.

This controller is shadow-only until the PIT/survivorship/OOS gates pass.  It
uses the existing portfolio constraints as hard limits and records every
exposure decision for attribution; it never submits orders or silently changes
the production champion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite

from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioConstraints


class ExposureParticipationState(StrEnum):
    DEFENSIVE = "DEFENSIVE"
    REDUCED = "REDUCED"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    MAX_ALLOWED = "MAX_ALLOWED"


class CashAllocationCause(StrEnum):
    INTENTIONAL_RISK_CASH = "INTENTIONAL_RISK_CASH"
    NO_VALID_OPPORTUNITY_CASH = "NO_VALID_OPPORTUNITY_CASH"
    OPTIMIZER_ARTIFACT_CASH = "OPTIMIZER_ARTIFACT_CASH"
    CONSTRAINT_BINDING_CASH = "CONSTRAINT_BINDING_CASH"
    ROUNDING_CASH = "ROUNDING_CASH"
    DATA_QUALITY_CASH = "DATA_QUALITY_CASH"


@dataclass(frozen=True, slots=True)
class ExposureEvidenceInputs:
    risk_on_probability: float
    risk_off_probability: float
    regime_confidence: float
    breadth: float
    trend: float
    volatility_score: float
    drawdown_score: float
    opportunity_quality: float
    alpha_confidence: float
    concentration_risk: float
    liquidity_score: float
    risk_budget_headroom: float
    uncertainty: float
    correlation_risk: float
    current_exposure: float
    recovery_signal: float = 0.0

    def __post_init__(self) -> None:
        bounded = (
            self.risk_on_probability,
            self.risk_off_probability,
            self.regime_confidence,
            self.breadth,
            self.trend,
            self.volatility_score,
            self.drawdown_score,
            self.opportunity_quality,
            self.alpha_confidence,
            self.concentration_risk,
            self.liquidity_score,
            self.risk_budget_headroom,
            self.uncertainty,
            self.correlation_risk,
            self.current_exposure,
            self.recovery_signal,
        )
        if any(not isfinite(item) or not 0 <= item <= 1 for item in bounded):
            raise ValueError("exposure evidence inputs must be in [0, 1]")
        if self.risk_on_probability + self.risk_off_probability > 1.000001:
            raise ValueError("risk-on and risk-off probabilities cannot exceed one")


@dataclass(frozen=True, slots=True)
class ExposureDecision:
    target_gross_exposure: float
    target_net_exposure: float
    exposure_confidence: float
    dominant_drivers: tuple[str, ...]
    binding_constraints: tuple[str, ...]
    risk_state: str
    participation_state: ExposureParticipationState
    raw_target: float
    risk_adjusted_target: float
    final_target: float
    current_exposure: float
    recovery_phase: bool
    shadow_only: bool
    model_version: str
    config_version: str

    def __post_init__(self) -> None:
        values = (
            self.target_gross_exposure,
            self.target_net_exposure,
            self.exposure_confidence,
            self.raw_target,
            self.risk_adjusted_target,
            self.final_target,
            self.current_exposure,
        )
        if any(not isfinite(item) or not 0 <= item <= 1 for item in values):
            raise ValueError("exposure decision values must be in [0, 1]")
        if self.target_net_exposure > self.target_gross_exposure + 1e-9:
            raise ValueError("net exposure cannot exceed gross exposure")

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["participation_state"] = self.participation_state.value
        return payload


@dataclass(frozen=True, slots=True)
class CashAttribution:
    cash_weight: float
    cause: CashAllocationCause
    amount: float
    reason: str


class AdaptiveExposureController:
    """Smooth a multi-signal participation target inside hard risk limits."""

    def __init__(
        self,
        constraints: PortfolioConstraints | None = None,
        *,
        model_version: str = "round69-adaptive-exposure-v1",
        config_version: str = "round69-default-v1",
        max_step: float = 0.15,
        hysteresis: float = 0.03,
    ) -> None:
        self.constraints = constraints or PortfolioConstraints()
        self.model_version = model_version
        self.config_version = config_version
        self.max_step = max_step
        self.hysteresis = hysteresis
        if not 0 < max_step <= 1 or not 0 <= hysteresis <= max_step:
            raise ValueError("exposure smoothing configuration is invalid")
        self._previous_target: float | None = None
        self._previous_raw_target: float | None = None

    @property
    def capacity(self) -> float:
        return min(
            self.constraints.maximum_gross_exposure,
            1.0 - self.constraints.minimum_cash_weight,
        )

    def decide(self, inputs: ExposureEvidenceInputs) -> ExposureDecision:
        capacity = self.capacity
        positive = (
            0.18 * inputs.breadth
            + 0.16 * inputs.trend
            + 0.14 * inputs.opportunity_quality
            + 0.12 * inputs.alpha_confidence
            + 0.10 * inputs.liquidity_score
            + 0.10 * inputs.risk_budget_headroom
            + 0.08 * inputs.risk_on_probability
            + 0.06 * inputs.regime_confidence
            + 0.06 * inputs.recovery_signal
        )
        negative = (
            0.22 * inputs.risk_off_probability
            + 0.18 * inputs.volatility_score
            + 0.15 * inputs.drawdown_score
            + 0.13 * inputs.concentration_risk
            + 0.12 * inputs.correlation_risk
            + 0.12 * inputs.uncertainty
            + 0.08 * (1.0 - inputs.liquidity_score)
        )
        score = max(0.0, min(1.0, positive - negative + 0.5))
        raw_target = capacity * score
        risk_adjusted = raw_target
        constraints: list[str] = []
        if inputs.risk_off_probability >= 0.70 or inputs.drawdown_score >= 0.80:
            risk_adjusted = min(risk_adjusted, min(inputs.current_exposure, capacity * 0.45))
            constraints.append("DEFENSIVE_RISK_CAP")
        if inputs.volatility_score >= 0.80:
            risk_adjusted = min(risk_adjusted, capacity * 0.60)
            constraints.append("VOLATILITY_CAP")
        if inputs.liquidity_score <= 0.20:
            risk_adjusted = min(risk_adjusted, capacity * 0.50)
            constraints.append("LIQUIDITY_CAP")
        risk_state = (
            "RISK_OFF" if inputs.risk_off_probability >= 0.60 else
            "RISK_ON" if inputs.risk_on_probability >= 0.60 else
            "TRANSITION"
        )
        recovery = inputs.recovery_signal >= 0.60 and risk_state != "RISK_OFF"
        final_target = self._smooth(risk_adjusted, inputs.current_exposure, raw_target)
        if risk_state == "RISK_OFF" or final_target < capacity * 0.35:
            state = ExposureParticipationState.DEFENSIVE
        elif final_target >= capacity - 1e-6:
            state = ExposureParticipationState.MAX_ALLOWED
        elif final_target >= capacity * 0.85:
            state = ExposureParticipationState.HIGH
        elif final_target >= capacity * 0.60:
            state = ExposureParticipationState.NORMAL
        elif final_target >= capacity * 0.35:
            state = ExposureParticipationState.REDUCED
        else:
            state = ExposureParticipationState.DEFENSIVE
        drivers = tuple(
            name
            for name, value in sorted(
                {
                    "breadth": 0.18 * inputs.breadth,
                    "trend": 0.16 * inputs.trend,
                    "opportunity_quality": 0.14 * inputs.opportunity_quality,
                    "alpha_confidence": 0.12 * inputs.alpha_confidence,
                    "risk_off": -0.22 * inputs.risk_off_probability,
                    "volatility": -0.18 * inputs.volatility_score,
                    "drawdown": -0.15 * inputs.drawdown_score,
                    "uncertainty": -0.12 * inputs.uncertainty,
                }.items(),
                key=lambda item: abs(item[1]),
                reverse=True,
            )[:4]
        )
        confidence = max(
            0.0,
            min(
                1.0,
                inputs.regime_confidence
                * (1.0 - inputs.uncertainty)
                * (0.5 + 0.5 * inputs.alpha_confidence),
            ),
        )
        if final_target >= capacity - 1e-6:
            constraints.append("MAXIMUM_GROSS_EXPOSURE")
        if final_target <= self.constraints.minimum_beta + 1e-9:
            constraints.append("MINIMUM_CASH_OR_BETA")
        self._previous_target = final_target
        self._previous_raw_target = raw_target
        return ExposureDecision(
            target_gross_exposure=final_target,
            target_net_exposure=final_target,
            exposure_confidence=confidence,
            dominant_drivers=drivers,
            binding_constraints=tuple(dict.fromkeys(constraints)),
            risk_state=risk_state,
            participation_state=state,
            raw_target=raw_target,
            risk_adjusted_target=risk_adjusted,
            final_target=final_target,
            current_exposure=inputs.current_exposure,
            recovery_phase=recovery,
            shadow_only=True,
            model_version=self.model_version,
            config_version=self.config_version,
        )

    def _smooth(self, target: float, current: float, raw_target: float) -> float:
        previous = self._previous_target
        anchor = current if previous is None else previous
        if (
            self._previous_raw_target is not None
            and abs(raw_target - self._previous_raw_target) <= self.hysteresis
        ):
            return max(0.0, min(self.capacity, anchor))
        delta = target - anchor
        if abs(delta) <= self.hysteresis:
            return max(0.0, min(self.capacity, anchor))
        stepped = anchor + max(-self.max_step, min(self.max_step, delta))
        return max(0.0, min(self.capacity, stepped))


def attribute_cash(
    *,
    actual_cash: float,
    target_cash: float,
    data_quality_blocked: bool,
    valid_opportunity: bool,
    optimizer_residual: float = 0.0,
    constraint_binding: bool = False,
) -> CashAttribution:
    """Classify cash without silently treating implementation residual as intent."""

    if not isfinite(actual_cash) or not 0 <= actual_cash <= 1:
        raise ValueError("actual_cash must be in [0, 1]")
    if not isfinite(target_cash) or not 0 <= target_cash <= 1:
        raise ValueError("target_cash must be in [0, 1]")
    if abs(optimizer_residual) > 1e-8:
        cause = CashAllocationCause.OPTIMIZER_ARTIFACT_CASH
        reason = "optimizer residual exceeds rounding tolerance"
    elif data_quality_blocked:
        cause = CashAllocationCause.DATA_QUALITY_CASH
        reason = "critical data evidence is blocked"
    elif constraint_binding:
        cause = CashAllocationCause.CONSTRAINT_BINDING_CASH
        reason = "hard risk or liquidity constraint binds"
    elif not valid_opportunity:
        cause = CashAllocationCause.NO_VALID_OPPORTUNITY_CASH
        reason = "no eligible opportunity passed the signal/data gates"
    elif actual_cash > target_cash + 1e-6:
        cause = CashAllocationCause.ROUNDING_CASH
        reason = "residual cash is within execution/rounding tolerance"
    else:
        cause = CashAllocationCause.INTENTIONAL_RISK_CASH
        reason = "cash is intentional risk budget"
    return CashAttribution(actual_cash, cause, actual_cash, reason)
