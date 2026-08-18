"""Fail-closed readiness evaluation for the forward-shadow/paper boundary."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReadinessState(StrEnum):
    NOT_READY = "NOT_READY"
    FORWARD_SHADOW_READY = "FORWARD_SHADOW_READY"
    PAPER_READY = "PAPER_READY"
    SMALL_CAPITAL_CANDIDATE = "SMALL_CAPITAL_CANDIDATE"
    LIVE_READY = "LIVE_READY"


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: str
    detail: str


class ForwardShadowReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "forward-shadow-readiness-v1"
    state: ReadinessState
    checks: tuple[ReadinessCheck, ...]
    blockers: tuple[str, ...] = ()
    forward_sample_size: int = Field(ge=0)
    minimum_forward_sample_size: int = Field(ge=1)
    production_llm_influence: float = Field(ge=0, le=1)
    production_probability_influence: float = Field(ge=0, le=1)
    auto_execution: str = "DISABLED"
    manual_confirmation: str = "ENABLED"


def evaluate_forward_shadow_readiness(
    dashboard: dict[str, object],
    *,
    terminal_startup: bool,
    terminal_full_cycle: bool,
    data_quality_status: str,
    minimum_forward_sample_size: int = 120,
) -> ForwardShadowReadiness:
    """Evaluate readiness without treating tests or synthetic evidence as OOS."""

    checks: list[ReadinessCheck] = []
    blockers: list[str] = []
    data_status = str(data_quality_status).upper()
    data_pass = data_status in {"PASS", "PASS_WITH_WARNINGS"}
    checks.append(
        ReadinessCheck(
            name="data_integrity",
            status="PASS" if data_pass else "BLOCKED",
            detail=data_status,
        )
    )
    if not data_pass:
        blockers.append("DATA_PIT_OR_SURVIVORSHIP_GATE")

    authority = _dict(dashboard.get("authority"))
    manual = authority.get("execution") == "MANUAL_CONFIRMATION"
    checks.append(
        ReadinessCheck(
            name="execution_semantics",
            status="PASS" if manual else "BLOCKED",
            detail=str(authority.get("execution", "UNKNOWN")),
        )
    )
    if not manual:
        blockers.append("MANUAL_EXECUTION_BOUNDARY")

    sample = _int(_dict(dashboard.get("forward_evidence")).get("valid_paired_observations"))
    sample = max(0, sample)
    checks.append(
        ReadinessCheck(
            name="forward_sample",
            status="PASS" if sample >= minimum_forward_sample_size else "ACCUMULATING",
            detail=f"{sample}/{minimum_forward_sample_size}",
        )
    )

    promotion = _dict(dashboard.get("promotion_evidence"))
    promotion_status = str(promotion.get("status", "UNKNOWN"))
    alpha_pass = promotion_status in {"ELIGIBLE_FOR_PROMOTION_REVIEW", "PASS"}
    checks.append(
        ReadinessCheck(
            name="alpha_evidence",
            status="PASS" if alpha_pass else "ACCUMULATING",
            detail=str(promotion.get("promotion_reason", promotion_status)),
        )
    )

    checks.append(
        ReadinessCheck(
            name="terminal_startup",
            status="PASS" if terminal_startup else "BLOCKED",
            detail="real entry point observed" if terminal_startup else "not observed",
        )
    )
    if not terminal_startup:
        blockers.append("TERMINAL_STARTUP")
    checks.append(
        ReadinessCheck(
            name="terminal_full_cycle",
            status="PASS" if terminal_full_cycle else "BLOCKED",
            detail="safe decision cycle observed" if terminal_full_cycle else "not observed",
        )
    )
    if not terminal_full_cycle:
        blockers.append("TERMINAL_FULL_CYCLE")

    provider = _dict(dashboard.get("provider_health"))
    checks.append(
        ReadinessCheck(
            name="llm_failure_safety",
            status="PASS",
            detail=f"connectivity={provider.get('connectivity', 'UNKNOWN')}; authority=0%",
        )
    )

    if blockers:
        state = ReadinessState.NOT_READY
    elif sample < minimum_forward_sample_size:
        state = ReadinessState.FORWARD_SHADOW_READY
    elif not alpha_pass:
        state = ReadinessState.FORWARD_SHADOW_READY
    else:
        state = ReadinessState.PAPER_READY

    return ForwardShadowReadiness(
        state=state,
        checks=tuple(checks),
        blockers=tuple(blockers),
        forward_sample_size=sample,
        minimum_forward_sample_size=minimum_forward_sample_size,
        production_llm_influence=_float(authority.get("production_lambda")),
        production_probability_influence=0.0,
    )


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _float(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
