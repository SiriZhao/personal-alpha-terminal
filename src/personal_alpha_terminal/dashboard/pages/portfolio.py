from datetime import date
from decimal import Decimal

import streamlit as st
from sqlalchemy import select

from personal_alpha_terminal.dashboard.charts import allocation_chart
from personal_alpha_terminal.dashboard.components import empty_state, format_price, page_header
from personal_alpha_terminal.dashboard.runtime import (
    dashboard_service,
    database_ready,
    position_import_service,
)
from personal_alpha_terminal.data.database import get_session_factory, session_scope
from personal_alpha_terminal.models import Portfolio
from personal_alpha_terminal.portfolio import parse_position_csv

page_header(
    "我的组合 Portfolio",
    "本地真实持仓记录、手工快照与 CSV 导入。系统仅分析，不连接券商。",
)

if not database_ready():
    empty_state("数据库尚未初始化", hint="前往系统诊断完成数据库初始化后再录入持仓。")
    st.stop()

with dashboard_service() as service:
    options = service.list_portfolios()

with st.expander("新建组合", expanded=not bool(options)):
    with st.form("create-portfolio"):
        name = st.text_input("组合名称")
        base_currency = st.selectbox("基础币种", ("USD", "CNY", "HKD"))
        cash_balance = st.number_input("现金余额", min_value=0.0, step=100.0)
        create_clicked = st.form_submit_button("创建组合", type="primary")
    if create_clicked:
        normalized_name = name.strip()
        if not normalized_name:
            st.error("组合名称不能为空。")
        else:
            try:
                with session_scope(get_session_factory()) as session:
                    if session.scalar(select(Portfolio).where(Portfolio.name == normalized_name)):
                        raise ValueError("组合名称已存在")
                    session.add(
                        Portfolio(
                            name=normalized_name,
                            base_currency=base_currency,
                            cash_balance=Decimal(str(cash_balance)),
                        )
                    )
                st.success("组合已创建。")
                st.rerun()
            except ValueError as error:
                st.error(str(error))

if not options:
    empty_state("尚无投资组合", hint="先创建一个本地组合，再录入或导入持仓。")
    st.stop()

selected = st.selectbox(
    "投资组合",
    options,
    format_func=lambda option: option.label,
    key="portfolio-selector",
)

snapshot_tab, manual_tab, import_tab = st.tabs(("组合快照", "手动录入", "CSV / 嘉信导入"))

with snapshot_tab:
    with dashboard_service() as service:
        snapshot = service.portfolio_snapshot(selected.id)
    if snapshot is None:
        st.error("所选组合不存在。")
    else:
        metrics = st.columns(4)
        metrics[0].metric(
            "总资产",
            format_price(snapshot.total_value, snapshot.portfolio.base_currency)
            if snapshot.valuation_complete
            else "Data unavailable",
        )
        metrics[1].metric(
            "证券市值",
            format_price(snapshot.invested_value, snapshot.portfolio.base_currency)
            if snapshot.valuation_complete
            else "Data unavailable",
        )
        metrics[2].metric(
            "现金",
            format_price(snapshot.cash_balance, snapshot.portfolio.base_currency),
        )
        metrics[3].metric(
            "持仓日期", snapshot.as_of_date.isoformat() if snapshot.as_of_date else "—"
        )
        if not snapshot.valuation_complete:
            st.warning("存在缺失行情或跨币种估值；系统不会填充价格或生成虚假总资产。")
        if not snapshot.positions:
            empty_state("当前组合还没有持仓快照。")
        else:
            st.dataframe(
                [
                    {
                        "市场": item.market,
                        "代码": item.symbol,
                        "名称": item.name,
                        "币种": item.currency,
                        "数量": float(item.quantity),
                        "平均成本": float(item.average_cost)
                        if item.average_cost is not None
                        else None,
                        "最新价": float(item.last_price) if item.last_price is not None else None,
                        "市值": float(item.market_value) if item.market_value is not None else None,
                        "组合权重": item.weight,
                        "行情日期": item.price_date,
                    }
                    for item in snapshot.positions
                ],
                width="stretch",
                hide_index=True,
            )
            if snapshot.valuation_complete:
                priced = [item for item in snapshot.positions if item.market_value is not None]
                labels = [item.symbol for item in priced]
                values = [float(item.market_value or 0) for item in priced]
                if snapshot.cash_balance > 0:
                    labels.append("现金")
                    values.append(float(snapshot.cash_balance))
                st.plotly_chart(allocation_chart(labels, values), width="stretch")

with manual_tab:
    st.info("手动录入创建持仓快照，不会伪造买卖流水或已实现收益。")
    with st.form("manual-position"):
        manual_date = st.date_input("快照日期", value=date.today())
        symbol = st.text_input("美股代码", placeholder="AAPL")
        quantity = st.number_input("数量", min_value=0.000001, value=1.0, step=1.0)
        average_cost = st.number_input("平均成本", min_value=0.01, value=1.0, step=0.01)
        manual_clicked = st.form_submit_button("保存持仓快照", type="primary")
    if manual_clicked:
        try:
            with position_import_service() as service:
                service.upsert_position(
                    portfolio_id=selected.id,
                    as_of_date=manual_date,
                    symbol=symbol,
                    quantity=Decimal(str(quantity)),
                    average_cost=Decimal(str(average_cost)),
                )
            st.success("持仓快照已保存；真实交易流水未改变。")
            st.rerun()
        except ValueError as error:
            st.error(f"无法保存：{error}")

with import_tab:
    st.write("支持通用 CSV，以及包含 Symbol、Quantity、Market Value、Cost Basis 的嘉信持仓快照。")
    uploaded = st.file_uploader("选择本地 CSV", type=("csv",), accept_multiple_files=False)
    import_date = st.date_input("导入快照日期", value=date.today(), key="csv-date")
    parsed = None
    if uploaded is not None:
        try:
            parsed = parse_position_csv(uploaded.getvalue())
            st.success(f"已识别 {parsed.format_name}，共 {len(parsed.rows)} 条持仓。")
            st.dataframe(
                [
                    {
                        "代码": item.symbol,
                        "数量": float(item.quantity),
                        "平均成本": float(item.average_cost) if item.average_cost else None,
                    }
                    for item in parsed.rows
                ],
                hide_index=True,
                width="stretch",
            )
            for warning in parsed.warnings:
                st.warning(warning)
        except ValueError as error:
            st.error(f"CSV 无法解析：{error}")
    if st.button("确认导入快照", type="primary", disabled=parsed is None):
        assert parsed is not None
        try:
            with position_import_service() as service:
                result = service.import_snapshot(
                    portfolio_id=selected.id,
                    as_of_date=import_date,
                    parsed=parsed,
                )
            st.success(f"已导入 {result.imported_count} 条持仓；未知代码未自动创建。")
            for warning in result.warnings:
                st.warning(warning)
            st.rerun()
        except ValueError as error:
            st.error(f"导入失败：{error}")
