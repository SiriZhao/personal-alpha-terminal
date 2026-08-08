import logging
from dataclasses import replace
from datetime import date

import streamlit as st

from personal_alpha_terminal.analysis.market_regime.schemas import MarketRegimeResult
from personal_alpha_terminal.core.product import (
    load_preferences,
    preferences_path,
    save_preferences,
)
from personal_alpha_terminal.dashboard.charts import (
    market_change_chart,
    regime_distribution_chart,
)
from personal_alpha_terminal.dashboard.components import (
    allocation_bar,
    empty_state,
    format_price,
    format_volume,
    kpi_card,
    section_header,
    signal_row,
    status_pill,
)
from personal_alpha_terminal.dashboard.home import HomeDigest, PortfolioDigest
from personal_alpha_terminal.dashboard.runtime import (
    dashboard_service,
    database_ready,
    home_dashboard_repository,
    market_regime_database_ready,
    market_regime_service,
)
from personal_alpha_terminal.dashboard.schemas import MarketIndexSnapshot
from personal_alpha_terminal.dashboard.startup import assess_startup
from personal_alpha_terminal.data.database import get_engine
from personal_alpha_terminal.validation.confidence import assess_regime_point

PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}
LOGGER = logging.getLogger(__name__)


@st.cache_data(ttl=45, show_spinner=False)
def _load_home_data(
    engine_token: int,
) -> tuple[tuple[MarketIndexSnapshot, ...], HomeDigest, MarketRegimeResult | None]:
    del engine_token
    with dashboard_service() as service:
        snapshots = service.market_overview()
    with home_dashboard_repository() as repository:
        digest = repository.load()
    regime = None
    if market_regime_database_ready():
        with market_regime_service() as service:
            regime = service.latest()
    return snapshots, digest, regime


def _risk_level(
    *,
    regime: MarketRegimeResult | None,
    portfolio: PortfolioDigest | None,
    data_lag_days: int,
) -> tuple[str, str, str]:
    score = 0
    reasons: list[str] = []
    if data_lag_days > 7:
        score += 2
        reasons.append("指数数据滞后")
    if regime is not None and regime.observations:
        if regime.current.regime == "risk_off":
            score += 2
            reasons.append("Risk-Off")
        elif regime.current.regime == "neutral":
            score += 1
            reasons.append("状态中性")
    if portfolio is not None:
        if portfolio.max_drawdown <= -0.20:
            score += 2
            reasons.append("回放回撤超过20%")
        elif portfolio.max_drawdown <= -0.10:
            score += 1
            reasons.append("回放回撤超过10%")
        if portfolio.annualized_volatility >= 0.30:
            score += 1
            reasons.append("波动率偏高")
    if score >= 3:
        return "High", "negative", " · ".join(reasons) or "多项风险阈值触发"
    if score >= 1:
        return "Elevated", "accent", " · ".join(reasons) or "存在需复核项目"
    return "Controlled", "positive", "未触发预设阈值；不代表无风险"


preferences = load_preferences()

if not (
    preferences.welcome_card_dismissed
    or st.session_state.get("pat_welcome_card_dismissed", False)
):
    with st.container(border=True):
        st.markdown("### 欢迎使用 Personal Alpha Terminal")
        st.caption("当前状态 · Research Preview")
        st.write(
            "当前用于个人量化研究；数据质量决定分析能力；"
            "未通过数据认证时不会生成真实交易建议。"
        )
        welcome_actions = st.columns(3)
        if welcome_actions[0].button(
            "开始配置",
            icon=":material/settings:",
            key="welcome-settings",
            width="stretch",
        ):
            st.switch_page("pages/settings.py")
        if welcome_actions[1].button(
            "查看数据状态",
            icon=":material/database:",
            key="welcome-data-status",
            width="stretch",
        ):
            st.switch_page("pages/data_sources.py")
        if welcome_actions[2].button("关闭", key="dismiss-welcome", width="stretch"):
            st.session_state["pat_welcome_card_dismissed"] = True
            try:
                save_preferences(replace(preferences, welcome_card_dismissed=True))
            except OSError:
                st.warning("欢迎卡状态暂未保存；这不会阻止使用系统。")
            st.rerun()

database_is_ready = database_ready()
if database_is_ready:
    try:
        with st.spinner("正在读取最新研究快照…"):
            snapshots, digest, regime = _load_home_data(id(get_engine()))
    except Exception as error:
        LOGGER.exception("dashboard_home_data_error")
        snapshots = ()
        digest = HomeDigest.unavailable(
            f"数据库读取失败：{type(error).__name__}"
        )
        regime = None
else:
    snapshots = ()
    digest = HomeDigest.unavailable("研究数据库尚未初始化")
    regime = None

