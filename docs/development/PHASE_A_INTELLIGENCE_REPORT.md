# Personal Alpha Terminal — Phase A Intelligence Report

**日期：** 2026-08-08  
**版本：** 1.1.0  
**阶段状态：** Implemented and fixture-tested; not certified on live point-in-time news data  
**交易权限：** 无自动交易；Intelligence 不能决定仓位，Risk Engine 保留最终否决权

## 1. 结论

Phase A 已建立单一、版本化、可回放的 Intelligence / Event / Probability 基础链，并接入现有应用服务、数据库迁移与命令行入口。链路为：

```text
Raw information
→ strict structured extraction
→ schema validation and normalization
→ canonical event deduplication
→ immutable persistence / PIT replay
→ event study
→ conditional evidence walk-forward validation
→ opportunity scanner
→ existing Portfolio / Risk trade proposal
```

Scanner 只负责研究候选排序。它不能自行产生目标仓位：只有现有 Portfolio / Risk 链已经给出 `TradeProposal` 时，候选才可携带行动和目标权重；否则状态为 `RESEARCH_ONLY`。AI contribution 在生产配置中强制为 0，AI 不改变 Quant Alpha、概率、仓位或风控结论。

本阶段没有重写行情 Provider、没有新增 UI、没有打包 EXE、没有接入券商，也没有将夹具结果声明为真实 Alpha 证据。

## 2. 实现内容与核心文件

### Unified Event 与 PIT

- `src/personal_alpha_terminal/intelligence/schemas.py`
  - 严格 Pydantic schema：`RawInformation`、`EventEvidence`、`UnifiedEvent`、`AgentResult`。
  - 区分 `published_at`、`observed_at`、`effective_at`、`ingested_at`、`data_cutoff`。
  - 所有时间必须 timezone-aware；违反时间顺序时拒绝。
  - `at_cutoff()` 会剔除 cutoff 后的 evidence 并重算置信度，防止文章更新回流历史。
- `src/personal_alpha_terminal/intelligence/time.py`
  - 使用 XNYS 交易日历映射盘前、常规时段、盘后、周末、节假日与 DST。
  - 盘后事件最早从下一可交易 session 进入事件研究。
- `src/personal_alpha_terminal/intelligence/storage.py`
  - 事件与研究结果使用不可变版本记录；支持任意 cutoff 的确定性 replay。

### News / Earnings / Macro Intelligence

- `src/personal_alpha_terminal/intelligence/extraction.py`
  - LLM 输出必须通过 JSON Schema / typed model 校验，再归一化和 sanity check。
  - company、earnings、macro 等事件类型进入统一 schema。
  - Earnings features 覆盖 EPS/revenue surprise、guidance、margin、estimate revision、management tone、capex revision。
  - Macro features 覆盖 CPI/PCE/NFP/Fed/yield/dollar/oil/policy 等标准化类别。
  - 解析失败、空响应、鉴权失败、限流、超时、模型不可用与 context overflow 均降级，不进入交易链。
- `src/personal_alpha_terminal/intelligence/dedup.py`
  - 根据实体、事件类型、时间窗口与规范化文本相似度构建 canonical event。
  - 多来源只形成一条事件和多条 evidence；来源多样性只有限提升置信度，不按报道数量放大方向。
- `src/personal_alpha_terminal/intelligence/budget.py`、`cache.py`
  - 请求数、token、成本、重试与 timeout 预算。
  - `content_hash + model_version + prompt_version` 缓存键，相同输入不重复调用。

### Event Study

- `src/personal_alpha_terminal/intelligence/event_study.py`
  - trading-session horizons：1D、3D、5D、10D、20D。
  - asset total return 与 benchmark total return 分离，输出 abnormal return。
  - cooldown、overlap flag、cluster/effective weight、right censoring。
  - moving-block bootstrap、Wilson interval、均值/中位数、分位数、最好/最差、expected shortfall、regime distribution。
  - 默认生产最小样本量 30；不足时为 `INSUFFICIENT_SAMPLE`，不伪造高置信结果。

### Conditional Probability 2.0

- `src/personal_alpha_terminal/quant_engine/probability.py`
  - `ConditionalProbability2` 同时输出 baseline/conditional probability、probability lift、odds ratio、baseline/conditional expected return、expected-return lift、credible interval、raw/effective N。
  - Beta-Binomial / empirical-Bayes shrinkage，避免 2/2 被解释为高置信 100%。
  - calibration 输出 Brier Score、Log Loss、ECE 与 reliability buckets。
