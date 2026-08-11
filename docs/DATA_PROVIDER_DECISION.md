# Historical Research Data Provider Decision

日期：2026-08-12
状态：需要人工订阅/授权；本轮没有购买、绑卡或接受许可。

## RECOMMENDED — 方案 A：Norgate Data US Stocks Platinum，先试用验收

- 产品：US Stocks Platinum。
- 官方价格：6 个月 USD 346.50；12 个月 USD 630。官方页面显示 12 个月相对 6 个月年化价格有 10% 折扣。[官方套餐比较](https://norgatedata.com/stockmarketpackages.php)
- 覆盖：daily price history 回到 1990、major-exchange current securities、delisted securities、历史 index constituents；官方称适合 backtesting。[订阅能力](https://norgatedata.com/subscribe/subscribe.php)
- 存储/接入：Windows 本地数据库与 Python/分析平台插件。历史 index membership 通过插件逐日查询，不提供原始 constituent list。[官方 FAQ](https://norgatedata.com/data-package-faq.php)
- 项目 adapter：将 Norgate security/lifecycle、major-exchange listing indicator、delisted、price/capital-event、index membership 映射到现有 provider-neutral schema；按 session/chunk 写 checkpoint，原始 licensed data 保留在 Git ignored storage。
- 能解决：历史价格跨度、current+delisted population、部分 lifecycle、部分 corporate action、部分历史 membership。
- 仍需验收：永久 ID、ticker reuse/merger 映射、真实 delisting return、PIT corporate-action vintage、broad universe（不是某个指数）逐日 membership、订阅终止后的本地缓存与派生研究权利。官方明确不声称 delisted database 完整，因此购买本身不等于 `RESEARCH_CERTIFIED`。[数据内容说明](https://norgatedata.com/data-content-tables.php)
- 选择理由：这是当前最低公开固定价格、可在 Windows/Python 落地、同时含 delisted 与历史 membership 能力的专业候选。建议先用试用做 schema/coverage/license acceptance test，验收失败不购买。

## 方案 B：Massive Advanced + 明确 non-display / strategy license

- 产品：Advanced 个人 API 价格页面为 USD 199/月、20+ 年历史；但该价格本身不包含本项目所需许可。[Stocks plans](https://massive.com/stocks)
- 覆盖：as-of ticker directory、active/inactive、部分 FIGI、raw flat files、prices 与 corporate actions，可做大规模 batch ingest。
- 必须人工动作：在付费前取得 Massive/交易所书面确认或单独协议，允许个人本地长期存储以及 non-display investment-strategy research。
- 关键限制：官方 market-data terms 默认把数据限定为 display use，并明确禁止未授权的 non-display use 或创建 investment strategy；终止时要求删除持有数据。[Market Data Terms](https://massive.com/legal/market-data-terms-of-service)
- 仍不能自动解决：delisting return、严格 PIT adjustment vintage、完整 broad membership 与永久 company identity 的所有边界。
- 结论：只有获得合适 license 后才可启用 adapter；普通个人 plan 不得直接 ingest 为 certified research evidence。

## 方案 C：CRSP US Stock Databases

- 产品：CRSP US Stock Databases，需向 Morningstar/CRSP 询价并签署研究数据许可。[官方产品页](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases)
- 覆盖：daily/monthly market data、corporate actions、active/inactive securities、PERMNO/PERMCO 永久标识；专业交付通常可提供 delisting history/returns，具体字段须以订单字典和合同验收。
- 项目 adapter：批量文件/平台导入 → CRSP permanent identity → ticker vintages/lifecycle → membership rule reconstruction → raw/return fields → calendar/benchmark → manifest/certification。
- 能解决：本项目最关键的永久 identity、inactive/delisted population 与 terminal treatment，是三套方案中最接近专业 reference standard 的路线。
- 缺点：报价制、授权成本最高；local storage、derived artifacts、个人使用范围和终止义务均需合同确认。CRSP 也不自动等于当前 broad-universe policy 的逐日 membership，仍需以当日 exchange/security-type/lifecycle 数据重建并认证。

## 不推荐作为单独认证源的低成本组合

Alpha Vantage、EODHD、Tiingo、Twelve Data 可以补充 prices、delisted list、ticker change 或 corporate actions，但官方公开能力无法同时证明 permanent identity、delisting return、PIT vintage、完整 historical membership 与长期本地研究权利。它们可以作为 secondary validation/provider，不应通过拼接 `PARTIAL` 被包装为 `RESEARCH_CERTIFIED`。

## 最短人工步骤

1. 先向 Norgate 申请试用并确认 Python API、个人本地研究/缓存权利。
2. 提供项目环境一个只读 Norgate database path，不提交数据库或凭证。
3. 运行 adapter acceptance audit；只有永久 ID/lifecycle/membership/delisting/corporate-action/calendar/benchmark 全部门禁通过后，才发布 `RESEARCH_CERTIFIED` 和 OOS lock。
4. 如果 Norgate 验收不能满足 delisting return 或 permanent identity，停止补丁式拼接，改为获取 CRSP 报价。