startup = assess_startup(
    database_ready=database_is_ready,
    configuration_exists=preferences_path().is_file(),
    data_gate_status=digest.data_gate_status,
    gate_reasons=digest.data_gate_blockers,
)

freshest = max((item.date for item in snapshots), default=None)
oldest = min((item.date for item in snapshots), default=None)
data_lag_days = (date.today() - oldest).days if oldest is not None else 999
risk_label, risk_tone, risk_reason = _risk_level(
    regime=regime,
    portfolio=digest.portfolio,
    data_lag_days=data_lag_days,
)
refresh_text = (
    digest.refreshed_at.strftime("%m-%d %H:%M")
    if digest.refreshed_at is not None
    else "暂无分析快照"
)

top_status = st.columns((1.4, 1, 1, 0.7))
top_status[0].caption(f"今天 · {date.today():%Y-%m-%d} · 最后分析 {refresh_text}")
top_status[1].caption(
    f"Data Gate · {startup.data_gate_status} · 样本 {digest.quality_sample_count}"
)
top_status[2].caption(
    f"运行模式 · {preferences.run_mode.value.replace('_', ' ').title()}"
)
if top_status[3].button("刷新视图", width="stretch", help="重新读取本地数据库，不伪造行情"):
    st.cache_data.clear()
    st.rerun()

if startup.data_gate_status == "BLOCKED":
    gate_columns = st.columns((5, 1))
    gate_columns[0].error(
        "Data Gate: BLOCKED · " + "；".join(startup.reasons[:3])
    )
    if gate_columns[1].button(
        "查看详情",
        icon=":material/monitor_heart:",
        key="gate-diagnostics",
        width="stretch",
    ):
        st.switch_page("pages/diagnostics.py")
elif startup.data_gate_status in {"DEGRADED", "RESEARCH_ONLY"}:
    st.warning(f"Data Gate: {startup.data_gate_status} · 仅允许受限研究展示。")
for notice in startup.notices:
    st.caption(notice)

