from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupState:
    """Non-blocking launch status shown by the main dashboard."""

    can_enter_dashboard: bool
    database_status: str
    configuration_status: str
    data_gate_status: str
    reasons: tuple[str, ...]
    notices: tuple[str, ...]


def assess_startup(
    *,
    database_ready: bool,
    configuration_exists: bool,
    data_gate_status: str,
    gate_reasons: tuple[str, ...] = (),
) -> StartupState:
    """Report launch health without turning optional setup into an access gate."""

    normalized_gate = data_gate_status.upper().strip() or "BLOCKED"
    reasons = list(gate_reasons)
    notices: list[str] = []
    if not database_ready:
        normalized_gate = "BLOCKED"
        reasons.insert(0, "研究数据库尚未初始化")
    if not configuration_exists:
        notices.append("配置文件尚未创建；当前使用安全默认值")
    if normalized_gate == "BLOCKED" and not reasons:
        reasons.append("未导入或未认证市场数据")
    return StartupState(
        can_enter_dashboard=True,
        database_status="READY" if database_ready else "NOT_INITIALIZED",
        configuration_status="READY" if configuration_exists else "DEFAULTS",
        data_gate_status=normalized_gate,
        reasons=tuple(dict.fromkeys(reasons)),
        notices=tuple(notices),
    )