- `src/personal_alpha_terminal/intelligence/probability.py`
  - preregistered condition definition，最多六个条件，禁止无限条件挖掘。
  - 严格时间排序的 Discovery/Train/Validation/OOS/Walk-forward folds。
  - 输出 rolling/OOS 稳定性；未达到最小样本或 OOS 门禁时结果无效。

### Multi-Agent Research

- `src/personal_alpha_terminal/intelligence/agents.py`
  - News Event、Earnings、Macro、Market Regime Research、Risk Research agent。
  - 输入和输出均为结构化 schema，包含 evidence、observed time、data cutoff、model/version。
  - Regime/Risk agent 只解释现有 Quant Regime/Risk 结果。
  - Aggregator 只聚合结构化证据与状态，不投票、不生成交易方向。

### Daily Opportunity Scanner

- `src/personal_alpha_terminal/intelligence/scanner.py`
  - 支持 `QUANT_ONLY` 与 `QUANT_PLUS_EVENT` 对照。
  - 权重集中配置；事件影响有硬上限；AI feature contribution 必须为 0。
  - 可拆解 quant、probability、event、risk penalty；无 magic hidden weight。
  - 关键数据门禁失败时 `BLOCKED`；intelligence 缺失但 Quant Core 可用时为 quant-only/degraded。
  - 没有现有 `TradeProposal` 时不产生 action/target weight。
- `src/personal_alpha_terminal/intelligence/service.py`
  - 将 materialization、replay、event/probability evidence 与 scanner 接成事务化应用服务。
- `src/personal_alpha_terminal/application/intelligence_service.py`
  - 提供 readiness 与最近 opportunity scan 查询。
- `src/personal_alpha_terminal/application/app_service.py`
  - Headless Application Service 暴露 Intelligence 状态与扫描结果。
- `src/personal_alpha_terminal/cli.py`
  - 新增 `pat intelligence-status` 与 `pat opportunities` JSON 入口。

## 3. Schema 与 Migration

新增 Alembic revision：`d5e8a4c2f710`，当前为唯一 migration head。

新增表：

- `intelligence_raw_information`
- `intelligence_events`
- `intelligence_event_evidence`
- `intelligence_features`
- `intelligence_research_results`
- `intelligence_extraction_cache`

所有实体记录 schema/model/prompt version、data cutoff 与创建/更新时间；事件 evidence 和 feature 使用外键及查询索引。迁移通过 SQLite 集成测试，但本阶段未执行真实 PostgreSQL 生产演练。

## 4. Quant Core 集成与安全门禁

- Intelligence 不创建第二套 Quant Core，不修改 Unified Alpha 的 expected excess return。
- Scanner 消费既有 `AlphaSignal`、Market Regime、Conditional evidence、Event Study 与现有 `TradeProposal`。
- Portfolio Engine / Risk Engine 仍是目标权重与行动候选的唯一权威来源。
- AI 关闭、超时、429 或解析失败时，Quant Core 保持可运行，状态明确为 `INTELLIGENCE_DEGRADED / QUANT_ONLY`。
- 行情、风险、PIT 或组合关键数据失败时 fail closed，不生成可执行建议。
- 正式历史 replay 只读取 cutoff 前已经 materialized、versioned 的结构化事件；回测期间不实时调用 LLM。

## 5. 测试与质量结果

### 自动测试

- Phase A 定向测试：**32 passed**。
- 全仓回归：**432 passed, 2 warnings**，耗时 68.29 秒。
- 两条 warning 均来自第三方 Backtrader 包的 Python escape-sequence `SyntaxWarning`，不是 Phase A 代码失败。

覆盖测试包括：

- schema、timezone 与时间顺序；
- 09:29、09:30、15:59、16:00 ET、盘前、盘后、周末、节假日、DST；
- 多来源去重与历史 cutoff 下文章更新不可见；
- future news / future earnings / next-day close 不可见；
- LLM timeout、401、429、malformed JSON、empty、unavailable model、context overflow；
- budget 与 deterministic cache；
- Event Study 的 next-session、异常收益、overlap/right censoring 和小样本；
- Probability smoothing、区间、calibration、walk-forward、条件预注册与时间顺序；
- Scanner quant-only、数据阻断、不可自行产生目标权重；
- 数据库 migration、事件 replay、缓存幂等；
- `raw info → event → event study → probability → scanner` 集成链。

### Coverage

`pytest-cov` 在本机 Python 3.14 / NumPy 组合中触发第三方模块重载错误，因此没有将失败的 pytest-cov 运行标成通过。使用 Python 标准库 `trace` 对 Phase A 的 32 个定向测试复核：新 `intelligence` 包整体 line coverage 为 **90.7%（1471/1622）**。PIT、schema、dedup、probability、event study 和 scanner 均被真实执行；没有通过 exclude 配置规避覆盖率。

