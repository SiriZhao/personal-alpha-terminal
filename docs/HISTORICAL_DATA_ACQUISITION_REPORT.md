# Historical Research Data Acquisition & Certification Report

日期：2026-08-12

结论：`NOT_CERTIFIABLE`
研究数据可用于正式 Alpha Research：**否**

## 1. 冻结研究基线

本轮只处理数据，没有调整因子权重、信号阈值、组合限制或 Probability 参数，也没有打开 locked OOS。

| 项目 | 冻结值 |
|---|---|
| Research baseline | `historical-research-baseline-8fb51f1a7b2fdaa0561a` |
| Git baseline | `1d90aa25466359eba38a3a50b048eeaac9f9b8ce` |
| Universe policy | `broad-us-equity-v1-fc8f4a945161` |
| Universe policy hash | `fc8f4a945161332edf486d2df4971b851111a87b5b6c3ea7bf33bc2e0d846207` |
| Strategy candidate | `USAdaptiveAlphaCoreV1:1.0.0:427671e52a53` |
| Strategy parameter hash | `427671e52a5391d97cd01fd855aec3bbafa7c762c072aeee253406fa993416b6` |
| Probability model | `probability-residual-overlay-v1-d774042de6fd` |
| Probability role | 未取得精确生产批准时仅作 supporting overlay，Base Alpha 不变 |
| Cost model hash | `ad9592a0b1739a0a99c3ff982d4377f057b0ab2e780267d1ffcb59ffb8392e9b` |
| Risk model hash | `3e322b866b573a1ca64725c4fbba98c86e7bd85fa2a1b3ce8a75b64163730713` |

机器证据：`artifacts/latest/historical_research_baseline.json`、`artifacts/latest/historical_data_acquisition.json`。

## 2. Expanded universe 的历史重建规则

目标市场为 NYSE、Nasdaq、NYSE American 的普通股。ETF、ETN、preferred、warrant、right、unit、closed-end fund、OTC、test issue 和异常 financial status 均排除；ADR、REIT 默认排除且只能由显式配置纳入。股票池不以公司规模或今天的成分名单定义。

日期 `T` 的 eligibility 只能读取 `available_at <= decision_time(T)` 的证券类型、listing lifecycle、membership、价格与 corporate-action 数据。价格门槛、252-session listing age、有效 bar 覆盖、缺失率和 20-session ADV/median dollar volume 都必须使用 `T` 以前的数据。Ticker 只用于显示，长期身份必须使用 permanent security ID。今天的 8,833 条目录记录不能倒填到任何历史日期。

当前目录含 8,833 个证券，名称/类型规则识别 5,263 个 common-equity record；完整 daily universe gate 在最近证书中进一步得到 4,957 个 security-type eligible，但只有 9 个拥有本地完整数据、流动性与特征资格。后两者都是当前 daily 截面，不是历史 membership。

## 3. 历史长度要求

冻结要求为 252 sessions 因子 warm-up + 1,008 TRAIN + 504 VALIDATION + 21 EMBARGO + 252 LOCKED_OOS，共 2,037 个 XNYS sessions。按 2026-08-10 向前计算的最晚最低起点是 2018-07-02；配置保守目标仍为 2015-01-01。当前价格库存只有 2024-08-07 至 2026-08-10，因此即使忽略 survivorship 问题也不满足研究跨度。

## 4. Provider capability matrix

以下结论只来自 2026-08-12 查阅的官方产品、API、价格和许可页面；未被官方页面证明的字段记为 `UNKNOWN`，`PARTIAL` 不按 `YES` 使用。

