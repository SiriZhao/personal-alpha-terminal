# Personal Alpha Terminal

## AI-native quant intelligence (DeepSeek)

The current external LLM provider is DeepSeek through its OpenAI-compatible API.
Set `DEEPSEEK_API_KEY` only in the operating-system or process environment and set
`PAT_LLM_PROVIDER=deepseek`; the repository never stores or logs the credential.
The default structured-extraction model is `deepseek-v4-flash`, while
`deepseek-v4-pro` is registered for explicitly routed high-value reasoning tasks.
Model, base URL, timeout, retry, thinking mode, reasoning effort and feature flags
are configuration values rather than business-logic constants.

The daily chain now records an `LLM_INTELLIGENCE` stage between PIT evidence and
the downstream displayed factor chain. Structured event extraction is schema
validated, prompt/model versioned, content-hash cached and auditable by request and
response hashes, document IDs, cutoff, tokens, latency and estimated cost. External
documents are untrusted data: instructions inside filings, transcripts or news can
never alter the system prompt or create a trade.

LLM event intelligence is currently `SHADOW`. It may create PIT-safe research
features and challenger evidence, but it has zero production contribution and
cannot modify Alpha, statistical probability, target weights or recommendations.
The classical Quant Core remains the safe fallback whenever DeepSeek, a schema, a
budget, or certified text data is unavailable. Promotion requires certified market
and historical text data, 252+ locked-OOS sessions, calibration, ablation and
after-cost incremental alpha. Current historical data remains `NOT_CERTIFIABLE`, so
no LLM factor is `PRODUCTION_APPROVED`.

Install the declared provider client with:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ai]"
```

No LLM selects securities, invents a probability, changes risk limits, confirms a
trade or sends an order. Explanations may only restate structured Quant evidence.

个人使用、中低频、美股、long-only、每日运行一次的专业量化决策终端。系统只生成经门禁批准的操作建议和外部券商手工执行计划，不连接券商自动下单，不使用 AI/LLM 选股，也不构成投资建议。

## 唯一正式流程

程序只有一套业务流程：

`CALENDAR → DATA → PIT → FEATURE → FACTOR → ALPHA CANDIDATE → SIGNAL → PORTFOLIO → RISK → DECISION → EXECUTION PLAN → PERSISTENCE`

候选不等于信号，信号不等于批准信号，批准信号也必须通过组合与风险门禁才能成为操作建议。任何未来数据、数据认证、策略认证、组合或风险失败都会 fail closed，最终输出 `NO_ACTION / BLOCKED`，不会为了产生 BUY/SELL 降低标准。

系统只有一个用户维护的正式组合，默认外部标识为 `main`。券商账户属于外部执行环境；程序内部不设置第二套交易模式。测试只能使用隔离的 `TEST_FIXTURE` 数据库，不能进入正式账户或批准注册表。

## 报告与文档生命周期

- 普通修改只通过 Git commit 记录，不为每次改动生成新的 FINAL/CLOSURE 报告。
- 当前真相来源仅限 `README.md`、`ARCHITECTURE.md`、`REPOSITORY_GUIDE.md`、
  `TECH_DEBT.md` 与仍有效的规范文档。
- 审计记录统一进入 `docs/audits/YYYY-MM-DD_<topic>.md`。
- 已被取代的会话报告归档到 `docs/history/YYYY-MM-DD-<phase>/` 并登记
  `docs/history/INDEX.md`。
- daily-run 等自动产物进入 `reports/` / `var/`，用
  `python main.py maintenance artifacts status` 与
  `python main.py maintenance artifacts cleanup --dry-run|--commit` 管理，绝不进入 docs。

## 初始化与维护组合

现金和持仓从不推测。首次初始化一个可审计的纯现金组合：

```powershell
python main.py portfolio-init --portfolio-id main --cash 100000 --currency USD
python main.py portfolio-show --portfolio-id main
python main.py portfolio-list
```

初始化现金会同时写入不可变 `deposit` 账本事件。可在初始化时录入持仓：

```powershell
python main.py portfolio-init --portfolio-id main --cash 50000 --position "AAPL=10:180" --position "MSFT=5"
```

手工更新一个日期的持仓快照：

```powershell
python main.py portfolio-update --portfolio-id main --as-of 2026-08-11 --cash 75000 --position "AAPL=10:180"
```

Charles Schwab 或通用 CSV 先预览、再显式提交：

```powershell
python main.py portfolio-import schwab.csv --portfolio-id main --as-of 2026-08-11
python main.py portfolio-import schwab.csv --portfolio-id main --as-of 2026-08-11 --commit --cash 25000
```

`config.yaml` 使用稳定的外部组合标识：

```yaml
portfolio_id: main
```

## 每日工作流与中文终端

默认 `zh-CN`；英文仅改变展示，不改变同一个不可变结果：

```powershell
python main.py daily
python main.py --locale zh-CN daily
python main.py --locale en-US daily
python main.py doctor
```

第一屏先回答今天能否操作、操作什么、为何阻塞；随后依次展示组合、同起点基准/前向记录、数据认证、PIT 股票池、因子候选、条件概率、风险、执行计划、阻塞优先级和运行证书。终端宽度不足时表格自动折行；文本图以数字为准，并兼容 Windows Terminal、PowerShell 和 CMD 的旧代码页。

## 人工确认与实际成交同步

只有运行证书中真实存在的正式 recommendation 才能确认：

```powershell
python main.py accept <recommendation-id> --run-id <run-id> --reason "manual review"
python main.py reject <recommendation-id> --run-id <run-id> --reason "operator veto"
python main.py watch <recommendation-id> --run-id <run-id> --reason "observe"
```

接受只创建待人工执行记录，不改变持仓。用户在 Charles Schwab 或其他外部券商手工成交后再同步真实 fill：

```powershell
python main.py mark-executed <recommendation-id> --run-id <run-id> --price 190.25 --quantity 5 --fees 0.50 --timestamp 2026-08-12T14:31:00+00:00 --fill-id schwab-fill-001
```

成交必须不早于 T 日收盘决策后的下一个合法 XNYS 执行窗口。数量、现金、持仓、费用和重复 fill ID 均有 fail-closed 校验。

## 数据、PIT 与研究认证

Yahoo Finance 是当前 daily 主 provider；Twelve Data、Alpha Vantage、Stooq 是可选适配器。每次运行保存 cutoff、snapshot/version、provider、覆盖率、质量状态、content hash 和 certification state。SPY/QQQ 与策略使用相同 completed-session PIT convention。

`LIVE_DAILY_DATA` 与历史研究数据严格隔离。当前 ticker list 不得倒填历史，今天下载的最终 adjusted series 不能冒充历史 PIT total-return vintage。研究导入独立运行：

```powershell
python main.py research-data providers
python main.py research-data audit
python main.py research-data acquire
python main.py research-data status
python main.py research-data import <csv-parquet-or-sqlite>
python main.py research-data certify
python main.py research-data manifest
```

`providers` 展示基于官方文档审计的 capability/license matrix；`acquire` 只盘点并哈希当前合法可得的数据层，不会自动购买数据、抓取多年历史或把 current directory 升级成 historical membership。大规模 raw import、checkpoint、cache、SQLite/Parquet 数据均保存在 Git ignored research storage；Git 只保存 schema、代码、小型 fixture 与机器 manifest。

当前研究数据仍为 `NOT_CERTIFIABLE`：缺历史 membership、delisting、identifier history、PIT corporate actions、PIT total-return 和绑定数据集的完整 calendar。`USAdaptiveAlphaCoreV1:1.0.0` 因此保持 `DIAGNOSTIC_ONLY`，生产批准注册表为空。前向实际运行记录可以积累真实证据，但不替代 survivorship-safe 历史 locked OOS / walk-forward / after-cost 认证。

## Probability、Regime 与风险

条件概率没有足够 OOS 样本时显示“未校准 / 样本不足”，不输出假置信度，也不修改 deterministic alpha。Market Regime 当前为 optional unavailable，不阻塞核心数据/因子分析。正式信号存在时，组合构建继续检查波动率、敞口、现金、最大持仓、换手、HHI、流动性、相关性、压力与回撤；缺合法 signal 时明确显示由 SIGNAL 阻塞，而不是伪造风险结果。

## Evidence、配置和测试

运行证据写入 `reports/daily-runs/<run_id>/`，包含 stage manifests、run certificate、data/config/strategy/parameter/portfolio identities、成本假设、blockers 与 canonical hashes。数据库、运行报告、cache、`.env`、凭证和个人交易数据均由 Git 忽略。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\mypy.exe src/personal_alpha_terminal --strict
.\.venv\Scripts\pytest.exe -q
```

