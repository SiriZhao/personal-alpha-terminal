import streamlit as st

from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.dashboard.components import page_header

page_header("关于", PRODUCT_DISPLAY_NAME)

st.markdown(
    """
Personal Alpha Terminal 是本地优先、可解释、fail-closed 的个人量化研究工具。

**Personal Quant Investment OS 定位**

- 每日首页汇总数据状态、组合状态、确定性量化建议和人工复核；
- 因子、事件、条件证据、市场关系和回测作为独立研究后台；
- AI 只解释量化证据，不参与股票排名、目标权重或风险门禁；
- 不自动下单，不连接券商，不操作真实资金；
- 数据不足或质量门禁失败时不生成确定性结论；
- Mock 内容必须明确标识，不能冒充真实市场研究；
- 市场状态未通过样本外校准时只显示“市场状态评分”。

**仍未完成的数据与实盘认证**

- A/HK/US 认证历史数据和 point-in-time 公司行动；
- 真实历史危机验证与市场状态概率校准；
- 真实 PostgreSQL 损坏恢复演练；
- 全新独立 Windows VM 认证与商业代码签名；
- 实盘交易认证（不在本预览版范围内）。

历史和模拟结果不保证未来表现。本软件不构成投资建议，也不保证保本、盈利或跑赢市场。
"""
)
