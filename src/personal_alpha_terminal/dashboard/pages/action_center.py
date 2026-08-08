"""Legacy Streamlit review page.

The terminal is the primary product interface. This compatibility page records
human decisions only and never creates a simulated or broker order.
"""

from datetime import UTC, datetime

import streamlit as st

from personal_alpha_terminal.dashboard.components import empty_state, format_percent, page_header
from personal_alpha_terminal.dashboard.runtime import decision_database_ready, decision_service
from personal_alpha_terminal.decision_engine import UserDecision

page_header(
    "行动中心 Action Center",
    "确定性量化建议的人工复核入口；系统不连接券商，也不创建模拟订单。",
)

if not decision_database_ready():
    empty_state("No Decision Generated", hint="决策数据库尚未初始化或不可用。")
    st.stop()

with decision_service() as service:
    latest = service.latest_run()
    pending = service.pending(now=datetime.now(UTC))

if latest is None:
    empty_state("No Decision Generated", hint="尚无通过数据门禁的量化决策运行。")
    st.stop()

header = st.columns(4)
header[0].metric("Data Gate", latest.gate_status)
header[1].metric("运行状态", latest.status)
header[2].metric("待复核", len(pending))
header[3].metric("来源数量", len(latest.source_ids))
st.caption(
    f"as-of {latest.as_of_time} · data {latest.data_version} · "
    f"model {latest.model_version} · fingerprint {latest.input_fingerprint[:12]}"
)

if latest.gate_status != "APPROVED" or latest.status != "generated":
    empty_state(
        "Research Only · No Decision Generated",
        hint="；".join(latest.blockers[:5]) or "数据门禁未批准组合决策。",
    )
    st.stop()

if not pending:
    empty_state("当前没有待复核事项", hint="无信号也是有效结果；系统不会强制生成交易。")
    st.stop()

for recommendation in pending:
    with st.container(border=True):
        delta = float(recommendation.target_weight - recommendation.current_weight)
        top = st.columns((1.1, 0.8, 1, 1, 1))
        top[0].subheader(recommendation.stock.symbol)
        top[1].metric("操作", recommendation.action)
        top[2].metric("当前", format_percent(float(recommendation.current_weight)))
        top[3].metric("目标", format_percent(float(recommendation.target_weight)))
        top[4].metric("变化", format_percent(delta))
        st.write("量化依据：" + "；".join(recommendation.rationale))
        if recommendation.risk_factors:
            st.warning("风险说明：" + "；".join(recommendation.risk_factors))
        reason = st.text_input(
            "复核备注（可选）",
            key=f"decision-reason-{recommendation.recommendation_id}",
        )
        buttons = st.columns(3)
        selected: UserDecision | None = None
        if buttons[0].button("接受", key=f"accept-{recommendation.recommendation_id}"):
            selected = UserDecision.ACCEPTED
        if buttons[1].button("拒绝", key=f"reject-{recommendation.recommendation_id}"):
            selected = UserDecision.REJECTED
        if buttons[2].button("观望", key=f"watch-{recommendation.recommendation_id}"):
            selected = UserDecision.WATCH
        if selected is not None:
            try:
                with decision_service() as service:
                    service.review(
                        recommendation_id=recommendation.recommendation_id,
                        decision=selected,
                        decided_at=datetime.now(UTC),
                        reason=reason,
                    )
                st.success(
                    "复核结果已记录。接受仅表示待人工在Charles Schwab执行，不会自动下单。"
                )
                st.rerun()
            except ValueError as error:
                st.error(f"无法记录复核结果：{error}")
