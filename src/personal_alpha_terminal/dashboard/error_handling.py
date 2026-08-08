from __future__ import annotations

import logging
from uuid import uuid4

import streamlit as st

LOGGER = logging.getLogger(__name__)


def render_unhandled_error(error: Exception) -> None:
    reference = uuid4().hex[:10]
    LOGGER.exception("dashboard_unhandled_error reference=%s", reference)
    st.error("页面暂时无法完成请求。系统已保留脱敏诊断记录。")
    st.markdown(
        "**可能原因**：数据库锁、网络或数据源失败、配置不完整，或当前模块仍被安全门禁阻止。"
    )
    st.markdown("**建议操作**：刷新页面；若持续出现，请在“系统诊断”导出诊断包。")
    st.code(f"诊断编号：{reference}\n错误类型：{type(error).__name__}", language=None)
