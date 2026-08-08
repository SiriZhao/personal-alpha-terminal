from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ConditionalProbabilityStudy,
)
from personal_alpha_terminal.dashboard.charts import conditional_probability_chart
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    conditional_probability_database_ready,
    conditional_probability_service,
    event_study_database_ready,
)

require_database()
page_header(
    "条件概率",
    "估计 P(B未来上涨或下跌 | A事件发生)，并强制执行最小样本限制",
)

if not event_study_database_ready() or not conditional_probability_database_ready():
    st.warning("条件概率相关表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

with conditional_probability_service() as service:
    definitions = service.list_definitions()
    instruments = service.list_instruments()
    configured_minimum = service.minimum_sample_size()

if not definitions:
    empty_state(
        "尚无可用事件定义。",
        hint="请先在“事件研究”页面创建条件A，例如“NVDA单日上涨超过8%”。",
    )
    st.stop()
if not instruments:
    empty_state("股票主数据为空。")
    st.stop()

condition = st.selectbox(
    "条件 A",
    definitions,
    format_func=lambda item: item.label,
    key="conditional-definition",
)
instrument_columns = st.columns(2)
with instrument_columns[0]:
    trigger = st.selectbox(
        "A 的触发证券",
        instruments,
        format_func=lambda item: item.label,
        key="conditional-trigger",
    )
with instrument_columns[1]:
    targets = st.multiselect(
        "结果 B 的证券",
        instruments,
        default=instruments[: min(3, len(instruments))],
        format_func=lambda item: item.label,
        key="conditional-targets",
    )

outcome_columns = st.columns(3)
with outcome_columns[0]:
    direction_label = st.radio(
        "B 的方向",
        ("上涨", "下跌"),
        horizontal=True,
        key="conditional-direction",
    )
with outcome_columns[1]:
    threshold_pct = st.number_input(
        "B 的幅度门槛（%）",
        min_value=0.0,
        max_value=1000.0,
        value=0.0,
        step=0.5,
        key="conditional-threshold",
    )
with outcome_columns[2]:
    confidence_label = st.selectbox(
        "置信水平",
        ("90%", "95%", "99%"),
        index=1,
        key="conditional-confidence",
    )

date_columns = st.columns(2)
today = date.today()
with date_columns[0]:
    start_date = st.date_input(
        "样本起始日期",
        value=today - timedelta(days=5 * 365),
        max_value=today,
        key="conditional-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "样本截止日期",
        value=today,
        max_value=today,
        key="conditional-end",
    )

safeguard_columns = st.columns(2)
with safeguard_columns[0]:
    minimum_sample_size = st.number_input(
        "最小样本数",
        min_value=configured_minimum,
        max_value=10000,
        value=configured_minimum,
        help=(f"系统配置的安全下限为 {configured_minimum}；低于该样本数时不输出概率和平均收益。"),
        key="conditional-minimum-sample",
    )
with safeguard_columns[1]:
    cooldown_days = st.number_input(
        "条件A冷却期（交易日）",
        min_value=0,
        max_value=252,
        value=0,
        help="用于减少相邻条件事件带来的重叠样本。",
        key="conditional-cooldown",
    )

run_clicked = st.button(
    "运行并保存条件概率",
    type="primary",
    disabled=not targets,
    key="conditional-run",
)

result: ConditionalProbabilityStudy | None = None
if run_clicked:
    try:
        confidence_level = {
            "90%": 0.90,
            "95%": 0.95,
            "99%": 0.99,
        }[confidence_label]
        with st.spinner("正在生成事件样本并估计条件概率……"):
            with conditional_probability_service() as service:
                result = service.run(
                    definition_id=condition.id,
                    trigger_stock_id=trigger.id,
                    target_stock_ids=tuple(item.id for item in targets),
                    start_date=start_date,
                    end_date=end_date,
                    outcome_direction="up" if direction_label == "上涨" else "down",
                    outcome_threshold=threshold_pct / 100,
                    minimum_sample_size=int(minimum_sample_size),
                    confidence_level=confidence_level,
                    cooldown_days=int(cooldown_days),
                )
        st.success(f"条件概率研究已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法完成条件概率研究：{error}")
else:
    with conditional_probability_service() as service:
        result = service.latest()

if result is None:
    empty_state("尚无条件概率研究结果。")
    st.stop()

reliable_count = sum(item.meets_minimum for item in result.results)
metrics = st.columns(4)
metrics[0].metric("条件A事件", result.event_count)
metrics[1].metric("推断门槛", result.minimum_sample_size)
metrics[2].metric("可靠结果", f"{reliable_count}/{len(result.results)}")
metrics[3].metric("运行编号", f"#{result.run_id}")

direction_name = "上涨" if result.outcome_direction == "up" else "下跌"
st.caption(
    f"{result.condition.label} · A：{result.trigger.label} · "
    f"B：未来{direction_name}超过 {result.outcome_threshold:.2%} · "
    f"{result.confidence_level:.0%} Beta 后验可信区间"
)

reliable = tuple(item for item in result.results if item.meets_minimum)
if reliable:
    st.plotly_chart(
        conditional_probability_chart(
            reliable,
            title="条件概率及置信区间",
        ),
        width="stretch",
        key=f"conditional-chart-{result.run_id}",
    )
else:
    st.warning("所有结果均低于最小样本门槛，系统已抑制概率、平均收益和置信区间。")

st.dataframe(
    [
        {
            "结果证券": item.target.label,
            "窗口": f"{item.horizon_days}日",
            "样本数": item.sample_size,
            "状态": "可推断" if item.meets_minimum else "样本不足",
            "条件概率": item.probability,
            "原始频率": item.raw_probability,
            "置信下限": item.confidence_lower,
            "置信上限": item.confidence_upper,
            "平均收益": item.average_return,
        }
        for item in result.results
    ],
    width="stretch",
    hide_index=True,
    column_config={
        column: st.column_config.NumberColumn(format="percent")
        for column in ("条件概率", "原始频率", "置信下限", "置信上限", "平均收益")
    },
)

with st.expander("统计口径与限制"):
    st.markdown(
        """
- 1/5/20日按结果证券自己的后续交易观测计算。
- 条件概率分母只包含已走完相应期限的事件，页面同时展示各期限真实样本数。
- 条件概率采用 Beta-Binomial 后验均值，默认 Beta(1,1) 先验；区间为等尾后验可信区间。
- 样本数低于系统门槛时，概率、区间和平均收益均不输出。
- 冷却期可减少相邻条件事件造成的窗口重叠，但不能消除所有序列相关。
- 区间是未做多重比较校正的名义区间；同时筛选大量证券和条件时仍可能出现伪发现。
"""
    )
