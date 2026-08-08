from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.dashboard.charts import (
    exposure_chart,
    portfolio_risk_line_chart,
    stress_contribution_chart,
)
from personal_alpha_terminal.dashboard.components import empty_state, page_header
from personal_alpha_terminal.dashboard.runtime import (
    portfolio_risk_database_ready,
    portfolio_risk_service,
)
from personal_alpha_terminal.dashboard.schemas import Exposure
from personal_alpha_terminal.portfolio.schemas import StressScenario

page_header(
    "组合风险",
    "统一计价的历史风险、Beta、行业/币种暴露与可解释静态压力测试。",
)

if not portfolio_risk_database_ready():
    st.error("组合风险数据表尚未初始化，请先运行数据库初始化命令。")
    st.stop()

with portfolio_risk_service() as service:
    portfolios = service.list_portfolios()
    benchmarks = service.list_benchmarks()

if not portfolios:
    empty_state("还没有可分析的投资组合。")
    st.stop()
if not benchmarks:
    empty_state("还没有可用的指数或 ETF 基准。")
    st.stop()

portfolio_col, benchmark_col, range_col = st.columns([2, 2, 1])
with portfolio_col:
    selected_portfolio = st.selectbox(
        "投资组合",
        portfolios,
        format_func=lambda item: item.label,
        key="portfolio-risk-portfolio",
    )
with benchmark_col:
    selected_benchmark = st.selectbox(
        "Beta / 压力基准",
        benchmarks,
        format_func=lambda item: item.label,
        key="portfolio-risk-benchmark",
    )
with range_col:
    history_years = st.selectbox(
        "历史窗口",
        (1, 3, 5),
        format_func=lambda value: f"{value} 年",
        key="portfolio-risk-history",
    )

st.subheader("压力情景")
scenario_col, market_col, currency_col, fx_col = st.columns([2, 1, 1, 1])
with scenario_col:
    scenario_name = st.text_input(
        "情景名称",
        value="NASDAQ -30% / USD +20%",
        key="portfolio-risk-scenario-name",
    )
with market_col:
    benchmark_shock_percent = st.number_input(
        "基准冲击 %",
        min_value=-100.0,
        max_value=1000.0,
        value=-30.0,
        step=1.0,
        key="portfolio-risk-market-shock",
    )
with currency_col:
    shock_currency = st.text_input(
        "冲击币种",
        value="USD",
        max_chars=3,
        key="portfolio-risk-currency",
    ).upper()
with fx_col:
    currency_shock_percent = st.number_input(
        "币种升值 %",
        min_value=-100.0,
        max_value=1000.0,
        value=20.0,
        step=1.0,
        key="portfolio-risk-fx-shock",
    )

end_date = date.today()
start_date = end_date - timedelta(days=365 * history_years)
analysis = None
run_clicked = st.button(
    "运行风险分析",
    type="primary",
    key="portfolio-risk-run",
)
if run_clicked:
    scenario = StressScenario(
        name=scenario_name.strip(),
        benchmark_shock=benchmark_shock_percent / 100,
        currency_shocks=({shock_currency: currency_shock_percent / 100} if shock_currency else {}),
    )
    try:
        with st.spinner("正在计算并保存风险快照…"):
            with portfolio_risk_service() as service:
                analysis = service.run(
                    portfolio_id=selected_portfolio.id,
                    benchmark_stock_id=selected_benchmark.id,
                    start_date=start_date,
                    end_date=end_date,
                    scenarios=(scenario,),
                )
        st.success(f"风险分析已保存，运行编号：{analysis.risk.run_id}")
    except ValueError as error:
        st.error(str(error))
else:
    with portfolio_risk_service() as service:
        analysis = service.latest(selected_portfolio.id)

if analysis is None:
    empty_state(
        "尚无已完成的风险快照。",
        hint="准备足够的历史价格与必要的 FX 数据后，点击“运行风险分析”。",
    )
    st.stop()

