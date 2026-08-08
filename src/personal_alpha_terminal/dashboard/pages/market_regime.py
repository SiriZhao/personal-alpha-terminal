from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.analysis.market_regime.schemas import MarketRegimeResult
from personal_alpha_terminal.dashboard.charts import (
    market_regime_calibration_curve,
    market_regime_distribution_chart,
    market_regime_history_chart,
)
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    market_regime_database_ready,
    market_regime_service,
)

FEATURE_LABELS = {
    "vix_level": "VIX 水平",
    "rate_change": "利率变化",
    "dollar_trend": "美元指数趋势",
    "index_trend": "指数趋势",
    "market_breadth": "市场宽度",
    "volume_breadth": "成交量宽度",
}
REGIME_LABELS = {
    "risk_on": "Risk-On",
    "risk_off": "Risk-Off",
    "neutral": "Neutral",
}


def default_index(
    instruments: tuple[GraphInstrument, ...],
    symbols: tuple[str, ...],
) -> int:
    for index, instrument in enumerate(instruments):
        if instrument.symbol.upper() in symbols:
            return index
    return 0


require_database()
page_header(
    "市场状态识别",
    "基于波动率、利率、美元、指数趋势、市场宽度和成交量的可解释统计模型。",
)

if not market_regime_database_ready():
    st.warning("市场状态表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

with market_regime_service() as service:
    instruments = service.list_instruments()

if len(instruments) < 4:
    empty_state(
        "市场状态模型至少需要四个已登记驱动资产。",
        hint="请登记 VIX、利率、美元指数和市场基准，并更新足够长的日行情。",
    )
    st.stop()

driver_columns = st.columns(2)
with driver_columns[0]:
    vix = st.selectbox(
        "VIX / 波动率指数",
        instruments,
        index=default_index(instruments, ("^VIX", "VIX")),
        format_func=lambda item: item.label,
        key="regime-vix",
    )
    dollar = st.selectbox(
        "美元指数",
        instruments,
        index=default_index(instruments, ("DX-Y.NYB", "DXY", "DX=F")),
        format_func=lambda item: item.label,
        key="regime-dollar",
    )
with driver_columns[1]:
    rate = st.selectbox(
        "利率",
        instruments,
        index=default_index(instruments, ("^TNX", "^TYX", "^FVX")),
        format_func=lambda item: item.label,
        key="regime-rate",
    )
    benchmark = st.selectbox(
        "市场基准指数",
        instruments,
        index=default_index(instruments, ("^GSPC", "SPY", "000001")),
        format_func=lambda item: item.label,
        key="regime-benchmark",
    )

market = st.selectbox(
    "市场宽度股票池",
    ("US", "HK", "A"),
    index=("US", "HK", "A").index(benchmark.market),
    key="regime-market",
)

today = date.today()
date_columns = st.columns(2)
with date_columns[0]:
    start_date = st.date_input(
        "展示起始日期",
        value=today - timedelta(days=365),
        max_value=today,
        key="regime-start",
    )
with date_columns[1]:
    end_date = st.date_input(
        "截止日期",
        value=today,
        max_value=today,
        key="regime-end",
    )

run_clicked = st.button(
    "识别并保存市场状态",
    type="primary",
    key="regime-run",
)

result: MarketRegimeResult | None = None
if run_clicked:
    try:
        with st.spinner("正在构建因果滚动特征并执行样本外校准验证……"):
            with market_regime_service() as service:
                result = service.run(
                    vix_stock_id=vix.id,
                    rate_stock_id=rate.id,
                    dollar_stock_id=dollar.id,
                    benchmark_stock_id=benchmark.id,
                    market=market,
                    start_date=start_date,
                    end_date=end_date,
                )
        st.success(f"市场状态分析已保存，运行编号 #{result.run_id}")
    except ValueError as error:
        st.error(f"无法识别市场状态：{error}")
else:
    with market_regime_service() as service:
        result = service.latest()

if result is None:
    empty_state("尚无市场状态分析结果。")
    st.stop()

current = result.current
probabilities = current.probabilities
display_values = probabilities or current.scores
metrics = st.columns(4)
metrics[0].metric("当前状态", REGIME_LABELS[current.regime])
metrics[1].metric(
    "最高校准概率" if probabilities is not None else "最高市场状态评分",
    f"{max(display_values.values()):.1%}",
)
metrics[2].metric("综合风险评分", f"{current.composite_score:+.3f}")
metrics[3].metric("宽度样本", current.breadth_constituent_count)
st.caption(
    f"截至 {current.as_of_date} · {result.model_type} v{result.model_version} "
    f"· 运行编号 #{result.run_id} · calibration={result.calibration.status}"
)

chart_columns = st.columns((1, 2))
with chart_columns[0]:
    st.plotly_chart(
        market_regime_distribution_chart(
            current,
            title=("当前校准状态概率" if probabilities is not None else "市场状态评分"),
        ),
        width="stretch",
        key=f"regime-current-{result.run_id}",
    )
with chart_columns[1]:
    st.plotly_chart(
        market_regime_history_chart(
            result.observations,
            title=("校准状态概率历史" if probabilities is not None else "市场状态评分历史"),
        ),
        width="stretch",
        key=f"regime-history-{result.run_id}",
    )

st.subheader("Walk-Forward Calibration")
calibration_metrics = st.columns(4)
calibration_metrics[0].metric(
    "输出口径",
    "Probability" if result.calibration.probability_output_enabled else "市场状态评分",
)
calibration_metrics[1].metric(
    "Brier Score",
    (
        f"{result.calibration.brier_score:.4f}"
        if result.calibration.brier_score is not None
        else "N/A"
    ),
)
calibration_metrics[2].metric(
    "Raw Score Brier",
    (
        f"{result.calibration.raw_score_brier:.4f}"
        if result.calibration.raw_score_brier is not None
        else "N/A"
    ),
)
calibration_metrics[3].metric(
    "OOS 样本",
    result.calibration.out_of_sample_count,
)
if result.calibration.calibration_curve:
    st.plotly_chart(
        market_regime_calibration_curve(result.calibration),
        width="stretch",
        key=f"regime-calibration-{result.run_id}",
    )
if result.calibration.reasons:
    st.warning("概率输出未通过：" + "；".join(result.calibration.reasons))
st.caption(
    "Brier Score 越低越好；只有严格 walk-forward 样本外结果同时优于原始 Score "
    "和扩展窗口基准，并通过数据与样本门禁，才允许显示 Probability。"
)

st.subheader("当前特征解释")
st.dataframe(
    [
        {
            "特征": FEATURE_LABELS[feature],
            "原始值": current.feature_values[feature],
            "历史 Z-score": current.feature_zscores[feature],
            "Risk-On 方向贡献": current.feature_contributions[feature],
        }
        for feature in FEATURE_LABELS
    ],
    width="stretch",
    hide_index=True,
    column_config={
        "原始值": st.column_config.NumberColumn(format="%.4f"),
        "历史 Z-score": st.column_config.NumberColumn(format="%+.3f"),
        "Risk-On 方向贡献": st.column_config.NumberColumn(format="%+.3f"),
    },
)

with st.expander("模型口径与限制"):
    st.markdown(
        """
- 所有 Z-score 只使用当前日期之前的历史观察，避免未来数据泄漏。
- VIX、利率变化和美元走强对应负权重；指数趋势、市场宽度和上涨成交量对应正权重。
- Softmax 仅称为 Market Regime Score，不是概率。
- 校准标签使用基准未来交易日收益，但每个预测日只训练于结果已在此前完成的样本。
- Probability 必须通过 walk-forward 样本外 Brier Score、类别覆盖和数据认证门禁。
- 市场宽度使用当前仍活跃的股票，存在幸存者偏差；第一版未维护历史指数成分。
- 不同市场收盘时点不同，精确日期对齐不能消除异步交易影响。
- 输出用于研究和风险语境判断，不构成预测、仓位建议或交易信号。
"""
    )
