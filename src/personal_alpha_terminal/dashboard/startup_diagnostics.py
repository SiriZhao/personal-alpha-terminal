from __future__ import annotations

import logging
from dataclasses import dataclass

import streamlit as st

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.core.logging import configure_logging, log_application_start_once
from personal_alpha_terminal.core.product import UserPreferences, load_preferences

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StartupIssue:
    component: str
    status: str
    error_type: str
    guidance: str


@dataclass(frozen=True, slots=True)
class DashboardInitialization:
    settings: Settings | None
    preferences: UserPreferences
    issues: tuple[StartupIssue, ...]


def initialize_dashboard() -> DashboardInitialization:
    """Load non-market application state without letting it produce an HTTP 500."""

    issues: list[StartupIssue] = []
    preferences = load_preferences()
    try:
        settings = get_settings()
    except Exception as error:
        LOGGER.exception("dashboard_startup_config_error")
        issues.append(
            StartupIssue(
                component="Configuration",
                status="Warning",
                error_type=type(error).__name__,
                guidance="检查 config.env；应用未读取或展示任何市场结论。",
            )
        )
        settings = None
    if settings is not None:
        try:
            configure_logging(settings)
            log_application_start_once()
        except Exception as error:
            LOGGER.exception("dashboard_startup_logging_error")
            issues.append(
                StartupIssue(
                    component="Logging",
                    status="Warning",
                    error_type=type(error).__name__,
                    guidance="日志目录当前不可写；可在系统诊断中检查路径。",
                )
            )
    return DashboardInitialization(settings, preferences, tuple(issues))


def render_safe_dashboard(issues: tuple[StartupIssue, ...]) -> None:
    """Render a dependency-light status page when normal navigation cannot initialize."""

    st.title("Personal Alpha Terminal")
    st.caption("Personal Quant Investment OS · Safe Startup Diagnostics")
    st.warning("系统以安全诊断模式启动。配置问题不会被解释为市场或投资信号。")
    metrics = st.columns(3)
    metrics[0].metric("Database", "Warning")
    metrics[1].metric("Data Gate", "BLOCKED")
    metrics[2].metric("AI", "Disabled")
    st.subheader("System Status")
    st.dataframe(
        [
            {
                "组件": issue.component,
                "状态": issue.status,
                "错误类型": issue.error_type,
                "建议": issue.guidance,
            }
            for issue in issues
        ],
        width="stretch",
        hide_index=True,
    )
    st.info("修复配置后刷新页面。数据门禁保持 BLOCKED，不会生成排名、仓位或调仓清单。")
