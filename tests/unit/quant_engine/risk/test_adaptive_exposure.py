from __future__ import annotations

from personal_alpha_terminal.quant_engine.risk.adaptive_exposure import (
    AdaptiveExposureController,
    CashAllocationCause,
    ExposureEvidenceInputs,
    ExposureParticipationState,
    attribute_cash,
)


def _inputs(**overrides: object) -> ExposureEvidenceInputs:
    values: dict[str, object] = {
        "risk_on_probability": 0.75,
        "risk_off_probability": 0.10,
        "regime_confidence": 0.80,
        "breadth": 0.80,
        "trend": 0.85,
        "volatility_score": 0.20,
        "drawdown_score": 0.10,
        "opportunity_quality": 0.85,
        "alpha_confidence": 0.75,
        "concentration_risk": 0.20,
        "liquidity_score": 0.90,
        "risk_budget_headroom": 0.80,
        "uncertainty": 0.15,
        "correlation_risk": 0.20,
        "current_exposure": 0.60,
        "recovery_signal": 0.80,
    }
    values.update(overrides)
    return ExposureEvidenceInputs(**values)


def test_controller_increases_participation_only_with_broad_confirmed_evidence() -> None:
    controller = AdaptiveExposureController()
    decision = controller.decide(_inputs())
    assert decision.target_gross_exposure >= decision.current_exposure
    assert decision.target_net_exposure == decision.target_gross_exposure
    assert decision.exposure_confidence > 0
    assert decision.shadow_only
    assert decision.dominant_drivers
    assert decision.participation_state in {
        ExposureParticipationState.NORMAL,
        ExposureParticipationState.HIGH,
        ExposureParticipationState.MAX_ALLOWED,
    }


def test_controller_defends_and_never_increases_in_crisis() -> None:
    controller = AdaptiveExposureController()
    decision = controller.decide(
        _inputs(
            risk_on_probability=0.05,
            risk_off_probability=0.90,
            breadth=0.15,
            trend=0.10,
            volatility_score=0.95,
            drawdown_score=0.90,
            liquidity_score=0.30,
            current_exposure=0.70,
            recovery_signal=0.0,
        )
    )
    assert decision.target_gross_exposure <= 0.70
    assert decision.participation_state is ExposureParticipationState.DEFENSIVE
    assert "DEFENSIVE_RISK_CAP" in decision.binding_constraints


def test_hysteresis_avoids_small_whipsaw_but_allows_recovery() -> None:
    controller = AdaptiveExposureController(max_step=0.20, hysteresis=0.05)
    first = controller.decide(_inputs(current_exposure=0.60))
    second = controller.decide(_inputs(current_exposure=first.final_target, trend=0.82))
    assert abs(second.final_target - first.final_target) <= 0.05
    recovery = controller.decide(
        _inputs(
            current_exposure=second.final_target,
            recovery_signal=1.0,
            breadth=1.0,
            trend=1.0,
        )
    )
    assert recovery.recovery_phase
    assert recovery.final_target >= second.final_target


def test_cash_attribution_does_not_hide_optimizer_residual_or_data_block() -> None:
    artifact = attribute_cash(
        actual_cash=0.30,
        target_cash=0.10,
        data_quality_blocked=False,
        valid_opportunity=True,
        optimizer_residual=0.01,
    )
    assert artifact.cause is CashAllocationCause.OPTIMIZER_ARTIFACT_CASH
    blocked = attribute_cash(
        actual_cash=0.50,
        target_cash=0.10,
        data_quality_blocked=True,
        valid_opportunity=True,
    )
    assert blocked.cause is CashAllocationCause.DATA_QUALITY_CASH
