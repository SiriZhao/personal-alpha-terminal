# Personal Alpha Terminal 中文用户指南

## A. 系统定位

Personal Alpha Terminal 是一个个人使用、美股、long-only、中低频、每日运行一次的量化决策终端。

系统只做一件事：

1. 用已完成交易日的数据形成下一交易时段的人工执行建议。
2. 把所有数据、PIT、风险、策略、执行门禁透明显示出来。
3. 由你本人到 Charles Schwab 手动下单，并把真实成交同步回系统。

系统不会自动下单，不连接 Broker API，不使用 AI 直接选股，也不允许 LLM 直接输出 BUY/SELL 控制组合。LLM 当前只能是 SHADOW research。

## B. 安装

要求：

- Windows 10/11
- Git
- Python 3.12 到 3.14

推荐把项目克隆到固定路径，例如：

```powershell
git clone <仓库地址> E:\CSDIY\Vibe Coding Project\personal-alpha-terminal
cd E:\CSDIY\Vibe Coding Project\personal-alpha-terminal
```

## C. Python 与 .venv

项目当前统一使用 `.venv`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ai]"
```

安装后确认：

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe main.py doctor
```

不要混用 `.venv` 和 `.venv` 跑正式流程；如果旧环境仍存在，只作为历史参考。

## D. 首次初始化

先确认配置：

```powershell
.\.venv\Scripts\python.exe main.py settings
```

初始化一个可审计的纯现金组合：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-init --portfolio-id main --cash 100000 --currency USD
```

查看组合：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-list
.\.venv\Scripts\python.exe main.py portfolio-show
```

如果已有真实持仓，可以在初始化时录入：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-init --portfolio-id main --cash 50000 --position "AAPL=10:180" --position "MSFT=5"
```

系统只维护一个正式组合，默认标识为 `main`。不要创建 paper 模式，不要模拟持仓进入正式 ledger。

## E. DeepSeek API 配置

DeepSeek 是可选 LLM provider，用于 SEC/PIT 文本特征研究。它不参与生产组合。

推荐在用户环境变量中设置：

```text
PAT_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<你的密钥>
```

不要把 Key 写入源码、config.yaml、docs 或任何 Git 跟踪文件。

检查方式只显示 PRESENT/MISSING，不输出密钥：

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py llm status
.\.venv\Scripts\python.exe main.py llm test
```

`llm test` 会发起一次真实最小请求，只用于确认连通性。

## F. SEC_EDGAR_USER_AGENT 配置

SEC EDGAR 要求合法 User-Agent 标识请求来源。

在用户环境变量中设置：

```text
SEC_EDGAR_USER_AGENT=YourName your-email@example.com
```

检查：

```powershell
.\.venv\Scripts\python.exe main.py doctor
```

doctor 只显示 `PRESENT` 或 `MISSING`，不会输出实际值。不要把 User-Agent 写入源码。

## G. OperationalPolicy

OperationalPolicy 是“在历史研究认证不足时，是否允许生成降级生产建议”的显式门禁。

代码、配置、组合配置或策略身份变化后，旧 policy 会因 `code_config_fingerprint` / `portfolio_config_hash` 变化而失效。这是预期行为，不是 bug。

检查：

```powershell
.\.venv\Scripts\python.exe main.py operational-policy status
```

如果看到：

```text
Status: IDENTITY_MISMATCH
Effective: false
```

说明当前 policy 不生效，系统保持 fail-closed，不会生成正式 actionable live acceptance。

重新授权必须由你本人显式执行：

```powershell
.\.venv\Scripts\python.exe main.py operational-policy create --decision ALLOW_PROVISIONAL
```

该命令会要求输入确认，不会在无人值守时自动签发。普通研究、诊断和每日 no-action 不需要 policy 也能运行。

## H. 每日运行时间

系统使用美股已完成交易日收盘数据，即 PIT completed-session convention。

不要用“今天盘中实时价格”作为历史因子；不要用“今天下载的最新调整序列”倒填历史。

推荐流程：

1. 等待美股当日交易时段结束。
2. 盘后等待 provider 数据稳定，避免使用不完整或未认证 bar。
3. 运行 daily。

