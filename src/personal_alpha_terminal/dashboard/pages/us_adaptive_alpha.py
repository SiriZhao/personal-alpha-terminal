import streamlit as st

from personal_alpha_terminal.dashboard.components import page_header, require_database
from personal_alpha_terminal.dashboard.runtime import us_adaptive_alpha_service

STATUS_LABELS = {
    "active": "可用",
    "experimental": "实验",
    "isolated": "独立运行",
    "disabled": "已禁用",
}


require_database()
page_header(
    "US Quant Dashboard",
    "专业中低频美股研究与手动调仓框架；量化代码决定排名与风险，AI 仅解释结果。",
)

with us_adaptive_alpha_service() as service:
    overview = service.overview()

gate = overview.data_gate
production_gate = overview.production_gate
metrics = st.columns(5)
metrics[0].metric("System Status", "Research Preview")
metrics[1].metric("Data Gate", production_gate.status.value)
metrics[2].metric(
    "可用 Sleeve",
    sum(item.status.value in {"active", "experimental", "isolated"} for item in overview.sleeves),
)
metrics[3].metric(
    "已禁用 Sleeve",
    sum(item.status.value == "disabled" for item in overview.sleeves),
)
metrics[4].metric("执行阶段", "Manual / Paper Only")

st.caption(
    "Phase 2 · US data validation。真实数据认证未通过时，模型状态保持 Blocked，"
    "不会生成候选排名、目标仓位或调仓清单。"
)

if production_gate.status.value == "BLOCKED":
    st.error("中央数据门禁未通过：禁止股票排名、目标仓位和手动调仓票据。")
elif gate.status.value == "degraded":
    st.warning("数据处于降级状态：仅允许研究展示，不允许进入组合。")
else:
    st.success("数据门禁通过；仍需冻结样本外验证和人工前向观察门禁。")

for blocker in gate.blockers:
    st.caption(f"BLOCKED · {blocker}")
for blocker in production_gate.blockers:
    st.caption(f"CENTRAL BLOCKED · {blocker}")
for warning in gate.warnings:
    st.caption(f"WARNING · {warning}")

st.subheader("Strategy Sleeves")
st.dataframe(
    [
        {
            "策略": item.label,
            "状态": STATUS_LABELS[item.status.value],
            "原因": item.reason,
            "所需能力": ", ".join(item.required_capabilities) or "cash-only",
            "研究资本上限": item.maximum_capital_weight,
        }
        for item in overview.sleeves
    ],
    width="stretch",
    hide_index=True,
    column_config={
        "研究资本上限": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
    },
)

st.subheader("Decision Decomposition")
decomposition = st.columns(4)
decomposition[0].info("Base Strategy Signal\n\n独立 Sleeve 产生基础研究信号")
decomposition[1].info("Conditional Evidence\n\n只增强或削弱已有信号")
decomposition[2].info("Market Regime\n\n平滑调整总风险预算")
decomposition[3].info("Portfolio Risk\n\n执行集中度、流动性与尾部约束")

st.subheader("Current Research Output")
if not production_gate.may_generate_positions:
    st.warning("最终研究等级：证据不足 / 风险受限 / 暂不进入组合")
    st.metric("建议仓位区间", "0% – 0%", help="数据门禁未通过时强制为零。")
else:
    st.info("尚无冻结的独立 Sleeve 信号。没有信号是允许的结果。")

with st.expander("方法与风险声明"):
    st.markdown(
        """
- Conditional Probability 必须同时展示无条件基准、Probability Lift、样本量、
  有效样本量、区间、尾部损失、成本后期望和 FDR。
- Market Graph 与 Lead-Lag 只生成候选关系，不能证明可交易因果关系。
- 未通过概率校准时，Market Regime 只能显示 Score。
- 财务质量与财报后漂移在 point-in-time 数据未认证时自动禁用。
- Capital Preservation 是风险目标，不是本金保证。股票和防御资产均可能亏损。
- 历史与模拟结果不保证未来表现，也不保证跑赢 SPY、VOO、QQQ 或 QQQM。
- 系统不自动下单、不使用杠杆、不自动做空、不交易裸期权。
"""
    )

st.caption(
    f"能力快照生成时间：{overview.generated_at.isoformat()} · "
    f"追溯来源：{', '.join(overview.source_ids) or 'none'}"
)
