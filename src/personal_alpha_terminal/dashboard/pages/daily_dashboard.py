from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date

import streamlit as st
from sqlalchemy import func, select

from personal_alpha_terminal.core.product import load_preferences, save_preferences
from personal_alpha_terminal.dashboard.components import (
    allocation_bar,
    empty_state,
    format_percent,
    kpi_card,
    page_header,
    section_header,
    status_pill,
)
from personal_alpha_terminal.dashboard.home import HomeDigest
from personal_alpha_terminal.dashboard.runtime import (
    database_ready,
    decision_database_ready,
    decision_service,
    home_dashboard_repository,
    market_regime_database_ready,
    market_regime_service,
)
from personal_alpha_terminal.data.database import get_session_factory
from personal_alpha_terminal.models import Portfolio, PortfolioAllocationTarget, Stock


def _tone(status: str) -> str:
    return {
        "APPROVED": "positive",
        "RESEARCH_ONLY": "warning",
        "DEGRADED": "warning",
        "BLOCKED": "negative",
    }.get(status.upper(), "neutral")


def _target_allocations(portfolio_name: str) -> tuple[date | None, tuple[tuple[str, float], ...]]:
    with get_session_factory()() as session:
        portfolio_id = session.scalar(
            select(Portfolio.id).where(Portfolio.name == portfolio_name)
        )
        if portfolio_id is None:
            return None, ()
        effective_date = session.scalar(
            select(func.max(PortfolioAllocationTarget.effective_date)).where(
                PortfolioAllocationTarget.portfolio_id == portfolio_id
            )
        )
        if effective_date is None:
            return None, ()
        targets = tuple(
            session.scalars(
                select(PortfolioAllocationTarget).where(
                    PortfolioAllocationTarget.portfolio_id == portfolio_id,
                    PortfolioAllocationTarget.effective_date == effective_date,
                )
            )
        )
        stock_ids = {item.stock_id for item in targets if item.stock_id is not None}
        symbols = {
            item.id: item.symbol
            for item in session.scalars(select(Stock).where(Stock.id.in_(stock_ids)))
        }
        rows = tuple(
            (
                symbols.get(item.stock_id, "Unknown")
                if item.stock_id is not None
                else f"Cash {item.cash_currency}",
                float(item.target_weight),
            )
            for item in targets
        )
        return effective_date, rows


page_header(
    "今日投资驾驶舱 · Quant Dashboard",
    "数据状态、组合风险与确定性量化决策汇总。系统仅分析，不自动交易。",
)

preferences = load_preferences()
if not preferences.welcome_card_dismissed:
    with st.container(border=True):
        st.subheader("欢迎使用 Personal Alpha Terminal")
        st.write(
            "当前定位：Personal Quant Investment OS。数据质量决定分析能力；"
            "未通过认证的数据不会生成组合决策。"
        )
        welcome_actions = st.columns(3)
        if welcome_actions[0].button("开始配置", type="primary", width="stretch"):
            st.switch_page("pages/settings.py")
        if welcome_actions[1].button("查看数据状态", width="stretch"):
            st.switch_page("pages/data_sources.py")
        if welcome_actions[2].button("关闭", width="stretch"):
            save_preferences(replace(preferences, welcome_card_dismissed=True))
            st.rerun()

if database_ready():
    try:
        with home_dashboard_repository() as repository:
            digest = repository.load()
    except Exception:
        digest = HomeDigest.unavailable("dashboard read model is unavailable")
else:
    digest = HomeDigest.unavailable("database is not initialized")

updated = (
    digest.refreshed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if digest.refreshed_at
    else "Data unavailable"
)
status_columns = st.columns(4)
with status_columns[0]:
    st.markdown(
        status_pill(f"Data Gate · {digest.data_gate_status}", tone=_tone(digest.data_gate_status)),
        unsafe_allow_html=True,
    )
with status_columns[1]:
    st.markdown(
        status_pill(f"Quality · {digest.quality_status}", tone=_tone(digest.quality_status)),
        unsafe_allow_html=True,
    )
with status_columns[2]:
    st.markdown(
        status_pill(f"Pipeline · {digest.pipeline_status}", tone=_tone(digest.pipeline_status)),
        unsafe_allow_html=True,
    )
with status_columns[3]:
    st.caption(f"最近更新：{updated}")

if digest.data_gate_status != "APPROVED":
    st.warning(
        "Research Only · No Decision Generated\n\n"
        + ("；".join(digest.data_gate_blockers[:3]) or "尚未导入并认证可用于组合决策的市场数据。")
    )

section_header("01", "市场状态 Market Regime", "未校准模型只显示评分，不称为概率。")
regime = None
if digest.data_gate_status == "APPROVED" and market_regime_database_ready():
    try:
        with market_regime_service() as regime_read_service:
            regime = regime_read_service.latest()
    except Exception:
        regime = None
if regime is None or not regime.observations:
    empty_state(
        "Waiting for Data",
        hint="需要通过数据门禁且具备可追溯的 VIX、利率、美元、指数和市场宽度数据。",
    )
