from datetime import date, timedelta

import streamlit as st

from personal_alpha_terminal.dashboard.charts import price_chart, volume_chart
from personal_alpha_terminal.dashboard.components import (
    empty_state,
    format_percent,
    format_price,
    format_volume,
    page_header,
    require_database,
)
from personal_alpha_terminal.dashboard.runtime import dashboard_service

require_database()
page_header("股票详情", "查看股票或 ETF 的价格走势、成交量和基础信息")

with dashboard_service() as service:
    options = service.list_stock_options()

if not options:
    empty_state(
        "股票主数据为空。",
        hint="请先登记股票并通过 Market Data Engine 更新日行情。",
    )
    st.stop()

selector_col, range_col = st.columns([3, 1])
with selector_col:
    selected = st.selectbox(
        "证券",
        options,
        format_func=lambda option: option.label,
        key="stock-detail-instrument",
    )
with range_col:
    range_label = st.selectbox(
        "时间范围",
        ("3个月", "6个月", "1年", "3年"),
        index=2,
        key="stock-detail-range",
    )

days_by_range = {"3个月": 92, "6个月": 183, "1年": 365, "3年": 1095}
end_date = date.today()
start_date = end_date - timedelta(days=days_by_range[range_label])

with dashboard_service() as service:
    detail = service.stock_detail(
        selected.id,
        start_date=start_date,
        end_date=end_date,
    )

if detail is None:
    st.error("所选证券不存在或已被删除。")
    st.stop()

latest = detail.latest
metric_columns = st.columns(4)
metric_columns[0].metric(
    "最新价格",
    format_price(latest.close if latest else None, detail.currency),
    format_percent(detail.period_change_pct) if latest else None,
)
metric_columns[1].metric("最新成交量", format_volume(latest.volume if latest else None))
metric_columns[2].metric("市场 / 交易所", f"{detail.instrument.market} / {detail.exchange}")
metric_columns[3].metric("行业", detail.industry or "未分类")

if not detail.prices:
    empty_state("所选时间范围没有行情数据。")
else:
    st.plotly_chart(
        price_chart(detail.prices, f"{detail.instrument.symbol} 收盘价"),
        width="stretch",
        key="stock-price-chart",
    )
    st.plotly_chart(
        volume_chart(detail.prices),
        width="stretch",
        key="stock-volume-chart",
    )

st.subheader("基本信息")
st.dataframe(
    [
        {
            "代码": detail.instrument.symbol,
            "名称": detail.instrument.name,
            "市场": detail.instrument.market,
            "交易所": detail.exchange,
            "币种": detail.currency,
            "行业": detail.industry or "未分类",
            "上市日期": detail.list_date,
            "状态": "正常" if detail.is_active else "停用",
            "最新数据日": latest.date if latest else None,
            "数据源": latest.source if latest else None,
        }
    ],
    width="stretch",
    hide_index=True,
)
