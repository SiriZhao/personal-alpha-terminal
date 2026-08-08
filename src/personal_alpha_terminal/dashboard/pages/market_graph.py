from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.market_graph.schemas import MarketGraphResult
from personal_alpha_terminal.dashboard.charts import market_graph_chart
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    market_graph_database_ready,
    market_graph_service,
)

RELATIONSHIP_LABELS = {
    "相关性": "correlation",
    "领先关系": "lead_lag",
    "资金传导代理": "capital_transmission",
}

require_database()
page_header(
    "市场图谱",
    "构建股票、ETF、指数和商品之间的动态统计关系网络",
)

if not market_graph_database_ready():
    st.warning("市场图谱表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

with market_graph_service() as service:
    instruments = service.list_instruments()

if len(instruments) < 2:
    empty_state(
        "当前数据库中不足两个可分析资产。",
        hint="请先登记资产并更新足够的日行情和成交量数据。",
    )
    st.stop()

selected = st.multiselect(
    "网络节点",
    instruments,
    default=instruments[: min(8, len(instruments))],
    format_func=lambda item: item.label,
    key="market-graph-instruments",
)

today = date.today()
date_columns = st.columns(2)
with date_columns[0]:
    start_date = st.date_input(
        "网络起始日期",
        value=today - timedelta(days=730),
        max_value=today,
        key="market-graph-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "网络截止日期",
        value=today,
        max_value=today,
        key="market-graph-end",
    )

run_clicked = st.button(
    "构建并保存网络",
    type="primary",
    disabled=len(selected) < 2,
    key="market-graph-run",
)

result: MarketGraphResult | None = None
if run_clicked:
    try:
        with st.spinner("正在计算边关系、中心性和传导路径……"):
            with market_graph_service() as service:
                result = service.run(
                    instrument_ids=tuple(item.id for item in selected),
                    start_date=start_date,
                    end_date=end_date,
                )
        st.success(f"网络快照已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法构建网络：{error}")
else:
    with market_graph_service() as service:
        result = service.latest()

if result is None:
    empty_state("尚无市场图谱结果。")
    st.stop()

relationship_selection = st.multiselect(
    "显示边类型",
    tuple(RELATIONSHIP_LABELS),
    default=tuple(RELATIONSHIP_LABELS),
    key=f"market-graph-edge-types-{result.run_id}",
)
selected_types = {RELATIONSHIP_LABELS[label] for label in relationship_selection}
visible_edges = tuple(edge for edge in result.edges if edge.relationship_type in selected_types)

metrics = st.columns(4)
metrics[0].metric("节点", len(result.nodes))
metrics[1].metric("关系边", len(result.edges))
metrics[2].metric("传导路径", len(result.paths))
metrics[3].metric("运行编号", f"#{result.run_id}")
st.caption(f"网络区间：{result.start_date} 至 {result.end_date}")

st.plotly_chart(
    market_graph_chart(
        result.nodes,
        visible_edges,
        title="动态市场关系网络",
    ),
    width="stretch",
    key=f"market-graph-chart-{result.run_id}",
)

if visible_edges:
    st.dataframe(
        [
            {
                "来源": edge.source.symbol,
                "目标": edge.target.symbol,
                "关系": edge.relationship_type,
                "强度": edge.strength,
                "原始 p 值": edge.p_value,
                "FDR q 值": edge.fdr_q_value,
                "Bonferroni p 值": edge.bonferroni_p_value,
            }
            for edge in visible_edges
        ],
        width="stretch",
        hide_index=True,
        column_config={
            column: st.column_config.NumberColumn(format="%.4f")
            for column in ("强度", "原始 p 值", "FDR q 值", "Bonferroni p 值")
        },
    )

st.subheader("核心资产")
st.dataframe(
    [
        {
            "资产": node.instrument.label,
            "类型": node.instrument.asset_type,
            "行业": node.instrument.industry or "未分类",
            "度中心性": node.degree_centrality,
            "介数中心性": node.betweenness_centrality,
            "影响力": node.influence,
            "关联强度": node.association_strength,
            "核心分数": node.core_score,
        }
        for node in result.nodes
    ],
    width="stretch",
    hide_index=True,
    column_config={
        column: st.column_config.NumberColumn(format="%.3f")
        for column in (
            "度中心性",
            "介数中心性",
            "影响力",
            "关联强度",
            "核心分数",
        )
    },
)

st.subheader("统计传导路径")
if not result.paths:
    st.info("当前阈值下没有发现三节点方向传导路径。")
else:
    st.dataframe(
        [
            {
                "排名": path.rank,
                "路径": " → ".join(node.symbol for node in path.nodes),
                "边类型": " → ".join(path.relationship_types),
                "综合强度": path.aggregate_strength,
                "累计滞后": f"{path.total_lag_days}日",
            }
            for path in result.paths
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "综合强度": st.column_config.NumberColumn(format="%.3f"),
        },
    )

with st.expander("方法与限制"):
    st.markdown(
        """
- 相关边是同期日收益 Pearson 相关，图中作为无方向关系。
- 领先边比较1至5个共同交易观测的滞后相关，并要求优于同期相关。
- “资金传导”使用方向收益乘以异常成交量的代理变量，不是真实资金流。
- 影响力使用有向关系图的 PageRank；核心分数综合中心性、影响力和关联强度。
- 三节点路径是统计传导链，不等于企业真实供应链或因果产业链。
- 所有资产对、方向和滞后先组成统一检验族，再同时计算 Benjamini-Hochberg FDR 与
  Bonferroni 校正；仅通过配置校正口径的边进入网络。
- p值使用一阶自相关修正后的有效样本量，但仍不等于因果证据，也不能完全消除异方差与结构突变风险。
"""
    )
