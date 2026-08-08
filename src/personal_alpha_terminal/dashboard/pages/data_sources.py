from __future__ import annotations

import streamlit as st

from personal_alpha_terminal.dashboard.components import page_header
from personal_alpha_terminal.data.market_data.capabilities import PROVIDER_CAPABILITIES

page_header(
    "数据源与数据合同",
    "只展示代码中已登记的 Provider 能力；连接检查不会写入研究数据库。",
)

rows = [
    {
        "市场": item.market,
        "资产类型": item.asset_type,
        "Provider": item.provider,
        "专用端点": item.endpoint,
        "原始成交量单位": item.raw_volume_unit,
        "研究库成交量单位": item.volume_unit,
        "价格合同": item.price_type,
        "状态": "可配置" if item.supported else "已被安全门禁阻止",
    }
    for item in PROVIDER_CAPABILITIES
]
columns = st.columns(3)
for column, market in zip(columns, ("A", "HK", "US"), strict=True):
    market_rows = [row for row in rows if row["市场"] == market]
    supported = sum(row["状态"] == "可配置" for row in market_rows)
    column.metric(f"{market} 市场", f"{supported}/{len(market_rows)} 类资产可配置")

st.dataframe(
    rows,
    width="stretch",
    hide_index=True,
    column_config={
        "状态": st.column_config.TextColumn(help="不支持的适配器不会回退到股票端点。"),
        "研究库成交量单位": st.column_config.TextColumn(
            help="Schema 校验通过后才允许写入；A 股股票必须为 share。"
        ),
    },
)

with st.expander("数据进入研究库前会发生什么？", expanded=True):
    st.markdown(
        "Provider Raw Layer → Normalization Layer → Validation Layer → Research Database。"
        "任一步失败都会阻断写入和下游分析。Provider 不允许直接写数据库，资产类型也"
        "不允许回退到股票接口。"
    )

if st.button("运行本地配置合同检查", type="primary"):
    invalid = any(
        row["状态"] == "可配置"
        and (
            row["原始成交量单位"] == "unknown"
            or row["研究库成交量单位"] == "unknown"
        )
        for row in rows
    )
    if not invalid:
        st.success("本地 Provider 路由和单位合同检查通过。此结果不等同于外部数据源认证。")
    else:
        st.error("发现已启用但单位不明确的 Provider 合同；真实数据更新已阻断。")

st.info(
    "A/HK/US 认证历史数据、双源对账、点时公司行动和退市样本认证仍未完成。"
    "在这些门禁关闭前，页面不会把连接可用描述为数据已认证。"
)
