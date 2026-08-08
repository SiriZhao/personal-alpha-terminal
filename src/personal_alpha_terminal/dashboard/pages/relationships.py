from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.relationships.schemas import RelationshipResult
from personal_alpha_terminal.dashboard.charts import (
    relationship_heatmap,
    rolling_correlation_chart,
)
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    relationship_database_ready,
    relationship_service,
)

DIRECTION_LABELS = {
    "strengthened": "相关增强",
    "weakened": "相关减弱",
    "sign_flip": "方向反转",
}

require_database()
st.warning(
    "相关性变化当前仅为探索性描述，未经过多重检验校正；"
    "不得据此直接交易或调整仓位。需要统计推断时请使用 Market Graph 的 FDR/Bonferroni 结果。"
)
page_header(
    "市场关系",
    "分析股票、ETF 或行业日收益之间的相关结构；结果自动保存到研究数据库",
)

if not relationship_database_ready():
    st.warning("关系分析表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

universe_labels = {
    "股票": "stock",
    "ETF": "etf",
    "行业": "industry",
}
method_labels = {
    "Pearson（线性关系）": "pearson",
    "Spearman（秩关系）": "spearman",
}

control_columns = st.columns([1, 1, 2])
with control_columns[0]:
    universe_label = st.selectbox("分析对象", tuple(universe_labels), key="relationship-universe")
with control_columns[1]:
    method_label = st.selectbox("相关方法", tuple(method_labels), key="relationship-method")

universe_type = universe_labels[universe_label]
method = method_labels[method_label]
with relationship_service() as service:
    entity_options = service.list_entities(universe_type)

if len(entity_options) < 2:
    empty_state(
        f"当前数据库中不足两个可分析的{universe_label}。",
        hint="请先登记证券、行业分类并更新足够的日行情数据。",
    )
    st.stop()

with control_columns[2]:
    selected_entities = st.multiselect(
        "选择分析范围",
        entity_options,
        default=entity_options[: min(6, len(entity_options))],
        format_func=lambda option: option.label,
        key="relationship-entities",
    )

today = date.today()
date_columns = st.columns(2)
with date_columns[0]:
    start_date = st.date_input(
        "起始日期",
        value=today - timedelta(days=730),
        max_value=today,
        key="relationship-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "结束日期",
        value=today,
        max_value=today,
        key="relationship-end",
    )

run_clicked = st.button(
    "运行并保存分析",
    type="primary",
    disabled=len(selected_entities) < 2,
    key="relationship-run",
)

result: RelationshipResult | None = None
if run_clicked:
    try:
        with st.spinner("正在计算相关矩阵、滚动窗口和结构变化……"):
            with relationship_service() as service:
                result = service.run(
                    universe_type=universe_type,
                    entity_ids=tuple(entity.id for entity in selected_entities),
                    method=method,
                    start_date=start_date,
                    end_date=end_date,
                )
        st.success(f"分析已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法完成分析：{error}")
else:
    with relationship_service() as service:
        result = service.latest(universe_type, method)

if result is None:
    empty_state(
        "尚无已保存的分析结果。",
        hint="选择至少两个对象后运行分析；建议准备不少于 180 个共同交易日。",
    )
    st.stop()

method_name = "Pearson" if result.method == "pearson" else "Spearman"
st.caption(
    f"运行 #{result.run_id} · {result.start_date} 至 {result.end_date} · "
    f"{method_name} · {len(result.entities)} 个对象"
)
st.plotly_chart(
    relationship_heatmap(
        result.entities,
        result.matrix,
        title=f"{method_name} 日收益相关矩阵",
    ),
    width="stretch",
    key=f"relationship-heatmap-{result.run_id}",
)

st.subheader("滚动相关性")
pairs = {
    f"{observation.left.label} ↔ {observation.right.label}": (
        observation.left.key,
        observation.right.key,
    )
    for observation in result.matrix
}
if pairs:
    selected_pair_label = st.selectbox(
        "关系对",
        tuple(pairs),
        key=f"relationship-pair-{result.run_id}",
    )
    selected_pair = pairs[selected_pair_label]
    pair_observations = tuple(
        observation
        for observation in result.rolling
        if (observation.left.key, observation.right.key) == selected_pair
    )
    if pair_observations:
        st.plotly_chart(
            rolling_correlation_chart(
                pair_observations,
                title=f"{selected_pair_label} 滚动相关性",
            ),
            width="stretch",
            key=f"relationship-rolling-{result.run_id}",
        )
    else:
        st.info("该关系对尚无完整的 30/90/180 日滚动窗口。")

st.subheader("相关性变化异常")
if not result.anomalies:
    st.info("当前运行未检测到超过阈值的相关性结构变化。")
else:
    st.dataframe(
        [
            {
                "关系对": f"{item.left.label} ↔ {item.right.label}",
                "检测日": item.detected_on,
                "基准相关": item.baseline_correlation,
                "当前相关": item.current_correlation,
                "绝对变化": item.absolute_change,
                "类型": DIRECTION_LABELS[item.direction],
                "基准/当前窗口": (f"{item.baseline_window_days}/{item.current_window_days}"),
            }
            for item in result.anomalies
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "基准相关": st.column_config.NumberColumn(format="%.3f"),
            "当前相关": st.column_config.NumberColumn(format="%.3f"),
            "绝对变化": st.column_config.NumberColumn(format="%.3f"),
        },
    )

with st.expander("方法说明"):
    st.markdown(
        """
- 收益口径：优先使用复权收盘价，计算简单日收益。
- 缺失值：每个关系对只使用双方同日均有收益的数据，不进行前向填充。
- 行业收益：对行业内有数据的成分股日收益做等权平均。
- 滚动窗口：按共同交易观测数计算 30、90、180 日相关。
- 变化检测：比较相邻且不重叠的 90 日基准窗口与最近 30 日窗口。
- 相关性不代表因果或稳定预测关系，异常仅作为进一步研究线索。
"""
    )
