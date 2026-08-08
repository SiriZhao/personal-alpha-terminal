import streamlit as st

from personal_alpha_terminal.dashboard.components import empty_state, page_header
from personal_alpha_terminal.dashboard.runtime import database_ready, home_dashboard_repository

page_header(
    "策略回测 Backtest",
    "统一回测结果与基准比较入口；仅展示通过数据验证并记录运行清单的结果。",
)

result = None
if database_ready():
    try:
        with home_dashboard_repository() as repository:
            result = repository.load().backtest
    except Exception:
        result = None

if result is None:
    empty_state(
        "Data unavailable",
        hint="尚无可认证回测结果。系统不会用演示收益替代真实验证。",
    )
else:
    metrics = st.columns(4)
    metrics[0].metric("策略", result.strategy_name)
    metrics[1].metric("总收益", f"{result.total_return:.2%}")
    metrics[2].metric("最大回撤", f"{result.max_drawdown:.2%}")
    metrics[3].metric("验证问题", result.validation_issue_count)
    st.caption(f"市场 {result.market} · 截止 {result.end_date}")
    if result.validation_issue_count:
        st.warning("该运行仍存在验证问题，不能用于组合决策。")

if st.button("打开因子研究与历史验证"):
    st.switch_page("pages/factor_research.py")