| Provider | Raw OHLCV | Delisted | Permanent ID | Ticker history | Listing lifecycle | Historical membership | Corp actions | Delisting return | PIT vintage | Total return | PIT fundamentals | Calendar | Grade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Nasdaq Trader current directory | NO | NO | NO | NO | PARTIAL | NO | NO | NO | NO | NO | NO | NO | LIVE_ONLY |
| Alpha Vantage | YES | YES | NO | UNKNOWN | PARTIAL | YES (2010+) | PARTIAL | NO | NO | PARTIAL | UNKNOWN | PARTIAL | RESEARCH_PARTIAL |
| Twelve Data | YES | UNKNOWN | PARTIAL | UNKNOWN | UNKNOWN | NO | PARTIAL | NO | NO | PARTIAL | UNKNOWN | PARTIAL | RESEARCH_PARTIAL |
| Tiingo | YES | PARTIAL | PARTIAL | PARTIAL | PARTIAL | NO | PARTIAL | NO | NO | PARTIAL | PARTIAL | NO | RESEARCH_PARTIAL |
| EODHD | YES | YES | PARTIAL | UNKNOWN | PARTIAL | NO | PARTIAL | NO | NO | PARTIAL | PARTIAL | PARTIAL | RESEARCH_PARTIAL |
| Massive | YES | YES | PARTIAL | PARTIAL | YES | YES | PARTIAL | NO | NO | PARTIAL | UNKNOWN | NO | REQUIRES_LICENSE |
| Norgate Data Platinum/Diamond | YES | PARTIAL | UNKNOWN | PARTIAL | YES | PARTIAL | PARTIAL | UNKNOWN | NO | PARTIAL | NO | PARTIAL | CONDITIONAL_PROFESSIONAL |
| Nasdaq Data Link / Sharadar | PARTIAL | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | PARTIAL | UNKNOWN | NO | PARTIAL | YES | NO | REQUIRES_LICENSE_DUE_DILIGENCE |
| CRSP US Stock | YES | YES | YES | YES | YES | YES | YES | YES | PARTIAL | YES | NO | PARTIAL | PROFESSIONAL_REFERENCE_STANDARD |

官方证据：