st.markdown(
    f"""
    <div class="pat-hero">
      <div class="pat-eyebrow">Personal Alpha Terminal · Command Center</div>
      <h1>市场现在处于什么位置？</h1>
      <p>全球市场、统计状态、Alpha 线索、组合暴露与研究进度。全部来自本地数据库，
      不使用演示数据，不生成无依据的价格预测。</p>
      <div class="pat-hero-meta">
        {status_pill(f"Risk · {risk_label}", tone=risk_tone)}
        <span class="pat-chip">行情 {freshest.strftime("%m-%d") if freshest else "未更新"}</span>
        <span class="pat-chip">研究 {refresh_text}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

section_header("01 / MARKET OVERVIEW", "全球市场", "先看方向、状态与风险，再进入单一资产。")

market_status_columns = st.columns(3)
for column, market, label in zip(
    market_status_columns,
    ("A", "HK", "US"),
    ("A股", "港股", "美股"),
    strict=True,
):
    available = [item for item in snapshots if item.instrument.market == market]
    with column:
        kpi_card(
            f"{label}数据",
            "可用" if available else "待配置",
            (
                f"最新 {max(item.date for item in available):%Y-%m-%d}"
                if available
                else "尚未导入可认证的指数行情"
            ),
            tone="positive" if available else "accent",
        )

if digest.quality_status in {"blocked", "failed"}:
    reasons = "；".join(digest.quality_blockers[:3]) or "最新数据质量检查未通过"
    st.error(f"数据质量已阻断下游分析：{reasons}")
elif digest.quality_status == "not_run":
    st.warning("尚未运行数据质量认证。研究模块会保持 fail-closed。")

if snapshots:
    columns = st.columns(min(6, len(snapshots)))
    for index, snapshot in enumerate(snapshots[:6]):
        change = snapshot.change_pct
        tone = "positive" if (change or 0) >= 0 else "negative"
        with columns[index]:
            kpi_card(
                snapshot.instrument.symbol,
                f"{change:+.2%}" if change is not None else "—",
                (
                    f"{format_price(snapshot.close, snapshot.currency)} · "
                    f"{format_volume(snapshot.volume)} · {snapshot.date:%m-%d}"
                ),
                tone=tone,
            )
    market_left, market_right = st.columns((1.85, 1), gap="medium")
    with market_left:
        st.plotly_chart(
            market_change_chart(snapshots),
            width="stretch",
            config=PLOTLY_CONFIG,
            key="home-market-change",
        )
    with market_right:
        with st.container(border=True):
            st.markdown("#### 市场状态")
            if regime is not None and regime.observations:
                point = regime.current
                confidence = assess_regime_point(point)
                label_map = {
                    "risk_on": "Risk-On",
                    "neutral": "Neutral",
                    "risk_off": "Risk-Off",
                }
                tone_map = {
                    "risk_on": "positive",
                    "neutral": "accent",
                    "risk_off": "negative",
                }
                st.markdown(
                    status_pill(
                        label_map.get(point.regime, point.regime),
                        tone=tone_map.get(point.regime, "neutral"),
                    ),
                    unsafe_allow_html=True,
                )
                regime_values = point.probabilities or point.scores
                st.plotly_chart(
                    regime_distribution_chart(
                        {
                            "Risk-On": regime_values["risk_on"],
                            "Neutral": regime_values["neutral"],
                            "Risk-Off": regime_values["risk_off"],
                        },
                        calibrated=point.probabilities is not None,
                    ),
                    width="stretch",
                    config=PLOTLY_CONFIG,
                    key="home-regime-probabilities",
                )
                st.caption(
                    f"证据质量 {confidence.percent} · 广度样本 "
                    f"{point.breadth_constituent_count} · "
                    f"{('OOS calibrated' if point.probabilities is not None else 'Score only')}; "
                    "非预测正确率"
                )
            else:
                empty_state("尚未运行市场状态模型。", hint="每日分析完成后自动显示。")
else:
    empty_state(
        "尚无可展示的指数行情。",
        hint="先登记全球指数并运行每日数据更新；正式界面不会填充示例数据。",
    )

st.markdown(
    f'<div class="pat-warning">风险等级：{risk_label} · {risk_reason}</div>',
    unsafe_allow_html=True,
)

section_header(
    "02 / ALPHA CENTER",
    "Alpha Center",
    "只展示达到样本门槛的历史证据，并明确区分统计关系与预测。",
)

event_column, probability_column, relationship_column = st.columns(3, gap="medium")
with event_column:
    with st.container(border=True):
        st.markdown("#### 事件历史证据")
        if digest.events:
            for event in digest.events:
                trigger_text = (
                    "今日触发"
                    if freshest is not None and event.last_event_date == freshest
                    else (
                        f"最近触发 {event.last_event_date:%m-%d}"
                        if event.last_event_date is not None
                        else "历史事件样本"
                    )
                )
                interval = (
                    f"区间 {event.interval_lower:.0%}–{event.interval_upper:.0%}"
                    if event.interval_lower is not None and event.interval_upper is not None
                    else "区间不可用"
                )
                signal_row(
                    f"{event.trigger_symbol} → {event.target_symbol} · {event.horizon_days}D",
                    f"{event.probability:.0%}",
                    f"{event.event_name} · {trigger_text} · 样本 {event.sample_size} · {interval}",
                )
        else:
            empty_state("暂无达到推断门槛的事件信号。")
        st.caption("按有效样本量展示，不按最高历史胜率挑选；历史关系不代表未来结果。")

with probability_column:
    with st.container(border=True):
        st.markdown("#### 条件概率证据")
        if digest.probabilities:
            for probability in digest.probabilities:
                interval = (
                    f"可信区间 {probability.interval_lower:.0%}–{probability.interval_upper:.0%}"
                    if probability.interval_lower is not None
                    and probability.interval_upper is not None
                    else "可信区间不可用"
                )
                average = (
                    f"平均收益 {probability.average_return:+.2%}"
                    if probability.average_return is not None
                    else "平均收益不可用"
                )
                signal_row(
                    f"{probability.target_symbol} · {probability.horizon_days}D",
                    f"{probability.probability:.0%}",
                    f"贝叶斯平滑 · 样本 {probability.sample_size} · {interval} · {average}",
                )
        else:
            empty_state("暂无满足最小样本限制的条件概率。")
        st.caption(
            "按有效样本量展示；跨标的和窗口未做统一多重比较校正，"
            "不代表机会、预测或交易建议。"
        )

with relationship_column:
    with st.container(border=True):
        st.markdown("#### 异常关系")
        if digest.relationships:
            direction_labels = {
                "strengthened": "关系增强",
                "weakened": "关系减弱",
                "sign_flip": "方向翻转",
            }
            for relationship in digest.relationships:
                signal_row(
                    f"{relationship.left_label} ↔ {relationship.right_label}",
                    f"Δ {relationship.absolute_change:.2f}",
                    (
                        f"{direction_labels.get(relationship.direction, relationship.direction)} · "
                        f"{relationship.baseline_correlation:+.2f} → "
                        f"{relationship.current_correlation:+.2f} · "
                        f"{relationship.detected_on:%m-%d}"
                    ),
                )
        else:
            empty_state("最新关系分析未发现阈值异常。")

section_header("03 / PORTFOLIO", "Portfolio", "资产、收益和风险放在同一口径下观察。")

portfolio = digest.portfolio
if portfolio is not None:
    portfolio_metrics = st.columns(4)
    with portfolio_metrics[0]:
        kpi_card(
            "组合价值",
            format_price(portfolio.total_value, portfolio.base_currency),
            f"估值日 {portfolio.as_of_date:%Y-%m-%d}",
            tone="accent",
        )
    with portfolio_metrics[1]:
        kpi_card(
            "年化收益",
            f"{portfolio.annualized_return:+.2%}",
            "当前权重历史回放",
            tone="positive" if portfolio.annualized_return >= 0 else "negative",
        )
    with portfolio_metrics[2]:
        kpi_card(
            "最大回撤",
            f"{portfolio.max_drawdown:.2%}",
            f"年化波动 {portfolio.annualized_volatility:.1%}",
            tone="negative" if portfolio.max_drawdown <= -0.15 else "neutral",
        )
    with portfolio_metrics[3]:
        kpi_card(
            "风险效率",
            f"Sharpe {portfolio.sharpe_ratio:.2f}"
            if portfolio.sharpe_ratio is not None
            else "Sharpe —",
            f"Beta {portfolio.beta:.2f}" if portfolio.beta is not None else "Beta 不可用",
        )
    allocation_left, allocation_right = st.columns(2, gap="medium")
    with allocation_left:
        with st.container(border=True):
            st.markdown("#### 主要资产")
            if portfolio.top_positions:
                for label, weight in portfolio.top_positions:
                    allocation_bar(label, weight)
            else:
                st.caption("持仓标签不可用。")
    with allocation_right:
        with st.container(border=True):
            st.markdown("#### 行业暴露")
            for label, weight in sorted(
                portfolio.industry_exposure.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:5]:
                allocation_bar(label, weight)
    st.caption("组合收益来自当前权重历史回放，不等同于真实交易账本业绩。")
else:
    empty_state("尚无已完成的组合风险快照。", hint="运行组合风险分析后显示资产、收益与风险。")

section_header(
    "04 / RESEARCH",
    "Research",
    "报告、因子与回测按最近完成时间排列，失败运行不会进入首页。",
)

report_column, factor_column, backtest_column = st.columns(3, gap="medium")
with report_column:
    with st.container(border=True):
        st.markdown("#### AI 与研究报告")
        ai_reports = tuple(
            report for report in digest.reports if report.generated_by != "deterministic"
        )
        if ai_reports:
            for report in ai_reports[:2]:
                signal_row(
                    report.title,
                    report.generated_by,
                    (
                        f"{report.report_type} · {report.as_of_date:%Y-%m-%d} · "
                        f"来源 {report.source_count}"
                    ),
                )
        else:
            st.caption("AI 报告尚未生成；系统不会在缺少凭据或数据依据时伪造内容。")
        deterministic = tuple(
            report for report in digest.reports if report.generated_by == "deterministic"
        )
        for report in deterministic[:2]:
            signal_row(
                report.title,
                "数据报告",
                f"{report.report_type} · {report.as_of_date:%Y-%m-%d} · 来源 {report.source_count}",
            )

with factor_column:
    with st.container(border=True):
        st.markdown("#### 因子研究")
        if digest.factor is not None:
            factor = digest.factor
            signal_row(
                f"{factor.market} · {factor.analysis_type}",
                f"{factor.score_count} 只",
                f"完成于 {factor.as_of_date:%Y-%m-%d}",
            )
            if factor.cumulative_return is not None:
                signal_row(
                    "历史因子回测",
                    f"{factor.cumulative_return:+.1%}",
                    f"最大回撤 {factor.max_drawdown:.1%}"
                    if factor.max_drawdown is not None
                    else "最大回撤不可用",
                )
        else:
            empty_state("尚无已完成的因子研究。")

with backtest_column:
    with st.container(border=True):
        st.markdown("#### 回测结果")
        if digest.backtest is not None:
            backtest = digest.backtest
            signal_row(
                backtest.strategy_name,
                f"{backtest.total_return:+.1%}",
                f"{backtest.market} · 截止 {backtest.end_date:%Y-%m-%d}",
            )
            signal_row(
                "风险调整后表现",
                f"Sharpe {backtest.sharpe_ratio:.2f}"
                if backtest.sharpe_ratio is not None
                else "Sharpe —",
                (
                    f"最大回撤 {backtest.max_drawdown:.1%} · "
                    f"验证问题 {backtest.validation_issue_count}"
                ),
            )
        else:
            empty_state("尚无已完成且通过持久化的回测。")

if oldest is not None and freshest is not None:
    st.caption(
        f"行情覆盖 {oldest:%Y-%m-%d}–{freshest:%Y-%m-%d} · "
        "首页使用有界只读查询和 45 秒缓存 · 所有概率均为历史统计，不是交易建议"
    )