具体时钟由系统 XNYS calendar 与 PIT 检查决定。不要只依赖固定墙钟时间。通常美东收盘后、北京时间晚上/次日凌晨，只要数据稳定且 doctor 的 timezone/calendar 检查通过，即可运行。

```powershell
.\.venv\Scripts\python.exe main.py --no-refresh daily
```

需要刷新市场数据时：

```powershell
.\.venv\Scripts\python.exe main.py refresh
```

最终是否生成可执行建议取决于 DATA/PIT/SIGNAL/PORTFOLIO/RISK/DECISION/EXECUTION 门禁，不取决于运行时间是否“看起来像”。

## I. 每日操作流程

标准流程：

1. 检查环境：

```powershell
.\.venv\Scripts\python.exe main.py doctor
```

2. 更新数据并运行 daily：

```powershell
.\.venv\Scripts\python.exe main.py refresh
```

或只使用缓存/已完成数据：

```powershell
.\.venv\Scripts\python.exe main.py --no-refresh daily
```

3. 阅读 gate：

```text
DATA PASS
PIT PASS
FEATURE PASS
FACTOR PASS
SIGNAL PASS_PROVISIONAL 或 PASS_PRODUCTION
PORTFOLIO PASS
RISK PASS 或 PASS_DEGRADED
DECISION PASS
EXECUTION_PLAN PASS
```

任何 BLOCKED 都必须先理解原因，不得忽略。

4. 阅读操作清单：

首屏会回答：

- 今天要不要操作？
- 买什么、卖什么？
- 目标权重是多少？
- 预计金额和大约数量？
- 为什么？
- 最早什么时候执行？
- 哪些 gate degraded？
- LLM 是否参与？
- Probability 是否参与？

5. 手动到 Charles Schwab 下单。

系统只生成执行计划，不提交订单。

6. 真实成交后同步持仓：

```powershell
.\.venv\Scripts\python.exe main.py mark-executed <recommendation-id> --run-id <run-id> --price 190.25 --quantity 5 --fees 0.50 --timestamp 2026-08-14T14:31:00+00:00 --fill-id schwab-fill-001
```

## J. 持仓更新

持仓更新是最重要的一步。真实成交必须真实录入，不得推测。

新增成交：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-update --portfolio-id main --as-of 2026-08-14 --cash 25000 --position "AAPL=10:190.25"
```

更新数量、价格、手续费：

- 数量写在 `=` 前。
- 价格写在冒号后，例如 `AAPL=10:190.25`。
- 手续费通过 `mark-executed` 的 `--fees` 录入。

部分成交：

```powershell
.\.venv\Scripts\python.exe main.py mark-executed <recommendation-id> --run-id <run-id> --price 190.25 --quantity 2 --fees 0.20 --timestamp 2026-08-14T14:31:00+00:00 --fill-id schwab-partial-001
```

卖出或减仓：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-update --portfolio-id main --as-of 2026-08-15 --cash 30000 --position "AAPL=8:191.00"
```

现金：

现金余额必须与真实券商账户同步。不要凭空改现金。

撤销错误：

系统是 append-only ledger。不要直接编辑 ledger 文件。发现错误时，用新的真实日期/成交记录纠正，并保留原始记录。

查看 ledger：

```powershell
.\.venv\Scripts\python.exe main.py portfolio-list
.\.venv\Scripts\python.exe main.py portfolio-show
.\.venv\Scripts\python.exe main.py forward-track --help
```

验证 ledger：

```powershell
.\.venv\Scripts\python.exe main.py doctor
```

doctor 会检查组合、数据库、迁移和 runtime 一致性。

## K. LLM 配置

DeepSeek 通过 OpenAI-compatible API 接入。

常用命令：

```powershell
.\.venv\Scripts\python.exe main.py llm status
.\.venv\Scripts\python.exe main.py llm test
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py intelligence status
```

SEC acquisition：

```powershell
.\.venv\Scripts\python.exe main.py intelligence acquire --cik 320193 --max-documents 20
```

历史 backfill：

