from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.lead_lag.schemas import LeadLagAnalysisResult
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.dashboard.charts import lead_lag_confidence_chart
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    lead_lag_database_ready,
    lead_lag_service,
)

require_database()
page_header(
    "领先滞后分析",
    "用 Cross Correlation 定位响应时间，并用 Granger F 检验和多重检验校正评估证据。",
)

if not lead_lag_database_ready():
    st.warning("领先滞后分析表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

with lead_lag_service() as service:
    instruments = service.list_instruments()

if len(instruments) < 2:
    empty_state(
        "当前数据库中不足两个可分析资产。",
        hint="请先登记资产，并写入足够长的日行情历史。",
    )
    st.stop()

settings = get_settings()
selected = st.multiselect(
    "分析资产",
    instruments,
    default=instruments[: min(6, len(instruments))],
    format_func=lambda item: item.label,
    key="lead-lag-instruments",
)

today = date.today()
date_columns = st.columns(3)
with date_columns[0]:
    start_date = st.date_input(
        "起始日期",
        value=today - timedelta(days=730),
        max_value=today,
        key="lead-lag-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "截止日期",
        value=today,
        max_value=today,
        key="lead-lag-end",
    )
with date_columns[2]:
    maximum_lag_days = st.number_input(
        "最大响应滞后（交易日）",
        min_value=1,
        max_value=settings.lead_lag_maximum_lag_days,
        value=settings.lead_lag_maximum_lag_days,
        step=1,
        key="lead-lag-maximum-lag",
    )

run_clicked = st.button(
    "运行并保存分析",
    type="primary",
    disabled=len(selected) < 2,
    key="lead-lag-run",
)

result: LeadLagAnalysisResult | None = None
if run_clicked:
    try:
        with st.spinner("正在运行有向资产对的 Cross Correlation 与 Granger 检验……"):
            with lead_lag_service() as service:
                result = service.run(
                    instrument_ids=tuple(item.id for item in selected),
                    start_date=start_date,
                    end_date=end_date,
                    maximum_lag_days=int(maximum_lag_days),
                )
        st.success(f"分析已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法运行分析：{error}")
else:
    with lead_lag_service() as service:
        result = service.latest()

if result is None:
    empty_state("尚无领先滞后分析结果。")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("有向资产对", len(result.pairs))
metrics[1].metric("可信关系", len(result.significant_pairs))
metrics[2].metric(
    "最高可信度",
    f"{max((item.confidence_score for item in result.pairs), default=0):.1%}",
)
metrics[3].metric("运行编号", f"#{result.run_id}")
st.caption(f"分析区间：{result.start_date} 至 {result.end_date}")

if result.significant_pairs:
    st.plotly_chart(
        lead_lag_confidence_chart(
            result.significant_pairs,
            title="通过阈值的领先关系",
        ),
        width="stretch",
        key=f"lead-lag-confidence-{result.run_id}",
    )
else:
    st.info("当前 FDR 与相关强度阈值下，没有发现可信领先关系。")

st.subheader("有向资产对证据")
st.dataframe(
    [
        {
            "领先资产": pair.source.label,
            "响应资产": pair.target.label,
            "响应滞后": pair.best_lag_days,
            "Cross Correlation": pair.cross_correlation,
            "Granger F": pair.granger_f_statistic,
            "原始 p": pair.raw_p_value,
            "滞后校正 p": pair.lag_adjusted_p_value,
            "FDR q": pair.q_value,
            "证据可信度": pair.confidence_score,
            "样本": pair.sample_size,
            "通过阈值": pair.is_significant,
        }
        for pair in result.pairs
    ],
    width="stretch",
    hide_index=True,
    column_config={
        "Cross Correlation": st.column_config.NumberColumn(format="%.3f"),
        "Granger F": st.column_config.NumberColumn(format="%.3f"),
        "原始 p": st.column_config.NumberColumn(format="%.5f"),
        "滞后校正 p": st.column_config.NumberColumn(format="%.5f"),
        "FDR q": st.column_config.NumberColumn(format="%.5f"),
        "证据可信度": st.column_config.ProgressColumn(
            min_value=0,
            max_value=1,
            format="percent",
        ),
    },
)

with st.expander("方法、可信度与限制"):
    st.markdown(
        "- 输入为复权收盘价日收益率；仅对齐共同交易日，不做前向填充。\n"
        "- 正滞后 `k` 定义为 `corr(A[t], B[t+k])`，"
        "即 A 领先 B `k` 个共同交易观察。\n"
        "- Granger 检验的原假设是 A 的历史值不能改善对 B 的解释；"
        "这里使用 `ssr_ftest`。\n"
        f"- 每个资产对内对 {maximum_lag_days} 个候选滞后做 Bonferroni 校正，"
        "再对全部有向资产对做 Benjamini–Hochberg FDR 校正。\n"
        "- “证据可信度”严格定义为 `1 - q_value`，"
        "不是贝叶斯后验概率，也不是未来上涨概率。\n"
        f"- 只有 `q ≤ {settings.lead_lag_fdr_alpha:.2f}` 且 "
        f"`|Cross Correlation| ≥ "
        f"{settings.lead_lag_minimum_abs_correlation:.2f}` 才标记为通过阈值。\n"
        "- Granger 领先是预测信息关系，不等于经济因果。共同因子、"
        "异步交易时段、结构突变和非平稳性都可能造成伪关系。"
    )
