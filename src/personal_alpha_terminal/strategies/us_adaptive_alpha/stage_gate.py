from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    ResearchStage,
    StageEvidence,
    StageGateDecision,
)

STAGE_ORDER = (
    ResearchStage.HISTORICAL_RESEARCH,
    ResearchStage.LOCKED_OUT_OF_SAMPLE,
    ResearchStage.FORWARD_OBSERVATION,
    ResearchStage.SHADOW_PORTFOLIO,
    ResearchStage.MANUAL_MICRO_CAPITAL,
    ResearchStage.GRADUAL_SCALE,
)


def assess_stage_gate(
    current_stage: ResearchStage,
    evidence: StageEvidence,
    *,
    minimum_observation_days: int = 126,
    minimum_shadow_days: int = 63,
) -> StageGateDecision:
    """Determine the maximum research stage; never choose real capital automatically."""

    blockers: list[str] = []
    maximum = ResearchStage.HISTORICAL_RESEARCH
    if not evidence.data_gate_passed:
        blockers.append("production data gate has not passed")
    elif not evidence.frozen_parameters:
        blockers.append("parameters are not frozen")
    elif not evidence.locked_test_passed:
        blockers.append("locked out-of-sample test has not passed")
    elif not evidence.benchmark_suite_complete:
        blockers.append("required benchmark suite is incomplete")
    elif not evidence.costs_included:
        blockers.append("cost, spread and slippage validation is incomplete")
    else:
        maximum = ResearchStage.FORWARD_OBSERVATION
        if evidence.observation_days < minimum_observation_days:
            blockers.append(
                "forward-observation history "
                f"{evidence.observation_days} < {minimum_observation_days} sessions"
            )
        elif evidence.operational_incidents > 0:
            blockers.append("forward observation contains unresolved operational incidents")
        else:
            maximum = ResearchStage.SHADOW_PORTFOLIO
            if evidence.shadow_days < minimum_shadow_days:
                blockers.append(
                    f"shadow history {evidence.shadow_days} < {minimum_shadow_days} sessions"
                )
            elif not evidence.manual_risk_approval:
                blockers.append("manual risk approval is required before micro-capital use")
            else:
                maximum = ResearchStage.MANUAL_MICRO_CAPITAL
                blockers.append("gradual scale requires a separate human capital decision")
    passed = STAGE_ORDER.index(current_stage) <= STAGE_ORDER.index(maximum)
    if not passed:
        blockers.append(f"current stage {current_stage} exceeds allowed stage {maximum}")
    return StageGateDecision(
        current_stage=current_stage,
        maximum_allowed_stage=maximum,
        passed=passed,
        blockers=tuple(dict.fromkeys(blockers)),
        automatic_capital_decision_allowed=False,
    )