- [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/)：listing status 可按历史日期查询 active/delisted，支持日期从 2010-01-01 起；但页面没有证明 permanent ID 或 delisting return。
- [Twelve Data pricing](https://twelvedata.com/pricing) 与 [EOD pricing](https://support.twelvedata.com/en/articles/12682324-end-of-day-eod-pricing-market-data)：免费/个人套餐及 EOD 能力；未证明完整历史 membership。
- [Tiingo EOD documentation](https://www.tiingo.com/documentation/end-of-day) 与 [fundamentals documentation](https://www.tiingo.com/documentation/fundamentals)：raw/adjusted prices、corporate-action adjustment 与 permaTicker；未证明 broad historical membership 或 delisting return。
- [EODHD delisted documentation](https://eodhd.com/financial-apis/delisted-stock-companies-data-2) 与 [pricing](https://eodhd.com/pricing)：可查询 delisted 和 US symbol changes，但永久身份、delisting return 与 PIT vintage 仍未被证明。
- [Massive market-data terms](https://massive.com/legal/market-data-terms-of-service)：个人 market-data 权利默认是 display use，non-display use 或创建 investment strategy 需要额外许可，终止后还要求删除数据，因此未授权前不能 ingest 为项目研究数据。
- [Norgate package comparison](https://norgatedata.com/stockmarketpackages.php)、[data content](https://norgatedata.com/data-content-tables.php) 与 [FAQ](https://norgatedata.com/data-package-faq.php)：Platinum 有 1990 起价格、delisted 与历史 index constituents，但官方明确没有声称 delisted 库完整，membership 通过本地插件查询而非可导出列表。
- [Nasdaq Data Link data organization](https://docs.data.nasdaq.com/v1.0/docs/data-organization) 与 [Sharadar publisher](https://data.nasdaq.com/publishers/SHARADAR)：相关产品为 premium，字段与许可需要订阅后逐包验证。
- [CRSP US Stock Databases](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases)：覆盖 active/inactive securities，并提供 PERMNO/PERMCO 等永久标识，属于需报价授权的专业参考标准。

## 5. 当前自动获得并验证的数据

| Layer | 实际结果 | 研究认证语义 |
|---|---:|---|
| Current official directory | 8,833 securities；hash `4af011...bc57e` | `LIVE_ONLY`，不可倒填历史 |
| Local live prices | 9,055 rows / 18 securities / 2024-08-07..2026-08-10 | inventory only |
| Historical security master | 0 certified securities | 缺失 |
| Historical membership | 0 rows / 0 sessions / 0.0% | 缺失 |
| Delisted/lifecycle | 0 delisted；8,833 lifecycle unknown | 缺失 |
| Corporate actions | 3 live rows | 不构成 PIT history |
| PIT total-return versions | 216 live rows | 不构成历史 vintage |
| XNYS calendar | 2,917 sessions / 23 early closes / 2015-01-02..2026-08-10 | 可复现规则层，已绑定 hash |
| SPY benchmark | 503 raw live rows | convention 未认证 |
| QQQ benchmark | 503 raw live rows | convention 未认证 |

Calendar 现在显式绑定请求起止日期与 `exchange_calendars` 规则版本，holiday 边界不会再依赖运行机器的滚动默认窗口。Momentum、trend、volatility、embargo 和 OOS 长度均以 session index 计数。

## 6. Ingest、存储与可复现性

研究导入继续支持 CSV、Parquet、SQLite，经 schema validation → normalization → row-level hashing → certification。正式数据按 security master、membership、prices、corporate actions、calendar 与 benchmark 分层保存，runtime raw/cache/snapshot 不进入 Git。

新增 acquisition checkpoint contract：provider/dataset/chunk ID、chunk content hash 与 row count 原子落盘；相同 chunk 重试幂等，已完成 chunk 内容变化会 fail closed。重复 security、membership、price、corporate-action 或 calendar provider row 会确定性拒绝。Manifest 原子发布，inventory hash 与 dataset content hash 语义分离；本次没有合法 research rows，因此 `research_dataset_content_hash = null`，没有用 inventory hash 冒充。

## 7. Probability 数据时间约束

Probability 数据必须与 base strategy 共用 permanent security/session/PIT identities。每条 observation 必须显式保存 `feature_time`、`condition_time`、`outcome_horizon`、`outcome_time`、`available_at`，并满足 condition 先于 outcome、`available_at <= decision_time`。当前 Probability 仍是 supporting overlay；研究数据和 exact-version OOS approval 不存在时不会修改 deterministic Base Alpha。

## 8. Certification attempt

机器 manifest：`historical-acquisition-e5fb4cb3401c7a8ef963`，manifest hash `e5fb4cb3401c7a8ef9638394c7b3c7f311c9b992900a90aadc3eea14f12842a1`。

阻塞项：

1. `HISTORICAL_MEMBERSHIP_INCOMPLETE` / `CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED`
2. `DELISTING_HISTORY_INCOMPLETE` / `DELISTING_RETURN_UNAVAILABLE`
3. `SECURITY_IDENTIFIER_HISTORY_INCOMPLETE`
4. `CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE` / `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`
5. `REQUIRED_PERIOD_COVERAGE_INCOMPLETE`
6. `BENCHMARK_PIT_TOTAL_RETURN_CONVENTION_INCOMPLETE`

最终 classification 为 `NOT_CERTIFIABLE`，production eligible 为 false。未创建 OOS lock，因为只有 `RESEARCH_CERTIFIED` 数据才允许预注册 split；没有读取或计算任何 locked OOS 策略结果。

## 9. E2E 与门禁

- `research-data providers`：成功，展示九类官方审计 provider。
- `research-data acquire`：真实读取当前目录、SQLite、XNYS calendar、SPY/QQQ 并生成 immutable evidence；预期 exit 3（NOT_CERTIFIABLE）。
- `research-data status/certify`：保持 NOT_CERTIFIABLE，不生成 research approval。
- Daily regression：zh-CN 与 en-US 对相同 no-refresh 输入均得到 `VALID_ANALYSIS_NON_ACTIONABLE`，canonical result hash 同为 `02e15f97f29a495aa1db6f76e4abb7ee7c6b3b2c88f311702df3f798c1aba4e7`；DATA/PIT/FEATURE/FACTOR 为 PASS，Signal 仅因 `STRATEGY_NOT_PRODUCTION_APPROVED` 阻塞，0 actions。`main` 仍为 NAV/cash USD 100,000、0 positions。
- Quality gates：Ruff PASS；strict mypy `361 source files` PASS；full pytest `647 passed`，没有 skip/xfail 降级。

## 10. 结论

当前免费/已配置方案不足以开始正式 Alpha Research。最小人工动作是先申请 Norgate US Stocks Platinum 的试用/订阅前技术验收，确认 Python 插件能够按日期查询 broad listing eligibility、稳定映射 current/delisted identity，并明确本地缓存/派生研究许可；未通过这些验收则直接选用 CRSP 等带永久标识与 delisting return 的 licensed research dataset。详见 `docs/DATA_PROVIDER_DECISION.md`。