```powershell
.\.venv\Scripts\python.exe main.py intelligence backfill --cik 320193 --max-documents 20
```

真实处理：

```powershell
.\.venv\Scripts\python.exe main.py intelligence process --max-documents 10
```

LLM cache 由 raw content hash、model、prompt version 决定。重复处理相同原始文档会命中缓存，不会伪造新的 LLM call。

成本：

```powershell
.\.venv\Scripts\python.exe main.py intelligence status
```

status 会显示 estimated API cost。当前 LLM production influence 必须是 `NONE`。

## L. Probability

条件概率表示“在给定条件下，未来 benchmark-relative 结果发生的概率”，不是 arbitrary confidence score。

- `P(cond)` 是条件概率估计。
- calibration 检查预测概率和实际频率是否一致。
- production influence 表示概率是否实际改变 Alpha 或目标权重。
- fallback 表示当前没有合格生产概率，使用 Classical fallback。
- `N/A` 表示 unavailable / not calibrated。
- `0%` 表示明确的零概率或零权重，不能把两者混为一谈。

当前正确状态：

```text
PROBABILITY_FALLBACK_CLASSICAL
production influence = 0
```

即使概率研究未通过，也不算工程失败；强行让概率参与组合才是错误。

## M. AI / PIT

- Raw SEC：SEC EDGAR 获取的原始文档，带 raw hash。
- PIT-certified：已确认 SEC acceptance timestamp，且 available_at 正确。
- issuer mapping：CIK 解析到 issuer identity。
- security mapping：issuer 在 PIT cutoff 下解析到 security/ticker。
- LLM calls：真实 DeepSeek 请求次数。
- events：从 SEC 文档提取的结构化事件。
- quarantine：证据不完整、evidence span 不匹配或疑似幻觉的事件。
- SHADOW feature：只用于研究，不改变生产组合。
- Production influence：当前必须为 `NONE`。

常用：

```powershell
.\.venv\Scripts\python.exe main.py intelligence status
.\.venv\Scripts\python.exe main.py intelligence audit
.\.venv\Scripts\python.exe main.py intelligence outcomes
.\.venv\Scripts\python.exe main.py intelligence alpha-research
.\.venv\Scripts\python.exe main.py intelligence probability-research
```

## N. Portfolio / Risk

- candidate pool：进入组合优化前的候选池。
- optimizer input：优化器实际看到的证券数量。
- maximum holdings：最大允许持仓数量，当前 canonical 为 10。
- gross exposure：总多头敞口。
- turnover：换手率。
- volatility：组合波动率。
- HHI：持仓集中度。
- size exposure：市值暴露诊断。

风险门禁不是装饰。任何 DATA、PIT、SIGNAL、PORTFOLIO、RISK 失败都会 fail closed。

## O. 故障排查

### DATA FAIL

检查：

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py data
```

确认 provider 是否可用、缓存是否过期、是否 coverage collapse。

### PIT FAIL

说明存在未来数据、时间戳、corporate action 或 completed-session 问题。不要用当前 ticker 列表倒填历史。

### POLICY mismatch

```powershell
.\.venv\Scripts\python.exe main.py operational-policy status
```

看到 `IDENTITY_MISMATCH` 后，由你本人显式重新授权。

### LLM unavailable

系统仍可运行 Classical Quant。LLM 失败不会阻塞量化核心。

### Probability fallback

属于合法状态。`N/A` 表示没有合格概率，不等于 0%。

### SEC unavailable

检查 `SEC_EDGAR_USER_AGENT` 是否 PRESENT，再运行：

```powershell
.\.venv\Scripts\python.exe main.py doctor
```

### missing dependency

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ai]"
```

### quarantine

被隔离事件不能进入 accepted evidence。不要为了计数删除隔离。

### no action

没有操作不一定是故障。如果所有门禁通过但无需调仓，系统会显示 `NO_ACTION / NO_TRADE`。

## 最终原则

数据正确性 > 无未来函数 > 策略有效性 > 风险控制 > 可复现性 > 稳定性 > 用户体验。

任何让回测“好看”而降低 PIT、成本、统计或风控标准的改动都是错误的。