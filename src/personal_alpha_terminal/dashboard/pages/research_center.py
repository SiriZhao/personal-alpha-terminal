import streamlit as st

from personal_alpha_terminal.dashboard.components import page_header
from personal_alpha_terminal.quant_engine.backends import quant_backend_statuses

page_header(
    "量化研究中心 Quant Research Center",
    "因子、事件、条件证据、市场关系和回测作为决策证据后台独立运行。",
)

groups = (
    ("因子与 Alpha", "Factor ranking、IC、样本外验证与基准比较。", "pages/factor_research.py"),
    ("事件研究", "事件窗口、异常收益、样本量、区间与稳定性。", "pages/event_study.py"),
    (
        "条件证据",
        "条件相对无条件基准的增量证据，不是确定预测。",
        "pages/conditional_probability.py",
    ),
    ("市场关系", "相关性、网络和 Lead-Lag 仅生成候选关系。", "pages/relationships.py"),
    ("市场状态", "未经校准时仅显示 Market Regime Score。", "pages/market_regime.py"),
    ("US Adaptive Alpha", "多 Sleeve 研究、数据门禁与本金保护约束。", "pages/us_adaptive_alpha.py"),
)

for start in range(0, len(groups), 3):
    columns = st.columns(3)
    for column, (title, description, path) in zip(columns, groups[start : start + 3], strict=True):
        with column.container(border=True):
            st.subheader(title)
            st.write(description)
            if st.button("打开研究模块", key=f"research-link-{path}", width="stretch"):
                st.switch_page(path)

st.info(
    "研究结果不会直接覆盖 Decision Engine。只有通过 ResearchDataGate、统计有效性、"
    "组合风险和可交易性约束的确定性结果，才可能进入行动中心。"
)

st.subheader("研究后端状态")
backend_columns = st.columns(3)
for column, backend in zip(backend_columns, quant_backend_statuses(), strict=True):
    with column.container(border=True):
        st.markdown(f"**{backend.name}**")
        st.caption(backend.role)
        if backend.available:
            st.success(f"可用 · {backend.version or 'version unknown'}")
        else:
            st.warning("当前不可用")
        st.caption(backend.limitation)

st.caption(
    "后端状态只表示软件能力可加载，不代表策略已通过真实数据、样本外或实盘验证。"
)
