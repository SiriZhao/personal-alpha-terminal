from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.event_study.schemas import EventStudyResult
from personal_alpha_terminal.dashboard.charts import event_probability_chart
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    event_study_database_ready,
    event_study_service,
)

RULE_LABELS = {
    "单日涨跌幅": "price_return",
    "成交量异常": "volume_spike",
    "突破历史新高": "new_high",
}

require_database()
page_header(
    "事件研究",
    "扫描历史同类事件，并评估不同证券在后续交易日的收益和路径风险",
)

if not event_study_database_ready():
    st.warning("事件研究表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

with event_study_service() as service:
    instruments = service.list_instruments()
    definitions = service.list_definitions()

with st.expander("新建或升级事件定义", expanded=not definitions):
    name = st.text_input("定义名称", value="单日大涨事件", key="event-definition-name")
    description = st.text_input(
        "说明",
        value="触发证券单日复权收盘收益超过阈值",
        key="event-definition-description",
    )
    rule_label = st.selectbox("事件类型", tuple(RULE_LABELS), key="event-rule-type")
    rule_type = RULE_LABELS[rule_label]
    parameters: dict[str, object]
    if rule_type == "price_return":
        threshold_pct = st.number_input(
            "涨跌幅阈值（%）",
            min_value=0.1,
            max_value=100.0,
            value=8.0,
            step=0.5,
            key="event-price-threshold",
        )
        direction_label = st.radio(
            "方向",
            ("上涨超过阈值", "下跌超过阈值"),
            horizontal=True,
            key="event-price-direction",
        )
        parameters = {
            "threshold": threshold_pct / 100,
            "direction": "above" if direction_label.startswith("上涨") else "below",
        }
    elif rule_type == "volume_spike":
        lookback_days = st.number_input(
            "历史均量窗口",
            min_value=2,
            max_value=252,
            value=20,
            key="event-volume-lookback",
        )
        multiplier = st.number_input(
            "成交量倍数",
            min_value=0.1,
            max_value=20.0,
            value=2.0,
            step=0.1,
            key="event-volume-multiplier",
        )
        parameters = {
            "lookback_days": int(lookback_days),
            "multiplier": multiplier,
        }
    else:
        lookback_days = st.number_input(
            "历史高点窗口",
            min_value=2,
            max_value=2520,
            value=252,
            key="event-high-lookback",
        )
        buffer_pct = st.number_input(
            "突破缓冲（%）",
            min_value=0.0,
            max_value=20.0,
            value=0.0,
            step=0.1,
            key="event-high-buffer",
        )
        parameters = {
            "lookback_days": int(lookback_days),
            "breakout_buffer": buffer_pct / 100,
        }
    if st.button("保存定义版本", key="event-save-definition"):
        try:
            with event_study_service() as service:
                saved = service.create_definition(
                    name=name,
                    description=description,
                    rule_type=rule_type,
                    parameters=parameters,
                )
            st.success(f"已保存 {saved.label}")
            st.rerun()
        except ValueError as error:
            st.error(f"无法保存定义：{error}")

if not instruments:
    empty_state(
        "股票主数据为空。",
        hint="请先登记股票或 ETF，并通过 Market Data Engine 更新日行情。",
    )
    st.stop()
if not definitions:
    empty_state("尚无事件定义。", hint="请先在上方创建一个可复用事件定义。")
    st.stop()

definition = st.selectbox(
    "事件定义",
    definitions,
    format_func=lambda item: item.label,
    key="event-selected-definition",
)
selection_columns = st.columns(2)
with selection_columns[0]:
    trigger = st.selectbox(
        "触发证券",
        instruments,
        format_func=lambda item: item.label,
        key="event-trigger",
    )
with selection_columns[1]:
    targets = st.multiselect(
        "响应证券",
        instruments,
        default=instruments[: min(3, len(instruments))],
        format_func=lambda item: item.label,
        key="event-targets",
    )

today = date.today()
date_columns = st.columns(2)
with date_columns[0]:
    start_date = st.date_input(
        "事件起始日期",
        value=today - timedelta(days=5 * 365),
        max_value=today,
        key="event-study-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "样本截止日期",
        value=today,
        max_value=today,
        key="event-study-end",
    )

advanced_columns = st.columns(2)
with advanced_columns[0]:
    cooldown_days = st.number_input(
        "事件冷却期（触发证券交易日）",
        min_value=1,
        max_value=252,
        value=5,
        help="连续触发会被聚合为一个事件簇；默认冷却5个触发证券交易日。",
        key="event-cooldown",
    )
with advanced_columns[1]:
    win_threshold_pct = st.number_input(
        "胜率门槛（%）",
        min_value=-99.0,
        max_value=1000.0,
        value=0.0,
        step=0.5,
        help="上涨概率固定统计收益>0；胜率统计收益超过该门槛。",
        key="event-win-threshold",
    )

run_clicked = st.button(
    "运行并保存事件研究",
    type="primary",
    disabled=not targets,
    key="event-study-run",
)

result: EventStudyResult | None = None
if run_clicked:
    try:
        with st.spinner("正在扫描事件并计算前瞻分布……"):
            with event_study_service() as service:
                result = service.run(
                    definition_id=definition.id,
                    trigger_stock_id=trigger.id,
                    target_stock_ids=tuple(item.id for item in targets),
                    start_date=start_date,
                    end_date=end_date,
                    cooldown_days=int(cooldown_days),
                    win_threshold=win_threshold_pct / 100,
                )
        st.success(f"事件研究已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法完成事件研究：{error}")
else:
    with event_study_service() as service:
        result = service.latest()

if result is None:
    empty_state("尚无事件研究结果。")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("历史事件", len(result.occurrences))
metrics[1].metric("响应证券", len({item.target.id for item in result.statistics}))
metrics[2].metric("最长期限", f"{max(result.horizons)}日")
metrics[3].metric("运行编号", f"#{result.run_id}")
st.caption(
    f"{result.definition.label} · 触发：{result.trigger.label} · "
    f"{result.start_date} 至 {result.end_date}"
)

if not result.occurrences:
    st.info("该区间没有检测到符合定义的历史事件。")
elif not result.statistics:
    st.info("已检测到事件，但样本截止日前没有走完所选前瞻期限的有效样本。")
else:
    st.plotly_chart(
        event_probability_chart(
            result.statistics,
            title="事件发生后的上涨概率",
        ),
        width="stretch",
        key=f"event-probability-{result.run_id}",
    )
    st.dataframe(
        [
            {
                "响应证券": item.target.label,
                "期限": f"{item.horizon_days}日",
                "有效样本": item.sample_size,
                "推断状态": "可推断" if item.meets_minimum else "低可信（仅描述）",
                "上涨概率": item.positive_probability,
                "上涨概率下限": item.positive_probability_lower,
                "上涨概率上限": item.positive_probability_upper,
                "胜率": item.win_rate,
                "平均收益": item.average_return,
                "平均收益下限": item.average_return_lower,
                "平均收益上限": item.average_return_upper,
                "中位收益": item.median_return,
                "收益波动": item.return_stddev,
                "最佳收益": item.best_return,
                "最差收益": item.worst_return,
                "平均最大上涨": item.average_max_upside,
                "最坏最大回撤": item.worst_max_drawdown,
            }
            for item in result.statistics
        ],
        width="stretch",
        hide_index=True,
        column_config={
            column: st.column_config.NumberColumn(format="percent")
            for column in (
                "上涨概率",
                "上涨概率下限",
                "上涨概率上限",
                "胜率",
                "平均收益",
                "平均收益下限",
                "平均收益上限",
                "中位收益",
                "收益波动",
                "最佳收益",
                "最差收益",
                "平均最大上涨",
                "最坏最大回撤",
            )
        },
    )

with st.expander("方法与限制"):
    st.markdown(
        """
- 事件判定只使用事件日及之前的行情，不使用未来数据。
- 1/3/5/10/20日表示响应证券自身的后续交易观测数，不是自然日。
- 前瞻收益以事件日或此前最近一个有效收盘为基准，未来路径严格从事件日之后开始。
- 连续触发按候选事件簇去重，冷却窗口使用触发证券的交易观测数。
- 未走完某期限的右端样本不进入该期限统计，因此各期限有效样本数可能不同。
- 上涨概率和胜率使用 Wilson 区间；平均收益使用保持局部依赖的移动块 Bootstrap 区间。
- 样本少于30时只展示描述统计，区间为空且状态固定为低可信。
- 最大上涨从包含基准日的路径计算；最大回撤是路径内从历史峰值到低点的最差跌幅。
- 日线事件研究不能证明因果关系，跨时区市场尤其需要结合信息发生时间进一步验证。
"""
    )