## Broad US Equity Universe 与 Probability Overlay

正式 Alpha 股票池不再由 18 个 bootstrap symbol 定义。Daily run 先读取 Nasdaq Trader 当前上市目录，再依次执行证券类型、PIT 可见性、价格历史、数据覆盖、公司行动完整性、t-1 ADV/median dollar volume 与特征可用性门禁。ETF、指数和 benchmark 不参与普通股横截面排名；SPY/QQQ 只用于同 PIT 基准，其他 ETF 只可作为风险参考或现有持仓。

当前目录只证明“当时可见的 current listings”，不能倒填历史或证明 survivorship-safe。若历史 membership、delisting、identifier history、PIT corporate actions 或 PIT total-return vintages 不完整，历史认证继续 `NOT_CERTIFIABLE`。股票数量永远服从数据正确性；当前真实 factor-eligible 数量由运行证书动态给出，不以配置硬编码。

Probability Overlay 已有正式 consumer 链：Base expected excess return → gated residual overlay → portfolio expected returns → target weight → recommendation。但只有 exact-version、locked-OOS、walk-forward、after-cost、multiple-testing-controlled 且 calibration 合格的 `PRODUCTION_APPROVED` artifact 才能改变结果。artifact 缺失、未批准、失配或退化时安全回退 Base Alpha，不会阻塞 deterministic core，也不会伪造概率。

最新机器证书：

- `artifacts/latest/universe_certification.json`
- `artifacts/latest/probability_overlay_certification.json`
- `artifacts/latest/historical_research_baseline.json`
- `artifacts/latest/historical_data_acquisition.json`

它们由以下命令从真实 daily run/config/cache 派生并计算 hash：

```powershell
python scripts/export_broad_universe_probability_certifications.py --config config.yaml
python scripts/export_historical_data_acquisition.py --config config.yaml
```

详细审计见 [Broad Universe 与 Probability Overlay 报告](docs/BROAD_UNIVERSE_PROBABILITY_OVERLAY_REPORT.md)。

更多资料：[统一主链收口报告](docs/UNIFIED_LIVE_CLOSURE_REPORT.md)、[中文终端架构](docs/CHINESE_TERMINAL_ARCHITECTURE.md)、[历史数据基础报告](docs/RESEARCH_DATA_FOUNDATION_REPORT.md)、[历史数据获取与认证报告](docs/HISTORICAL_DATA_ACQUISITION_REPORT.md)、[Provider 决策](docs/DATA_PROVIDER_DECISION.md)、[Alpha 研究认证报告](docs/ALPHA_RESEARCH_CERTIFICATION_REPORT.md)。
