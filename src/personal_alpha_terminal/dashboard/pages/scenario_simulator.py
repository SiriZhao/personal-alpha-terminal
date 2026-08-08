import streamlit as st

from personal_alpha_terminal.dashboard.charts import (
    asset_sensitivity_heatmap,
    scenario_comparison_chart,
    scenario_risk_map_chart,
)
from personal_alpha_terminal.dashboard.components import empty_state, page_header
from personal_alpha_terminal.dashboard.runtime import (
    portfolio_risk_service,
    scenario_database_ready,
    scenario_service,
)
from personal_alpha_terminal.scenario_simulator.catalog import (
    RISK_FACTORS,
    built_in_scenarios,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorShock,
    ScenarioDefinition,
    ScenarioResult,
)

page_header(
    "Scenario Simulator",
    "把明确的市场假设映射到当前持仓；结果是条件敏感性估计，不是价格预测。",
)

if not scenario_database_ready():
    st.error("情景模拟数据表尚未初始化，请先运行数据库迁移。")
    st.stop()

with portfolio_risk_service() as risk_service:
    portfolios = risk_service.list_portfolios()

if not portfolios:
    empty_state("还没有可分析的投资组合。")
    st.stop()

selected_portfolio = st.selectbox(
    "投资组合",
    portfolios,
    format_func=lambda item: item.label,
    key="scenario-portfolio",
)

try:
    with scenario_service() as service:
        portfolio, mappings = service.mapping_snapshot(selected_portfolio.id)
except ValueError as error:
    st.error(str(error))
    st.info("请先在“基础风险”页面完成一次组合估值，场景模拟只使用已验证的持仓快照。")
    st.stop()

st.caption(
    f"持仓快照 {portfolio.as_of_date.isoformat()} · "
    f"{portfolio.base_currency} {portfolio.total_value:,.2f} · "
    "现金在情景中保持不变"
)