risk = analysis.risk
st.caption(
    f"估值日 {risk.as_of_date.isoformat()} · 基准 {risk.benchmark.label} · "
    f"组合基准币种 {risk.base_currency}"
)
primary = st.columns(5)
primary[0].metric("组合价值", f"{risk.base_currency} {risk.total_value:,.2f}")
primary[1].metric("年化收益率", f"{risk.annualized_return:.2%}")
primary[2].metric("年化波动率", f"{risk.annualized_volatility:.2%}")
primary[3].metric("最大回撤", f"{risk.max_drawdown:.2%}")
primary[4].metric(
    "Sharpe Ratio",
    f"{risk.sharpe_ratio:.2f}" if risk.sharpe_ratio is not None else "—",
)
secondary = st.columns(2)
secondary[0].metric(
    "Beta",
    f"{risk.beta:.2f}" if risk.beta is not None else "—",
)
secondary[1].metric("共同样本", f"{risk.observation_count} 个交易日")

st.plotly_chart(
    portfolio_risk_line_chart(
        risk.equity_curve,
        title="组合历史净值（起点 100）",
        y_title="净值",
    ),
    width="stretch",
    key="portfolio-risk-equity",
)
st.plotly_chart(
    portfolio_risk_line_chart(
        risk.drawdown_curve,
        title="历史回撤",
        y_title="回撤",
        percent=True,
    ),
    width="stretch",
    key="portfolio-risk-drawdown",
)

exposure_columns = st.columns(2)
with exposure_columns[0]:
    industry_exposure = tuple(
        Exposure(name=name, weight=weight)
        for name, weight in sorted(
            risk.industry_exposure.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    st.plotly_chart(
        exposure_chart(industry_exposure, "行业暴露"),
        width="stretch",
        key="portfolio-risk-industry",
    )
with exposure_columns[1]:
    currency_exposure = tuple(
        Exposure(name=name, weight=weight)
        for name, weight in sorted(
            risk.currency_exposure.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    st.plotly_chart(
        exposure_chart(currency_exposure, "币种暴露"),
        width="stretch",
        key="portfolio-risk-currency-exposure",
    )

st.subheader("持仓风险分解")
st.dataframe(
    [
        {
            "代码": item.instrument.symbol,
            "类型": item.instrument.asset_type,
            "币种": item.currency,
            "行业": item.industry,
            "市值": item.market_value,
            "权重": item.weight,
            "Beta": item.beta,
        }
        for item in risk.positions
    ],
    column_config={
        "市值": st.column_config.NumberColumn(format="%.2f"),
        "权重": st.column_config.NumberColumn(format="percent"),
        "Beta": st.column_config.NumberColumn(format="%.2f"),
    },
    hide_index=True,
    width="stretch",
)

for index, result in enumerate(analysis.stress_tests):
    st.subheader(f"压力测试：{result.scenario.name}")
    stress_metrics = st.columns(4)
    stress_metrics[0].metric(
        "压力后价值",
        f"{risk.base_currency} {result.stressed_value:,.2f}",
    )
    stress_metrics[1].metric("组合变化", f"{result.pnl_percent:.2%}")
    stress_metrics[2].metric(
        "损益",
        f"{risk.base_currency} {result.pnl_amount:,.2f}",
    )
    stress_metrics[3].metric("Beta 未覆盖权重", f"{result.uncovered_weight:.2%}")
    st.plotly_chart(
        stress_contribution_chart(result),
        width="stretch",
        key=f"portfolio-risk-stress-{index}",
    )

st.caption(
    "方法：使用当前持仓权重回放历史收益；Beta=Cov(资产,基准)/Var(基准)。"
    "压力测试按持仓 Beta 映射基准冲击，再与非基准币种的汇率冲击复合。"
    "该结果不模拟流动性、波动率跃升、相关性突变、融资或交易成本，不构成投资建议。"
)
