# Personal Alpha Terminal

个人使用、中低频、美股、long-only、每日运行一次的专业量化决策终端。系统只生成经门禁批准的操作建议和外部券商手工执行计划，不连接券商自动下单，不使用 AI/LLM 选股，也不构成投资建议。

## 唯一正式流程

程序只有一套业务流程：

`CALENDAR → DATA → PIT → FEATURE → FACTOR → ALPHA CANDIDATE → SIGNAL → PORTFOLIO → RISK → DECISION → EXECUTION PLAN → PERSISTENCE`

候选不等于信号，信号不等于批准信号，批准信号也必须通过组合与风险门禁才能成为操作建议。任何未来数据、数据认证、策略认证、组合或风险失败都会 fail closed，最终输出 `NO_ACTION / BLOCKED`，不会为了产生 BUY/SELL 降低标准。

系统只有一个用户维护的正式组合，默认外部标识为 `main`。券商账户属于外部执行环境；程序内部不设置第二套交易模式。测试只能使用隔离的 `TEST_FIXTURE` 数据库，不能进入正式账户或批准注册表。

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
python main.py research-data audit
python main.py research-data status
python main.py research-data import <csv-parquet-or-sqlite>
python main.py research-data certify
python main.py research-data manifest
```

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

更多资料：[统一主链收口报告](docs/UNIFIED_LIVE_CLOSURE_REPORT.md)、[中文终端架构](docs/CHINESE_TERMINAL_ARCHITECTURE.md)、[历史数据基础报告](docs/RESEARCH_DATA_FOUNDATION_REPORT.md)、[Alpha 研究认证报告](docs/ALPHA_RESEARCH_CERTIFICATION_REPORT.md)。
