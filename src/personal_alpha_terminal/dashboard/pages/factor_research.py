from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.analysis.factors.schemas import (
    FactorBacktestResult,
    FactorSnapshotResult,
)
from personal_alpha_terminal.dashboard.charts import (
    factor_backtest_chart,
    factor_score_chart,
)
from personal_alpha_terminal.dashboard.components import empty_state, page_header, require_database
from personal_alpha_terminal.dashboard.runtime import (
    factor_database_ready,
    factor_research_service,
)

FACTOR_LABELS = {
    "pe": "PE",
    "pb": "PB",
    "fcf_yield": "FCF Yield",
    "revenue_growth": "Revenue Growth",
    "eps_growth": "EPS Growth",
    "roe": "ROE",
    "roic": "ROIC",
    "momentum": "12-1 Momentum",
    "volatility": "Volatility",
}
CATEGORY_LABELS = {
    "value": "价值",
    "growth": "成长",
    "quality": "质量",
    "momentum": "动量",
    "volatility": "低波",
}

require_database()
page_header(
    "因子研究",
    "点时基本面、横截面分位评分，以及无未来数据回填的历史分组回测。",
)

if not factor_database_ready():
    st.warning("因子研究表尚未初始化。请先运行 `pat init-db`，然后刷新页面。")
    st.stop()

snapshot_tab, backtest_tab = st.tabs(("当前因子评分", "历史回测"))
today = date.today()

with snapshot_tab:
    snapshot_columns = st.columns(2)
    with snapshot_columns[0]:
        snapshot_market = st.selectbox(
            "评分市场",
            ("US", "HK", "A"),
            key="factor-snapshot-market",
        )
    with snapshot_columns[1]:
        as_of_date = st.date_input(
            "评分日期",
            value=today,
            max_value=today,
            key="factor-snapshot-date",
        )
    snapshot_clicked = st.button(
        "计算并保存 Factor Score",
        type="primary",
        key="factor-snapshot-run",
    )
    snapshot: FactorSnapshotResult | None = None
    if snapshot_clicked:
        try:
            with st.spinner("正在构造点时财务与价格因子截面……"):
                with factor_research_service() as service:
                    snapshot = service.run_snapshot(
                        market=snapshot_market,
                        as_of_date=as_of_date,
                    )
            st.success(f"评分已保存，运行编号 #{snapshot.run_id}")
        except ValueError as error:
            st.error(f"无法计算因子评分：{error}")
    else:
        with factor_research_service() as service:
            snapshot = service.latest_snapshot()

    if snapshot is None:
        empty_state("尚无因子评分结果。")
    else:
        st.caption(f"{snapshot.market} · 截至 {snapshot.as_of_date} · 运行编号 #{snapshot.run_id}")
        st.plotly_chart(
            factor_score_chart(snapshot.scores, title="综合 Factor Score 排名"),
            width="stretch",
            key=f"factor-score-chart-{snapshot.run_id}",
        )
        st.dataframe(
            [
                {
                    "排名": rank,
                    "股票": item.instrument.label,
                    "Factor Score": item.factor_score,
                    "类别覆盖": f"{item.category_coverage}/5",
                    **{
                        CATEGORY_LABELS[name]: value for name, value in item.category_scores.items()
                    },
                    **{FACTOR_LABELS[name]: value for name, value in item.raw_factors.items()},
                }
                for rank, item in enumerate(snapshot.scores, start=1)
            ],
            width="stretch",
            hide_index=True,
        )

with backtest_tab:
    backtest_columns = st.columns(3)
    with backtest_columns[0]:
        backtest_market = st.selectbox(
            "回测市场",
            ("US", "HK", "A"),
            key="factor-backtest-market",
        )
    with backtest_columns[1]:
        backtest_start = st.date_input(
            "回测起始日期",
            value=today - timedelta(days=365 * 5),
            max_value=today,
            key="factor-backtest-start",
        )
    with backtest_columns[2]:
        backtest_end = st.date_input(
            "回测截止日期",
            value=today,
            max_value=today,
            key="factor-backtest-end",
        )
    backtest_clicked = st.button(
        "旧版因子回测已停用",
        disabled=True,
        key="factor-backtest-run",
    )
    st.warning(
        "该页面原有的收盘到收盘收益诊断不具备下一开盘成交、成本、交易日历和"
        "可成交性约束，已停止发布绩效指标。因子策略请使用 Backtest Laboratory。"
    )
    backtest: FactorBacktestResult | None = None
    if backtest_clicked:
        try:
            with st.spinner("正在逐历史截面重建因子并计算持有期收益……"):
                with factor_research_service() as service:
                    backtest = service.run_backtest(
                        market=backtest_market,
                        start_date=backtest_start,
                        end_date=backtest_end,
                    )
            st.success(f"回测已保存，运行编号 #{backtest.run_id}")
        except ValueError as error:
            st.error(f"无法运行回测：{error}")
    else:
        with factor_research_service() as service:
            backtest = service.latest_backtest()

    if backtest is None:
        empty_state("尚无因子回测结果。")
    else:
        summary = backtest.summary
        metrics = st.columns(5)
        metrics[0].metric("累计收益", f"{summary.cumulative_return:.1%}")
        metrics[1].metric(
            "等权基准",
            f"{summary.benchmark_cumulative_return:.1%}",
        )
        metrics[2].metric("年化收益", f"{summary.annualized_return:.1%}")
        metrics[3].metric("最大回撤", f"{summary.max_drawdown:.1%}")
        metrics[4].metric(
            "Sharpe",
            f"{summary.sharpe_ratio:.2f}" if summary.sharpe_ratio is not None else "—",
        )
        st.plotly_chart(
            factor_backtest_chart(backtest.periods, title="因子组合与等权股票池"),
            width="stretch",
            key=f"factor-backtest-chart-{backtest.run_id}",
        )
        st.dataframe(
            [
                {
                    "再平衡日": item.rebalance_date,
                    "持有期结束": item.period_end_date,
                    "入选股票": ", ".join(asset.symbol for asset in item.selected),
                    "组合收益": item.portfolio_return,
                    "等权基准": item.benchmark_return,
                    "超额收益": item.excess_return,
                }
                for item in backtest.periods
            ],
            width="stretch",
            hide_index=True,
        )

with st.expander("因子口径与回测限制"):
    st.markdown(
        """
- 基本面严格使用 `available_at <= 评分日` 的记录；收入和 EPS 使用同报告类型的同比增长。
- FCF Yield 仅使用年度或 TTM FCF，并以评分日价格乘当时已知股数估算市值。
- 动量默认使用 12-1 口径；波动率为近期日收益标准差年化，低波方向得分更高。
- 原始因子按横截面方向百分位转为 0–100 分；缺失值不做中性填充。
- 综合分对价值、成长、质量、动量、低波五类等权，而不是让字段较多的类别自动占更高权重。
- 旧版收盘到收盘因子收益诊断已停用；正式绩效必须通过 Backtest Laboratory 的下一开盘
  成交、成本、交易日历、可成交性和流动性门禁。
- 当前股票主数据没有历史指数成分，因此回测仍可能存在股票池与退市数据完整性偏差。
"""
    )