else:
    current = regime.current
    labels = {"risk_on": "Bullish / Risk-On", "neutral": "Neutral", "risk_off": "Risk-Off"}
    regime_columns = st.columns(5)
    regime_columns[0].metric("市场状态", labels.get(current.regime, current.regime))
    regime_columns[1].metric(
        "风险评分", f"{max(0.0, min(100.0, 50.0 - current.composite_score * 25)):.0f} / 100"
    )
    for index, key in enumerate(("vix_level", "market_breadth", "index_trend"), start=2):
        regime_columns[index].metric(
            key.replace("_", " ").title(), f"{current.feature_zscores.get(key, 0.0):+.2f} z"
        )
    st.caption(
        f"来源：regime run #{regime.run_id} · 截止 {current.as_of_date} · "
        f"样本 {current.breadth_constituent_count} · calibration={regime.calibration.status}"
    )

section_header("02", "我的投资组合 Portfolio Snapshot", "真实持仓记录与最近风险快照。")
portfolio = digest.portfolio
if portfolio is None:
    empty_state("尚无组合数据", hint="前往“我的组合”手动录入或导入 CSV。")
else:
    portfolio_columns = st.columns(4)
    with portfolio_columns[0]:
        kpi_card(
            "总资产",
            f"{portfolio.base_currency} {portfolio.total_value:,.2f}",
            f"截至 {portfolio.as_of_date}",
        )
    with portfolio_columns[1]:
        kpi_card(
            "年化收益",
            format_percent(portfolio.annualized_return),
            "基于已记录组合历史",
        )
    with portfolio_columns[2]:
        kpi_card(
            "最大回撤",
            format_percent(portfolio.max_drawdown),
            "历史结果不保证未来",
        )
    with portfolio_columns[3]:
        kpi_card(
            "Beta",
            f"{portfolio.beta:.2f}" if portfolio.beta is not None else "Data unavailable",
            "相对已配置基准",
        )
    for symbol, weight in portfolio.top_positions[:5]:
        allocation_bar(symbol, weight)
    target_date, targets = _target_allocations(portfolio.name)
    if targets:
        st.caption(f"目标配置 · effective {target_date}")
        for symbol, weight in targets:
            allocation_bar(f"Target · {symbol}", weight)
    else:
        st.info("目标配置 Data unavailable · 尚无经风险约束保存的配置目标。")
    st.caption(f"持仓日期：{portfolio.as_of_date} · 风险结果仅对已记录持仓有效。")

section_header("03", "今日行动中心 Action Center", "模型建议必须经过人工接受、拒绝或观望。")
latest = None
if decision_database_ready():
    try:
        with decision_service() as decision_read_service:
            latest = decision_read_service.latest_run()
    except Exception:
        latest = None
if latest is None:
    empty_state(
        "No Decision Generated",
        hint="系统不会在数据不足、门禁未通过或没有合格信号时生成行动建议。",
    )
elif latest.status != "generated" or latest.gate_status != "APPROVED":
    empty_state(
        "Research Only · No Decision Generated",
        hint="；".join(latest.blockers[:4]) or f"Decision status: {latest.status}",
    )
else:
    st.caption(
        f"决策时间：{latest.as_of_time} · 数据版本：{latest.data_version} · "
        f"模型版本：{latest.model_version} · 来源 {len(latest.source_ids)}"
    )
    for recommendation in latest.recommendations[:5]:
        change = float(recommendation.target_weight - recommendation.current_weight)
        with st.container(border=True):
            columns = st.columns((1.1, 0.8, 1, 1, 1.2))
            columns[0].subheader(recommendation.stock.symbol)
            columns[1].metric("操作", recommendation.action)
            columns[2].metric("当前仓位", format_percent(float(recommendation.current_weight)))
            columns[3].metric("目标仓位", format_percent(float(recommendation.target_weight)))
            columns[4].metric("变化", format_percent(change))
            st.write("；".join(recommendation.rationale[:3]))
            st.caption(
                f"量化评分 {float(recommendation.quant_score):.1f}/100 · "
                f"证据可信度 {float(recommendation.confidence_score):.1f}/100（非概率） · "
                f"样本 {recommendation.sample_size} · 状态 {recommendation.review_status}"
            )
    if st.button("打开完整行动中心", icon=":material/task_alt:"):
        st.switch_page("pages/action_center.py")

section_header("04", "研究与系统状态", "研究模块保留为证据后台，不直接覆盖组合决策。")
research_columns = st.columns(3)
research_columns[0].metric("事件证据", len(digest.events))
research_columns[1].metric("条件证据", len(digest.probabilities))
research_columns[2].metric("关系异常", len(digest.relationships))
st.caption("AI 仅用于解释已存在的量化证据；最终排名、目标权重和风险约束由确定性代码生成。")

section_header("05", "AI 研究助手", "仅解释量化结果，不预测价格、不创建或覆盖行动建议。")
if preferences.ai_provider == "disabled":
    st.info("AI 未启用 · 系统的量化计算、风险门禁和人工决策流程仍可正常使用。")
elif digest.data_gate_status != "APPROVED":
    st.warning("AI 已配置，但没有通过数据门禁的量化证据，因此不会生成解释。")
else:
    st.success(
        f"AI Provider · {preferences.ai_provider} · 仅接收结构化量化结果和可追溯来源。"
    )
st.caption("本页面不提供股票聊天或 AI 选股入口。")