### 静态与依赖检查

- Phase A 修改范围 Ruff：PASS。
- Phase A 20 个源码文件 Mypy strict：PASS。
- `pip check`：PASS。
- Alembic heads：`d5e8a4c2f710 (head)`。
- CLI parser 和新子命令帮助：PASS。
- 全仓 Ruff：未通过，原因是本阶段之前已存在的 `terminal/` 格式与 unused-import 债务；未为掩盖该事实而修改无关模块。

## 6. 已知问题与真实验证边界

1. **真实 News/Earnings/Macro 数据尚未认证。** 本阶段完成接口、版本化存储和确定性夹具验证，但没有付费/授权历史资讯档案，也未使用夹具声称真实 Alpha。
2. **PIT 历史 archive 是下一道关键门禁。** 需要保留原始发布时间、首次 observed time、article update、财报修订和宏观 revision 的可追溯数据源。
3. **Event dedup 当前是可审计的确定性聚类。** 它使用实体、规范化事件类型、时间和文本 token similarity；更复杂的 embedding 辅助可以在 Phase B 研究，但必须冻结模型版本且保持可回放。
4. **Conditional patterns 尚未 Production Approved。** OOS/walk-forward/calibration 框架已实现，但任何真实条件族仍需预注册和真实数据验证后才能提高事件贡献。
5. **Event Study 只做 session-level mapping。** 不声称精确模拟盘前/盘后盘口成交，也不把 after-hours 事件当作当日收盘前可知。
6. **成本预算依赖 Provider usage metadata。** 当前预算器可 fail closed，但真实 token/cost 账单需要各 Provider 返回可靠 usage。
7. **PostgreSQL 未在本阶段实演。** schema migration 通过 SQLite 集成测试，生产恢复与性能验证仍保持未完成。
8. **仓库可复现元数据受限。** 当前项目目录在父 Git 工作区中未被跟踪，且父仓库没有可解析的 `HEAD`；运行记录不能声称存在有效 git commit，需在正式仓库初始化/提交后关闭此项。
9. **既有全仓 Ruff 债务未清理。** 主要位于先前的 terminal 模块；不影响 Phase A 测试通过，但应进入后续工程维护。

## 7. 为 Phase B 保留的接口

- `UnifiedEvent` 与 immutable `IntelligenceRepository`：支持更多已认证 feed 与历史 replay。
- `StructuredEventExtractor`：允许接入 OpenAI/DeepSeek 的严格 JSON provider，不改变 schema/guardrail。
- `AgentResult`：允许新增 narrative/hypothesis 研究结果，但仍不能直接影响交易。
- `ConditionalDefinition` / walk-forward validation：用于预注册条件族、漂移和 calibration monitor。
- `ScannerMode`：用于 Quant-only 与 Quant-plus-event 的 OOS 增量对照。
- `OpportunityCandidate`：作为 Portfolio/Risk 下游前的研究候选合同。

## 8. 为后续 Data Stabilization 发现的数据要求

- 原始新闻、财报与宏观发布的 immutable source identifier、原始正文 hash、publish/update/observed timestamps；
- 可重建的 earnings surprise 与 estimate revision vintage；
- 宏观初值和修订值的独立版本；
- 可审计的 XNYS 日历、DST 和半日市数据来源；
- SPY/QQQ/sector ETF benchmark 映射及 point-in-time total-return series；
- Provider outage、late arrival、duplicate 和 correction 的 lineage；
- 真实 OOS 期内的 calibration 与 event-family multiple-testing registry。

## 9. 验收状态

| 项目 | 状态 |
|---|---|
| Unified Event Schema / provenance | Implemented, Tested |
| News/Earnings/Macro structured extraction | Implemented, Fixture Tested |
| Event deduplication | Implemented, Tested |
| Event Study | Implemented, Tested on deterministic data |
| Conditional Probability 2.0 | Implemented, Tested on deterministic data |
| Calibration / walk-forward | Implemented, Tested on deterministic data |
| Multi-Agent Research framework | Implemented, Tested; non-trading |
| Daily Opportunity Scanner | Implemented, Integrated, Tested |
| PIT replay / leakage guards | Implemented, Tested |
| Quant-only fallback / AI isolation | Implemented, Tested |
| Live US intelligence data validation | **Not completed** |
| Real-data OOS Alpha validation | **Blocked pending certified data** |
| Production trading approval | **Not applicable / not approved** |

Phase A 的工程验收通过；真实投资证据与 Production Alpha 门禁保持关闭。