with st.expander("资产—风险因子映射", expanded=False):
    if mappings:
        symbol_by_id = {item.instrument.id: item.instrument.symbol for item in portfolio.positions}
        st.dataframe(
            [
                {
                    "资产": symbol_by_id.get(item.asset_id, str(item.asset_id)),
                    "风险因子": item.factor_code,
                    "敏感度": item.sensitivity,
                    "下界": item.sensitivity_low,
                    "上界": item.sensitivity_high,
                    "置信度": item.confidence_score,
                    "方法": item.method,
                    "数据来源": item.source,
                    "截至日期": item.as_of_date,
                }
                for item in mappings
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.warning("当前持仓没有可用映射。未映射资产按不变处理，会低估风险；请录入有依据的敏感度。")

    st.markdown("#### 登记一条版本化映射")
    st.caption(
        "敏感度含义：资产收益变化 = 敏感度 × 标准化因子冲击。"
        "例如利率因子按每 100bp 计，-0.08 表示利率上升 100bp 时资产约下降 8%。"
    )
    mapping_columns = st.columns(2)
    with mapping_columns[0]:
        mapped_position = st.selectbox(
            "资产",
            portfolio.positions,
            format_func=lambda item: f"{item.instrument.symbol} · {item.instrument.name}",
            key="scenario-mapping-asset",
        )
        mapped_factor = st.selectbox(
            "风险因子",
            RISK_FACTORS,
            format_func=lambda item: f"{item.name} · {item.shock_unit}",
            key="scenario-mapping-factor",
        )
        sensitivity = st.number_input(
            "中心敏感度",
            value=0.0,
            step=0.05,
            format="%.4f",
            key="scenario-mapping-sensitivity",
        )
    with mapping_columns[1]:
        sensitivity_low = st.number_input(
            "敏感度下界",
            value=-0.10,
            step=0.05,
            format="%.4f",
            key="scenario-mapping-low",
        )
        sensitivity_high = st.number_input(
            "敏感度上界",
            value=0.10,
            step=0.05,
            format="%.4f",
            key="scenario-mapping-high",
        )
        mapping_confidence = st.slider(
            "映射证据质量",
            min_value=0,
            max_value=100,
            value=60,
            key="scenario-mapping-confidence",
        )
    mapping_source = st.text_input(
        "数据来源 / 校准说明",
        placeholder="例如：verified_regression:QQQM_vs_NDX:2024-01-01_to_2026-06-30",
        key="scenario-mapping-source",
    )
    if st.button("保存映射", key="scenario-save-mapping"):
        try:
            mapping = AssetFactorExposure(
                asset_id=mapped_position.instrument.id,
                factor_code=mapped_factor.code,
                sensitivity=float(sensitivity),
                sensitivity_low=float(sensitivity_low),
                sensitivity_high=float(sensitivity_high),
                as_of_date=portfolio.as_of_date,
                method="user_documented_mapping",
                source=mapping_source.strip(),
                confidence_score=mapping_confidence,
            )
            with scenario_service() as service:
                service.register_exposures((mapping,))
            st.success("映射已按持仓日期保存。")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

st.divider()
mode = st.radio(
    "情景来源",
    ("内置压力模板", "自定义假设"),
    horizontal=True,
    key="scenario-mode",
)

builtins = built_in_scenarios()
scenario: ScenarioDefinition | None = None
if mode == "内置压力模板":
    scenario = st.selectbox(
        "选择压力模板",
        builtins,
        format_func=lambda item: item.name,
        key="scenario-builtin",
    )
    st.warning(
        "2008、2020、2022 模板是近似种子，不是精确历史重放；"
        "AI 估值回撤和中国复苏属于假设情景。正式决策前应使用已核验序列重新校准。"
    )
    st.caption(scenario.description)
else:
    name = st.text_input(
        "情景名称",
        value="自定义市场假设",
        key="scenario-custom-name",
    )
    description = st.text_area(
        "情景逻辑",
        value="记录冲击为何可能同时发生，以及该组合暴露为何相关。",
        key="scenario-custom-description",
    )
    st.markdown("#### 风险因子冲击")
    shocks: list[FactorShock] = []
    factor_columns = st.columns(3)
    for index, factor in enumerate(RISK_FACTORS):
        with factor_columns[index % 3]:
            if factor.shock_unit == "basis_points":
                value = st.number_input(
                    f"{factor.name}（bp）",
                    min_value=-1000.0,
                    max_value=1000.0,
                    value=0.0,
                    step=25.0,
                    key=f"scenario-factor-{factor.code}",
                )
                magnitude = float(value)
            elif factor.shock_unit == "standard_score":
                value = st.number_input(
                    f"{factor.name}（标准分）",
                    min_value=-1.0,
                    max_value=1.0,
                    value=0.0,
                    step=0.1,
                    key=f"scenario-factor-{factor.code}",
                )
                magnitude = float(value)
            else:
                value = st.number_input(
                    f"{factor.name}（%）",
                    min_value=-100.0,
                    max_value=500.0,
                    value=0.0,
                    step=1.0,
                    key=f"scenario-factor-{factor.code}",
                )
                magnitude = float(value) / 100
            if magnitude != 0:
                shocks.append(
                    FactorShock(
                        factor_code=factor.code,
                        magnitude=magnitude,
                        unit=factor.shock_unit,
                        rationale="user-entered conditional assumption",
                    )
                )
    fx_columns = st.columns(2)
    with fx_columns[0]:
        fx_currency = st.text_input(
            "持仓币种升值（可选）",
            placeholder="USD",
            max_chars=3,
            key="scenario-fx-currency",
        ).upper()
    with fx_columns[1]:
        fx_percent = st.number_input(
            "相对组合基准币种变化（%）",
            min_value=-100.0,
            max_value=1000.0,
            value=0.0,
            step=1.0,
            key="scenario-fx-percent",
        )
    custom_source = st.text_input(
        "假设来源",
        value="user_assumption:documented_in_dashboard",
        key="scenario-custom-source",
    )
    try:
        scenario = ScenarioDefinition(
            name=name.strip(),
            scenario_type="custom",
            description=description.strip(),
            factor_shocks=tuple(shocks),
            currency_shocks=(
                {fx_currency: float(fx_percent) / 100} if fx_currency and fx_percent != 0 else {}
            ),
            evidence_level="user_assumption",
            data_sources=(custom_source.strip(),),
        )
    except ValueError:
        scenario = None

run_result: ScenarioResult | None = st.session_state.get("scenario-result")
if st.button(
    "运行情景模拟",
    type="primary",
    disabled=scenario is None,
    key="scenario-run",
):
    if scenario is not None:
        try:
            with st.spinner("正在计算、保存审计快照并生成报告…"):
                with scenario_service() as service:
                    run_result, _ = service.run_latest(
                        portfolio_id=selected_portfolio.id,
                        scenario=scenario,
                    )
            st.session_state["scenario-result"] = run_result
        except ValueError as error:
            st.error(str(error))

if run_result is not None and run_result.portfolio_id == selected_portfolio.id:
    result = run_result
    st.subheader(f"Scenario Report · {result.scenario.name}")
    metrics = st.columns(5)
    metrics[0].metric(
        "组合变化",
        f"{result.pnl_percent:.2%}",
        f"{result.pnl_amount:,.2f} {result.base_currency}",
    )
    metrics[1].metric("压力后价值", f"{result.stressed_value:,.2f}")
    metrics[2].metric("风险等级", result.risk_level)
    metrics[3].metric("映射覆盖率", f"{result.mapped_weight:.1%}")
    metrics[4].metric("证据质量", f"{result.confidence_score}/100")
    st.caption(
        f"敏感性区间 {result.pnl_percent_low:.2%} 至 "
        f"{result.pnl_percent_high:.2%} · "
        f"运行编号 {result.run_id} · 数据指纹 {result.data_fingerprint[:12]}…"
    )
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)
    st.plotly_chart(
        scenario_risk_map_chart(result),
        width="stretch",
        key="scenario-risk-map",
    )
    if any(item.factor_contributions for item in result.impacts):
        st.plotly_chart(
            asset_sensitivity_heatmap(result),
            width="stretch",
            key="scenario-sensitivity-map",
        )
    st.dataframe(
        [
            {
                "资产": item.instrument.symbol,
                "权重": item.weight,
                "因子影响": item.factor_return,
                "汇率影响": item.currency_return,
                "总影响": item.combined_return,
                "组合贡献": item.contribution,
                "压力后价值": item.stressed_value,
                "已映射": item.mapped,
            }
            for item in result.impacts
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "权重": st.column_config.NumberColumn(format="percent"),
            "因子影响": st.column_config.NumberColumn(format="percent"),
            "汇率影响": st.column_config.NumberColumn(format="percent"),
            "总影响": st.column_config.NumberColumn(format="percent"),
            "组合贡献": st.column_config.NumberColumn(format="percent"),
            "压力后价值": st.column_config.NumberColumn(format="%.2f"),
        },
    )

st.divider()
st.subheader("内置情景比较")
selected_names = st.multiselect(
    "选择 1–5 个模板",
    [item.name for item in builtins],
    default=[item.name for item in builtins[:4]],
    max_selections=5,
    key="scenario-compare-selection",
)
if st.button(
    "运行情景比较",
    disabled=not selected_names,
    key="scenario-compare-run",
):
    chosen = tuple(item for item in builtins if item.name in selected_names)
    try:
        with st.spinner("正在运行可复现的多情景比较…"):
            with scenario_service() as service:
                comparison = service.compare_latest(
                    portfolio_id=selected_portfolio.id,
                    scenarios=chosen,
                )
        st.session_state["scenario-comparison"] = comparison
    except ValueError as error:
        st.error(str(error))

stored_comparison = st.session_state.get("scenario-comparison")
if stored_comparison is not None and stored_comparison.portfolio_id == selected_portfolio.id:
    st.plotly_chart(
        scenario_comparison_chart(stored_comparison),
        width="stretch",
        key="scenario-comparison-chart",
    )

st.caption(
    "计算方法：资产因子收益为显式敏感度与标准化冲击的线性和；"
    "非基准币种变化在其后按复利方式换算。区间仅反映敏感度上下界，"
    "不代表概率置信区间。大冲击、流动性缺口、相关性突变和衍生品非线性可能使结果失真。"
)
