import streamlit as st

from personal_alpha_terminal import __build_version__
from personal_alpha_terminal.core.product import PRODUCT_CHANNEL, PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.dashboard.components import apply_product_theme
from personal_alpha_terminal.dashboard.error_handling import render_unhandled_error
from personal_alpha_terminal.dashboard.runtime import database_ready
from personal_alpha_terminal.dashboard.startup_diagnostics import (
    initialize_dashboard,
    render_safe_dashboard,
)

st.set_page_config(
    page_title="Personal Alpha Terminal",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)
initialization = initialize_dashboard()
settings = initialization.settings
preferences = initialization.preferences
apply_product_theme(preferences.theme, preferences.market_color_convention)

if settings is None or initialization.issues:
    render_safe_dashboard(initialization.issues)
    st.stop()

with st.sidebar:
    st.markdown(
        f"""
        <div class="pat-eyebrow">{PRODUCT_CHANNEL}</div>
        <div style="font-size:1.35rem;font-weight:720;letter-spacing:-.04em;">
          Personal Alpha<span style="color:#6C8CFF;">.</span>
        </div>
        <div style="color:#7F8CA2;font-size:.76rem;margin-top:.3rem;">
          v{__build_version__} · Personal Quant Investment OS
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    if database_ready():
        st.success("Local database · Ready", icon=":material/check_circle:")
    else:
        st.error("Database · Offline", icon=":material/database:")
    st.divider()
    st.caption(
        f"模式 · {preferences.run_mode.value.replace('_', ' ').title()}\n\n"
        "量化生成 · 人工确认 · 不自动交易"
    )

navigation = st.navigation(
    {
        "首页": [
            st.Page(
                "pages/daily_dashboard.py",
                title="Quant Dashboard",
                icon=":material/space_dashboard:",
                default=True,
            ),
        ],
        "Portfolio": [
            st.Page(
                "pages/portfolio.py",
                title="我的组合",
                icon=":material/account_balance_wallet:",
            ),
            st.Page("pages/risk.py", title="风险分析", icon=":material/security:"),
            st.Page(
                "pages/scenario_simulator.py",
                title="情景模拟",
                icon=":material/crisis_alert:",
            ),
        ],
        "Actions": [
            st.Page(
                "pages/action_center.py",
                title="行动中心",
                icon=":material/task_alt:",
            ),
        ],
        "Research": [
            st.Page(
                "pages/research_center.py",
                title="量化研究",
                icon=":material/biotech:",
            ),
            st.Page("pages/stock_detail.py", title="股票详情", icon=":material/candlestick_chart:"),
            st.Page("pages/event_study.py", title="事件研究", icon=":material/experiment:"),
            st.Page(
                "pages/conditional_probability.py", title="条件证据", icon=":material/percent:"
            ),
            st.Page("pages/relationships.py", title="市场关系", icon=":material/hub:"),
            st.Page("pages/market_graph.py", title="市场图谱", icon=":material/account_tree:"),
            st.Page("pages/lead_lag.py", title="领先滞后", icon=":material/timeline:"),
            st.Page("pages/market_regime.py", title="市场状态", icon=":material/speed:"),
            st.Page("pages/factor_research.py", title="因子研究", icon=":material/functions:"),
            st.Page(
                "pages/us_adaptive_alpha.py", title="US Adaptive Alpha", icon=":material/shield:"
            ),
        ],
        "Backtest": [
            st.Page(
                "pages/backtest_center.py",
                title="策略回测",
                icon=":material/monitoring:",
            ),
        ],
        "Settings": [
            st.Page("pages/data_sources.py", title="数据源", icon=":material/database:"),
            st.Page("pages/settings.py", title="系统设置", icon=":material/settings:"),
            st.Page("pages/diagnostics.py", title="系统诊断", icon=":material/monitor_heart:"),
            st.Page("pages/about.py", title="关于", icon=":material/info:"),
        ],
    }
)
try:
    navigation.run()
except Exception as error:
    render_unhandled_error(error)

with st.sidebar:
    st.divider()
    st.caption(PRODUCT_DISPLAY_NAME)
