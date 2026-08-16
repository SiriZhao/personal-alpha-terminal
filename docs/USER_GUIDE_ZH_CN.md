# Personal Alpha Terminal 中文使用教程

> 版本基准：v1.1.0（SHADOW_ONLY，fail-closed）
> 适用对象：系统实际使用者（个人用户）
> 文档性质：正式产品教程，不是开发日志

---

## 第 0 章 这个系统到底是什么

**Personal Alpha Terminal 是一个「个人中低频美股专业量化决策终端」。**

先说清楚它**不是什么**：

- ❌ 不是 AI 推荐股票的软件（没有「AI 选股」功能）
- ❌ 不是自动交易系统（**系统里没有任何券商 API，永远不可能自动下单**）
- ❌ 不是高频交易系统（策略周期以周为单位，中低频）
- ❌ 不是券商机器人（下单永远是你在 Charles Schwab 手工完成）

它的完整逻辑链条是：

```text
原始市场数据（Raw Market Data）
  → 时点清洗数据（Point-in-Time Clean Data）
  → 特征（Feature：动量 / 趋势斜率 / 低波动）
  → 因子（Factor：截面标准化与中性化）
  → 信号（Alpha Signal：模型批准的候选）
  → 概率（Probability：仅作支持证据，未校准时不显示）
  → 组合构建（Portfolio Construction：真实持仓 + 约束优化）
  → 风险引擎（Risk Engine：相关性 / 压力 / 集中度 / 波动）
  → 最终决策（Decision：BUY / SELL / REDUCE / NO ACTION）
  → 手工执行清单（Manual Execution Plan）
  → 由你人工审核、人工决定、人工在 Charles Schwab 下单
```

系统的核心哲学叫 **fail-closed（宁缺毋滥）**：

> 任何一个环节的证据不足——数据认证失败、时点证据缺失、组合未初始化、
> 模型未批准、风险检查不通过——系统都会选择「不给交易结论」，
> 而不是「猜一个结论」。

所以你会经常看到 BLOCKED / NOT_ACTIONABLE / NO_ACTION。
**这些不是故障，而是系统在正确地工作。**

---

## 第 1 章 5 分钟快速开始

> 只想马上用起来？读这一章就够了。细节在后面各章。

### 1.1 启动

- **发布版（有 PersonalAlphaTerminal.exe）**：双击 `PersonalAlphaTerminal.exe`，
  它默认执行 `daily` 命令（刷新数据 + 跑完整链路 + 渲染终端）。
- **开发环境**：在项目目录下运行
  ```powershell
  .\.venv\Scripts\python.exe main.py
  ```
  或者双击 `run_terminal.bat`。

### 1.2 第一次看到 PORTFOLIO NOT_INITIALIZED

第一次启动时，你会看到组合状态是 `NOT_INITIALIZED`，
并且 `TRADING BLOCKED`。这是**正常的、正确的**：

- 系统不知道你的真实持仓，就不会编造一个持仓来算交易；
- 研究链（数据 → 信号）照常运行并显示，但正式交易决策被锁定。

### 1.3 初始化你的真实组合（一次性）

在终端（命令行）里运行：

```powershell
# 交互式向导（推荐，会一步步问你）
PersonalAlphaTerminal.exe portfolio-init

# 或一行命令（示例数字仅为教学，不是投资建议）
PersonalAlphaTerminal.exe portfolio-init --name "My Portfolio" --cash 50000 --position AAPL=10:150.25 --position SPY=5:450.00
```

交互向导会依次询问：组合名称 → 现金余额（USD）→ 逐个持仓
（格式 `TICKER=股数[:成本价]`，空行结束）→ 确认保存（y/N）。
任何一步输入 `cancel` 都会安全退出，不保存任何内容。

### 1.4 每天运行分析

```powershell
PersonalAlphaTerminal.exe daily
```

运行结束后，按顺序看三处：

1. 顶部状态行：`DATA READY  QUANT ANALYSIS READY  PORTFOLIO READY  RISK ...  TRADING ...`
2. `FINAL VALIDATED DECISIONS` 区块：这是**唯一**的正式交易输出区域。
3. `EXECUTION PLAN` 区块：如果可交易，这里给出手工执行清单。

### 1.5 什么时候不能交易

以下任一情况，**绝对不要交易**：

- 状态行出现 `TRADING BLOCKED`
- 分类显示 `VALID QUANT ANALYSIS / NON-ACTIONABLE` 或 `INVALID / NON-ACTIONABLE`
- 决策表显示 `NO_ACTION`（无调仓）或 `NOT_ACTIONABLE`（证据不足）
- DATA / PIT / RISK 任何一项不是 PASS

### 1.6 交易后同步持仓

在 Schwab 手工下单并成交后，系统**不会自动知道**。你必须手工同步：

```powershell
# 对系统内已接受的建议录入成交（fill-id 必须唯一）
PersonalAlphaTerminal.exe mark-executed <recommendation_id> --run-id <run_id> --price 100 --quantity 10 --fees 0 --fill-id schwab-001

# 或者用新的 CSV 重新导入整份持仓
PersonalAlphaTerminal.exe portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --commit
```

---

## 第 2 章 每天的标准使用流程

### 2.1 什么时候运行

| 时间 | 建议 |
|---|---|
| 美东收盘后（北京次日凌晨 5 点后，夏令时 4 点后） | **最佳**：最新一根日 bar 已完整 |
| 盘中 | 可以运行，但当天 bar 未收盘，分析基于截止到 PIT cutoff 的数据 |
| 周末 / 美国节假日 | 可以运行，系统自动使用最近一个已完成交易日的数据 |

### 2.2 三个关键日期概念

终端头部会显示三个日期，理解它们是正确使用系统的关键：

| 名称 | 含义 | 举例（周日运行） |
|---|---|---|
| **Latest Completed Session** | 最近一个已收盘的美股交易日 | 周五 2026-08-07 |
| **Analysis Date** | 本次分析所用的数据日期 = 最近已完成交易日 | 2026-08-07 |
| **Trade Date** | 下一个可执行交易的交易日 | 周一 2026-08-10 |

**为什么周日运行看到周五数据是正常的？**
因为周六、周日美股不开盘，没有新数据。系统的规则是
「永远只用最近一个已完成交易日的收盘数据」——这叫
**Point-in-Time（时点）正确性**。如果系统给你看「今天的预测数据」，
而今天根本没有交易，那才是 bug。

**Trade Date = 2026-08-10** 的意思是：如果最终决策给出 BUY/SELL，
你最早可以在周一开盘后手工执行，而不是周日。

### 2.3 标准每日步骤

**Step 1 — 启动**
双击 exe 或运行 `main.py`。等待数据刷新与链路计算（通常几十秒到几分钟）。

**Step 2 — 读状态行**
看 HEADER 里的分类与分层状态行（详见第 4 章）。
确认 `DATA READY` 与 `QUANT ANALYSIS READY`。

**Step 3 — 检查 PIPELINE**
PIPELINE 表列出全部 12 个阶段。正常情况：
CALENDAR / DATA / PIT / FEATURE / FACTOR / SIGNAL 全绿（PASS），
PROBABILITY 黄色（PASS_DEGRADED，见第 11 章），
PORTFOLIO / RISK / DECISION / EXECUTION 视组合与证据而定。

**Step 4 — 看 DATA CERTIFICATION**
确认：certified symbols = requested、Future rows = 0、
PIT integrity = PASS、duplicates = 0、invalid OHLC = 0。
任何一项异常都不要继续交易（见第 18 章故障排查）。

**Step 5 — 浏览 FACTOR / ALPHA（只看，不交易）**
Candidate 排名是诊断信息，**不是买入建议**（见第 9 章）。

**Step 6 — 读 RISK EVIDENCE**
看相关性、压力、集中度是否触发限制。Risk BLOCKED 时决策不会产生。

**Step 7 — 读 FINAL VALIDATED DECISIONS**
这是唯一正式区域。可能是：
- 若干 BUY / SELL / INCREASE / REDUCE 行 → 进入 Step 8；
- `NO_ACTION` → 今天没有通过 no-trade 规则的调仓，正常，什么都不做；
- `NOT_ACTIONABLE` → 证据不足，什么都不做。

**Step 8 — 读 EXECUTION PLAN**
若可交易，清单给出 Ticker / Action / Est Value / Qty / Est Cost / Earliest 时间。
**这只是计划，下单永远由你在 Schwab 手工完成。**

**Step 9 — 人工确认与记录**
对每条建议用 `accept` / `reject` / `watch` 记录你的审阅结论（见第 7 章）。

**Step 10 — 手工下单与同步**
在 Charles Schwab 手工下单；成交后用 `mark-executed` 录入成交，
或用 `portfolio-import --commit` 更新整份持仓（见第 6 章）。

### 2.4 什么情况下应该交易 / 绝对不要交易

**可以考虑执行（仍需你人工判断）**：
- 分类为 `ACTIONABLE TRADING PLAN · MANUAL EXECUTION ONLY`
- DATA / PIT / RISK 全部 PASS
- FINAL VALIDATED DECISIONS 有具体行，且 EXECUTION PLAN 给出清单

**绝对不要交易**：
- `TRADING BLOCKED` 或任何 BLOCKED 阶段
- Future rows > 0 或 PIT integrity 不是 PASS
- 组合未初始化（NOT_INITIALIZED）
- 你看不懂当前结果时——宁可不动

---

## 第 3 章 首次使用详细教程

### 3.1 程序在哪里、如何启动

| 形态 | 启动方式 |
|---|---|
| Windows 发布版 | 双击 `PersonalAlphaTerminal.exe`（等价于 `daily` 命令） |
| 开发检出（有 .venv） | 双击 `run_terminal.bat`，或运行 `.\.venv\Scripts\python.exe main.py` |
| 指定子命令 | `PersonalAlphaTerminal.exe <命令>`（命令清单见 CLI_REFERENCE_ZH_CN.md） |

程序入口是纯终端界面（不是浏览器、不是 GUI 窗口）。
Windows 下双击 exe 或 bat 后，窗口运行完毕会停在 `pause` 等待你按键，
所以不会「闪退」——如果窗口立刻消失，见第 18 章故障排查。

### 3.2 启动后的界面长什么样

一次完整的 `daily` 运行会自上而下渲染这些区块（顺序固定）：

1. HEADER（分类 + 版本 + Run ID + 三个日期 + 分层状态行）
2. PIPELINE · FAIL CLOSED（12 阶段状态表）
3. DATA CERTIFICATION（数据认证证据）
4. REJECTED DATA（如有被拒绝的数据）
5. PIT / UNIVERSE（时点 / 研究域）
6. DATA HEALTH · STRATEGY INPUTS ONLY（逐标的健康度）
7. MARKET REGIME（市场状态，可选覆盖层）
8. REAL PORTFOLIO · MANUAL LEDGER（真实组合）
9. FACTOR / ALPHA · CANDIDATE ≠ TRADE（因子与候选）
10. CONDITIONAL PROBABILITY · SUPPORTING EVIDENCE ONLY（条件概率）
11. RISK EVIDENCE / RISK · RAW TARGET → RISK-ADJUSTED TARGET（风险）
12. FINAL VALIDATED DECISIONS · ONLY FORMAL BUY/SELL AREA（正式决策）
13. REJECTED SIGNALS / GATE BLOCKERS（被拒信号与闸门原因）
14. EXECUTION PLAN（手工执行清单）
15. BENCHMARK · SAME PIT DATA CONVENTION AS STRATEGY（基准 SPY / QQQ）
16. RUN CERTIFICATE（运行证书：Run ID 与各类哈希）
17. TODAY SUMMARY（当日总结）

第一次使用，先看三处：**HEADER 的分类**、**PIPELINE 表**、**REAL PORTFOLIO**。

### 3.3 PORTFOLIO NOT_INITIALIZED 是什么意思

REAL PORTFOLIO 区块显示 `Status NOT_INITIALIZED` 时，表示
**数据库里还没有任何真实组合账本**。此时：

- 研究链（DATA → SIGNAL）正常运行，你可以看因子、候选、数据健康度；
- 但 PORTFOLIO 阶段显示 FAIL_BLOCKING，RISK / DECISION / EXECUTION 显示 NOT_RUN；
- 正式交易决策被锁定，TRADING BLOCKED。

这是 fail-closed 的正确表现。解决办法：运行 `portfolio-init` 或
`portfolio-import`（见下两节）。

### 3.4 portfolio-init：交互式初始化（逐步教学）

运行：

```powershell
PersonalAlphaTerminal.exe portfolio-init
```

向导流程（每一步都可以输入 `cancel` 安全退出）：

**Step 1 — 组合名称**

```text
Portfolio name [My Portfolio]:
```

直接回车使用默认名 `My Portfolio`，或输入你自己的名称（不能为空）。

**Step 2 — 现金余额**

```text
Cash balance (USD):
```

输入你 Schwab 账户里的现金金额，例如 `25000`。
要求：≥ 0、有限数字、不能是 NaN/inf。输错会提示重新输入。

**Step 3 — 持仓录入**

```text
Enter positions as TICKER=SHARES[:AVERAGE_COST], one per line.
Average cost is optional. Press Enter on an empty line when done.
Position 1 (blank line to finish):
```

每行格式：`代码=股数[:成本价]`，例如：

```text
AAPL=10:150.25
MSFT=5
SPY=2:450.10
```

- `AAPL=10:150.25`：10 股 AAPL，平均成本 150.25（成本可选）
- `MSFT=5`：5 股 MSFT，不录成本
- 输完按空行结束

校验规则：代码非空且格式合法（支持 `^VIX` 这类指数代码）、
股数必须为正数（不能为负、不能为 0，也不支持做空）、不能 NaN/Inf、
同一代码不能重复。

**Step 4 — 确认**

向导显示汇总表，然后问：

```text
Save this portfolio? [y/N]:
```

输入 `y` 保存（整个写入是原子事务，要么全部保存，要么完全不保存）；
其他任何输入都取消，不保存任何内容。

保存成功后显示 `Created portfolio id=1; broker connection: NONE`。
`broker connection: NONE` 是系统的设计承诺：永远没有券商连接。

**⚠️ 教学声明**：本教程中出现的所有金额、股数、成本价（如 25000、
AAPL=10:150.25）都**只是格式示例**，不代表任何投资建议。

### 3.5 portfolio-init：一行命令（非交互）

如果你在脚本里使用，或设置了 `PAT_NONINTERACTIVE=1`，用参数方式：

```powershell
PersonalAlphaTerminal.exe portfolio-init --name "My Portfolio" --cash 25000 --position AAPL=10:150.25 --position SPY=5
```

参数：
- `--name`：组合名称（默认 `My Portfolio`）
- `--cash`：现金余额（**必填**，否则非交互模式报错）
- `--currency`：货币（默认 USD）
- `--position`：`TICKER=SHARES[:AVERAGE_COST]`，可重复多次

注意：交互式向导**只在**终端可交互、未设 `PAT_NONINTERACTIVE=1`、
且没有传 `--cash` 时触发。

---

## 第 4 章 portfolio-import：从 CSV 导入持仓

### 4.1 什么时候用 import

- 你的持仓比较多，逐行输入麻烦；
- 你已经有一份整理好的持仓清单；
- 你想定期用「整份替换」的方式同步持仓（见第 6 章）。

### 4.2 CSV 格式要求

**编码**：UTF-8（推荐带 BOM 或不带都可以）。
**表头**：`ticker,shares`（也兼容 `symbol,quantity` 表头）。
**可选列**：`average_cost`（平均成本）、`cost_basis`（成本基础）。

示例文件（`my_holdings.csv`）：

```csv
ticker,shares,average_cost
AAPL,10,150.25
MSFT,5,320.00
SPY,2,450.10
```

仓库里提供了一份示例模板：`docs/user-guide/portfolio_import_template.csv`。
**注意：模板只是格式示例，不会被任何生产流程自动导入。**

**⚠️ 示例数字仅为教学，不是投资建议。**

### 4.3 关于 cash（现金）

CSV 里可以写一行 `CASH` 表示现金（Schwab 导出风格），但**更推荐显式指定**：

```powershell
PersonalAlphaTerminal.exe portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --cash 25000
```

`--cash` 省略且 CSV 里也没有 CASH 行时，系统**不会偷偷假定现金**，
而是**保留组合现有的现金余额不变**（导入结果会标记现金未更新）。
想改现金就必须显式 `--cash` 或在 CSV 里写 CASH 行。

### 4.4 preview 与 commit

`portfolio-import` 默认是 **preview（预览）**：只解析、校验、显示将导入什么，
**不写入**真实账本。确认无误后再加 `--commit` 真正提交：

```powershell
# 第一步：预览（不改动任何数据）
PersonalAlphaTerminal.exe portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10

# 第二步：确认后提交
PersonalAlphaTerminal.exe portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --commit
```

参数：
- `csv`：CSV 文件路径（必填）
- `--portfolio-id`：目标组合 ID（必填，用 `portfolio-list` 查看）
- `--as-of`：持仓生效日期 `YYYY-MM-DD`（必填）
- `--commit`：真正写入（缺省只预览）
- `--cash`：显式现金覆盖

### 4.5 校验规则（导入时会被拒绝的情况）

- 表头缺失或无法识别
- 非正股数（0 和负数都拒绝，不支持做空）
- NaN / Inf 数值
- 重复的 ticker
- 空的 ticker
- 损坏或截断的文件

任何校验失败都会明确指出**哪一行、什么问题**，并且不会写入任何数据。

### 4.6 从 Charles Schwab 整理真实持仓

系统不连接 Schwab，也不假设 Schwab 界面的具体按钮路径。正确做法是：

1. 登录你的 Schwab 账户，打开持仓页面；
2. **人工**记录每个持仓的代码和股数（以及现金余额）；
3. 按 4.2 的格式整理成 CSV；
4. 用 preview → commit 两步导入。

不要直接导入 Schwab 的原始导出文件——它们的列名与格式各不相同，
请先人工整理成上面的标准格式。

---

## 第 5 章 组合选择与查看

```powershell
# 列出所有组合（id / 名称 / 货币 / 现金）
PersonalAlphaTerminal.exe portfolio-list
PersonalAlphaTerminal.exe portfolio          # 同上，别名

# 查看某个组合的详细持仓（id / 名称 / 货币 / 现金 / as_of + 逐持仓）
PersonalAlphaTerminal.exe portfolio-show --portfolio-id 1
```

没有组合时，`portfolio-list` 会显示
`QUANT ANALYSIS READY · PORTFOLIO REQUIRED · TRADING BLOCKED`，
提示先运行 portfolio-init 或 portfolio-import。

**daily 运行使用哪个组合？** 规则（`_resolve_portfolio`）：

- 数据库里**恰好只有 1 个**组合 → 自动使用它；
- 有 0 个 → PORTFOLIO NOT_INITIALIZED（阻塞）；
- 有 ≥2 个 → 不自动选择，返回 NOT_INITIALIZED，
  你需要删掉多余的或用唯一组合。

因此个人使用建议：**只维护一个组合账本**。

---

## 第 6 章 每次交易后的持仓同步（重要）

**核心事实：你在 Schwab 手工交易后，系统不会自动知道。**
持仓账本必须由你手工更新，否则下一次分析的「当前持仓」是错的。

### 6.1 你有哪些工具

| 场景 | 推荐做法 |
|---|---|
| 执行了系统给出的建议（FINAL VALIDATED DECISIONS 里的行） | `mark-executed` 录入成交 |
| 部分成交 | 同一 `--fill-id` 体系下多次 `mark-executed`，或整份重导 |
| 完全清仓某标的 | 整份重导（新 CSV 不含该标的） |
| 新增仓位（系统没建议、你自己买的） | 整份重导 |
| 现金变动（出入金、分红） | 整份重导（带 `--cash`） |

### 6.2 用 mark-executed 录入成交

对一条已接受的建议录入一笔真实成交：

```powershell
PersonalAlphaTerminal.exe accept REC-xxxx --run-id daily-xxxxxxxx
# 在 Schwab 手工下单并成交后：
PersonalAlphaTerminal.exe mark-executed REC-xxxx --run-id daily-xxxxxxxx --price 100.50 --quantity 10 --fees 0 --fill-id schwab-2026-08-10-001
```

参数：
- `recommendation_id`：建议 ID（位置参数）
- `--run-id`：该建议所属的 Run ID（必填，系统会校验建议确实绑定到这个 run）
- `--price` / `--quantity` / `--fees`：成交价 / 数量 / 手续费（fees 默认 0）
- `--fill-id`：**唯一**的成交标识。多笔部分成交必须每笔用不同 fill-id
- `--timestamp` / `--notes` / `--external-reference`：可选备注

**部分成交**：approved 数量没填满前，订单状态保持 `PARTIAL`；
每笔部分成交用不同的 `--fill-id`，累计数量不得超过批准数量。
这个设计是重启安全的——中途退出不会丢状态。

**重要**：`mark-executed` 会真实更新账本的股数与现金。
只有你录入的成交才会改变持仓，ACCEPT 本身不改变持仓。

### 6.3 整份重导（最简单可靠）

如果你做了系统建议之外的操作（自己买卖、出入金），最稳妥的办法是
重新整理一份完整的当前持仓 CSV，然后：

```powershell
PersonalAlphaTerminal.exe portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --cash 24500 --commit
```

`--as-of` 用你确认持仓的日期。导入会作为新的持仓快照记录，
旧快照保留为历史（账本是时点化的，符合 PIT 原则）。

### 6.4 不要做的事

- ❌ 不要指望系统自动同步券商持仓（没有券商连接）；
- ❌ 不要在没成交时提前 `mark-executed`（账本会与实际不符）；
- ❌ 不要复用同一个 `--fill-id` 录入两笔不同成交。

---

## 第 7 章 逐块解释终端

> 本章按渲染顺序逐块讲解：它是什么、正常长什么样、异常长什么样、
> 是否影响交易。

### 7.1 HEADER（头部）

**内容**：总体分类、版本、Run ID、市场时段、三个日期、数据截止、耗时、分层状态行。

**总体分类**只有四种（这是最重要的一行）：

| 分类 | 含义 | 能否交易 |
|---|---|---|
| `ACTIONABLE TRADING PLAN · MANUAL EXECUTION ONLY` | 全链路通过，产生了正式交易计划 | 可人工执行 |
| `CERTIFIED NO-ACTION RUN` | 全链路通过，但没有需要调仓的操作 | 无需操作 |
| `VALID QUANT ANALYSIS / NON-ACTIONABLE` | 分析有效，但正式决策不可用 | 不可交易 |
| `INVALID / NON-ACTIONABLE QUANT RUN` | 本次运行无效 | 绝对不可交易 |

**分层状态行**（Part 3 引入的新语义）：

```text
DATA READY   QUANT ANALYSIS READY   PORTFOLIO READY   RISK READY   TRADING ACTIONABLE   LLM OPTIONAL/OFFLINE
```

每一层独立表达一个层级的就绪状态，避免「一个 READY 误导全局」。

### 7.2 PIPELINE · FAIL CLOSED（管线）

12 个阶段的状态表：CALENDAR、DATA、PIT、FEATURE、FACTOR、SIGNAL、
PROBABILITY、PORTFOLIO、RISK、DECISION、EXECUTION、PERSISTENCE。

**正常**：研究链（CALENDAR→SIGNAL）绿色 PASS，PROBABILITY 黄色
PASS_DEGRADED（设计内降级，见第 11 章）。

**异常**：任何红色 FAIL_BLOCKING 都会阻塞其后所有阶段；
NOT_RUN（灰色）表示被上游阻塞而未执行——这**不是**该阶段自己坏了。

**是否影响交易**：是。任何 FAIL_BLOCKING 都会导致 TRADING BLOCKED。

### 7.3 DATA CERTIFICATION（数据认证）

显示数据提供方的认证结果：Provider、Snapshot ID、请求/接收/认证/拒绝的
标的数、bars 的 expected/matched/unexpected/quarantined、覆盖率、
最新时间戳、PIT cutoff，以及五项完整性检查：
Corporate actions / PIT integrity / Freshness / Duplicates /
Invalid OHLC / Future rows / Timezone violations。

**正常**：certified = requested、matched = expected、
Future rows = 0、Duplicates = 0、Invalid OHLC = 0、Timezone violations = 0、
PIT integrity = PASS。

**异常**：任何非零的 Future rows / Duplicates / Invalid OHLC /
Timezone violations 都是严重问题，见第 18 章。

**是否影响交易**：是。数据认证不通过则一切下游都不可信。

### 7.4 REJECTED DATA（被拒数据）

只在有数据被拒绝时出现。列出被拒标的与原因（如缺少最新 bar、格式错误）。
少量拒绝通常不影响整体，但要看是否包含你关心的标的。

### 7.5 PIT / UNIVERSE（时点与研究域）

显示时点证据与研究域（universe）状态：当前研究域成员数、
是否为历史幸存者安全（survivorship-safe）域。

**正常**：universe 已认证、成员数 ≥ 配置要求（当前 18 个标的：
15 必需 + 3 可选）。

**注意**：免费数据源无法提供完整的历史成分/退市记录，
因此历史回测相关的域保持受限——这是已知限制，不是故障。

### 7.6 DATA HEALTH · STRATEGY INPUTS ONLY（数据健康度）

逐标的列出策略输入数据的健康状态（如 SAFE / WATCH / STALE）。
这是策略输入视角的健康度，帮助你判断某个标的数据是否新鲜可靠。

### 7.7 MARKET REGIME（市场状态）

显示 `REGIME_*` 状态与结构说明。这是**可选的分析覆盖层**，
不是核心量化管线的一部分。

**正常取值**：
- `REGIME_OPTIONAL_UNAVAILABLE`：没有可用的已校准 regime 结果——
  **这是允许的**，核心管线照常运行；
- `REGIME_CALIBRATED_RISK_ON/NEUTRAL/RISK_OFF`：存在已校准结果；
- `REGIME_OPTIONAL_*_SCORE_ONLY`：只有未校准的分数，仅展示、不参与任何计算。

**是否影响交易**：未校准时零影响（不会改变 alpha、仓位、风险限制）；
已校准时仅通过风险预算温和调整。看到黄色/灰色不要误以为系统坏了，
见第 12 章。

### 7.8 REAL PORTFOLIO · MANUAL LEDGER（真实组合）

显示组合状态、NAV、现金、已投资权重、现金权重，以及逐持仓的
Shares / Price / Current / Target / Delta。

**正常**：Status 为 `UNCHANGED` 或 `TARGET_COMPUTED`（表示组合已加载），
持仓与现金正确。
**异常**：`Status NOT_INITIALIZED` → 需要先 portfolio-init / portfolio-import。

**是否影响交易**：是。组合未初始化则正式交易被锁定。

### 7.9 FACTOR / ALPHA · CANDIDATE ≠ TRADE（因子与候选）

列出按 Composite 排序的候选：Rank / Ticker / 各因子分量
（momentum_12_1、trend_slope、low_volatility 等）/ Composite /
Exp Alpha / Evidence / Status。

**这是诊断区域，不是买入建议。** 详见第 9 章。

### 7.10 CONDITIONAL PROBABILITY（条件概率）

显示条件概率证据（仅支持性）。当前通常为 PASS_DEGRADED，
表示没有经过 OOS 校准的概率覆盖层——这是设计内的诚实状态。
详见第 11 章。

### 7.11 RISK EVIDENCE / RISK ADJUSTED TARGET（风险）

两个面板：

- **RISK EVIDENCE**：Correlation（recent/baseline/jump + N）、
  Size exposure、Stress、Stress evidence 说明；
- **RISK · RAW TARGET → RISK-ADJUSTED TARGET**：Gate 状态、
  Expected vol、Target vol、HHI、Largest target、Gross→Cash、Turnover、Reasons。

详见第 10 章。

### 7.12 FINAL VALIDATED DECISIONS（最终验证决策）

**唯一正式的 BUY/SELL 区域。** 表格列：Ticker / Action / Current /
Target / Delta / Value / Alpha / Confidence / Risk / Reason。

可能的内容：
- 若干 BUY/SELL/INCREASE/REDUCE 行 → 正式调仓建议；
- 单行 `ALL / NO_ACTION` → 完整管线跑完但没有超出 no-trade 带的调仓；
- 单行 `ALL / NOT_ACTIONABLE` → 必需阶段未完成，没有产生交易判断。

**是否影响交易**：这是唯一的交易依据。没有行 = 不要交易。

### 7.13 REJECTED SIGNALS / GATE BLOCKERS（被拒信号与闸门原因）

列出被风险/约束拒绝的信号与原因（Rejected by / Reason）。
帮助你理解「为什么某个强候选没有变成决策」。

### 7.14 EXECUTION PLAN（执行清单）

标题含状态与经纪商（`Charles Schwab (manual only)`）。
列：# / Ticker / Action / Est Value / Qty / Est Cost / Earliest。
下方给出现金流水：Cash before + Proceeds − Buys − Costs = Cash after。

**这只是手工执行清单**，系统不会、也不能自动下单。
无调仓时显示 `NO EXECUTION`。

### 7.15 BENCHMARK（基准）

显示 SPY 与 QQQ 两行（与策略使用**相同的 PIT 数据约定**）：
Benchmark / Status / Start / End / N / Period Return / Ann Vol / Max DD / Note。

**N** 是收益率观测数（bars−1）。**Status** 为 `PIT PROXY` 表示
基准收益来自与策略同一份 PIT 认证数据。详见第 13 章。

### 7.16 RUN CERTIFICATE（运行证书）

显示：Classification、Run ID、Data hash、Config hash、Models、
Certificate 路径。这是本次运行的「身份证」，用于追溯与复现。
边框绿色 = actionable，红色 = 不可交易。详见第 14 章。

### 7.17 TODAY SUMMARY（当日总结）

汇总：决策数、买/卖数、换手率、执行后现金、Blockers，
以及固定提示 `MANUAL EXECUTION REQUIRED · CHARLES SCHWAB · NO BROKER API`。
边框绿色 = actionable，红色 = 非 actionable。

---

## 第 8 章 状态代码与颜色说明

> 本章只列系统**真实存在**的状态，不发明新状态。

### 8.1 管线阶段状态（StageStatus）

| 状态 | 颜色 | 含义 |
|---|---|---|
| `PASS` | 绿 | 阶段成功完成 |
| `PASS_DEGRADED` | 黄 | 完成但降级（如概率未校准）——设计内，非故障 |
| `FAIL_BLOCKING` | 红（加粗） | 阶段失败并阻塞下游 |
| `NOT_RUN` | 灰 | 被上游阻塞而未执行 |

### 8.2 决策就绪（DecisionReadiness）

| 状态 | 含义 |
|---|---|
| `READY` | 所有必需阶段完成，决策可用 |
| `NOT_ACTIONABLE` | 证据不足，决策不可用 |

### 8.3 运行分类（run_classification）

见 7.1 的四种分类表。

### 8.4 组合状态

| 状态 | 含义 |
|---|---|
| `NOT_INITIALIZED` | 无真实组合账本（0 个或 ≥2 个组合） |
| `NOT_CHECKED` | 存在阻塞但未走到组合检查 |
| `UNCHANGED` | 组合已加载，本次运行未产生新的目标 |
| `TARGET_COMPUTED` | 组合已加载且本次运行计算出门控通过的目标 |

分层状态行里的 `PORTFOLIO READY` 表示状态不是 NOT_INITIALIZED
（即 UNCHANGED 或 TARGET_COMPUTED）。

### 8.5 风险状态（RiskSummary）

- **Gate / status**：`PASS`（风险与目标都已计算）/ `BLOCKED`
  （风险未计算或被拦截，含组合缺失的级联情形）。
- **correlation_status**：`VALID` / `NOT_VALIDATED`（样本不足）/
  `NOT_APPLICABLE`（持仓 < 2 只）/ `NOT_CAPTURED`（无组合风险状态）。
- **size_exposure_status**：`VALID` / `NOT_VALIDATED`（缺 PIT 市值数据）/
  `NOT_CAPTURED`。
- **stress_status**：`PASS` / `WARN` / `BLOCKED` / `NOT_VALIDATED`
  （未做生产验证）/ `NOT_CAPTURED`。

### 8.6 概率状态

- `PASS_DEGRADED`（阶段）+ `INSUFFICIENT EVIDENCE` / `NOT CALIBRATED OOS`
  （reliability）→ 未校准，诚实降级；
- `CALIBRATED_LOCKED_OOS` → 存在已校准锁定 OOS 的概率工件。

### 8.7 市场 regime 状态

`REGIME_OPTIONAL_UNAVAILABLE` / `REGIME_CALIBRATED_*` /
`REGIME_OPTIONAL_*_SCORE_ONLY`（见 7.7）。

### 8.8 分层状态行取值

`DATA READY/BLOCKED`、`QUANT ANALYSIS READY/NOT READY`、
`PORTFOLIO READY/REQUIRED`、`RISK READY/BLOCKED`、
`TRADING ACTIONABLE/BLOCKED`、`LLM OPTIONAL` / `LLM OPTIONAL/OFFLINE`。

### 8.9 其他常见标记

- `NO_ACTION`：管线完整但没有调仓（正常）；
- `NOT_ACTIONABLE`：证据不足（正常的安全结果）；
- `DIAGNOSTIC ONLY` / `CANDIDATE ≠ TRADE`：诊断信息，非交易建议；
- `BLOCKED`：闸门阻塞。

### 8.10 颜色总则

- **绿**：通过 / 可交易（actionable）；
- **黄**：降级 / 警告（PASS_DEGRADED、stress 非 PASS）——通常不是故障；
- **红**：失败 / 阻塞 / 不可交易；
- **灰**：未运行（被上游阻塞）。

---

## 第 9 章 Candidate ≠ Trade（候选 ≠ 交易）

**这是全系统最重要的一条规则，请务必理解。**

FACTOR / ALPHA 区块里的候选排名（例如 `GOOGL Rank 1`）
**绝对不等于「应该买入 GOOGL」**。原因：

1. **候选只是因子排名**。它回答「哪些标的的因子分高」，
   不回答「该不该买、买多少」。
2. **候选没有经过组合约束**。真实组合有仓位上限、行业上限、
   换手率限制、现金下限、波动目标等，一个排名靠前的候选可能
   因为已经超配而无法加仓。
3. **候选没有经过风险引擎**。相关性、压力、集中度可能否决它。
4. **候选没有经过 no-trade 带**。微小的目标调整会被忽略。

只有 **FINAL VALIDATED DECISIONS** 区块才是正式交易输出，
而且它必须已经通过 Portfolio、Risk、Decision 全部闸门。

**正确读法**：
- 看候选 → 理解市场里什么因子在起作用（诊断）；
- 看最终决策 → 决定要不要手工执行（行动）。

如果你只看到候选而没有最终决策行，那就是「没有交易」。

---

## 第 10 章 Risk 教程（风险引擎）

风险引擎只在组合存在时真正执行。它回答：「这个目标组合安全吗？」

### 10.1 字段逐个解释

| 字段 | 含义 | 怎么看 |
|---|---|---|
| Gate | 风险总闸状态 | `PASS` 才允许决策 |
| Expected vol | 组合预期年化波动 | 越低越稳 |
| Target vol | 策略目标波动 | Expected 偏离太多会降敞口 |
| HHI | 赫芬达尔集中度指数 | 越小越分散（上限 0.18） |
| Largest target | 最大单一目标仓位 | 上限 12% |
| Gross → Cash | 总敞口 → 现金目标 | 现金下限 10% |
| Turnover | 换手率 | 上限 30%，控制交易成本 |
| Correlation | 持仓间相关性 recent/baseline/jump | 相关性飙升会降敞口 |
| Size exposure | 市值暴露证据 | `NOT_VALIDATED` 表示缺 PIT 市值数据 |
| Stress | 压力测试状态 | 触发硬限制会 BLOCKED |

### 10.2 为什么一个强 Alpha 信号也可能被 Risk 拒绝

举例：某标的因子排名第 1（强 alpha），但：

- 你已经持有它 12%（达到单一仓位上限）→ 不能再加；
- 它与你现有持仓高度相关 → 相关性约束否决；
- 加它会突破波动目标 → 风险预算削减；
- 压力测试显示尾部损失超限 → stress 一票否决。

所以「因子强」只是入场券，**风险与约束才是最终裁判**。
被拒的信号会出现在 REJECTED SIGNALS 区块，附带原因。

### 10.3 风险状态的正常与异常

- **正常**：Gate PASS、stress PASS、size VALID、correlation VALID；
- **可接受**：size `NOT_VALIDATED`（免费数据缺 PIT 市值）→
  组合构建会因此 fail-closed，这是诚实行为；
- **异常**：Gate BLOCKED / stress BLOCKED → 决策不会产生，TRADING BLOCKED。

---

## 第 11 章 Probability 教程（条件概率）

### 11.1 PASS_DEGRADED 不是系统坏了

PROBABILITY 阶段显示 `PASS_DEGRADED`、
消息 `no calibrated conditional overlay; deterministic base alpha is unchanged`，
这是**设计内的正确状态**，含义是：

> 目前没有一个经过 OOS（样本外）校准、被批准的概率模型，
> 所以系统诚实地说「我没有可靠的概率」，
> 并且**完全不影响**确定性的基础 alpha。

### 11.2 关键概念

- **calibrated（已校准）**：概率模型在独立样本外数据上验证过，
  预测的概率与实际频率吻合。只有这样的概率才被允许显示。
- **uncalibrated（未校准）**：没有经过验证的概率。系统拒绝显示。
- **OOS（out-of-sample，样本外）**：模型从没见过的数据，
  用来检验它是否真的有效。训练数据绝不能和评估数据混用。
- **sample size（样本量）**：概率估计需要足够多的历史样本
  （系统有最小样本要求），样本太少则不可靠。
- **supporting evidence（支持证据）**：即使有校准概率，
  它也**只是支持证据**，不改变 alpha、不单独触发交易。

### 11.3 为什么「不显示概率」比「随便显示 75%」更可靠

假设系统随便给你一个「上涨概率 75%」：

- 这个数字没有经过样本外验证，可能完全是过拟合的幻觉；
- 你会基于一个虚假的确定性去交易，承担真实风险；
- 一旦亏损，你无法追溯这个数字是怎么来的。

而「不显示概率 + 明确告诉你为什么」：

- 你知道系统没有可靠的概率证据；
- 你不会误以为有一个 75% 的把握；
- 决策仍然基于确定性的、可复现的因子 alpha。

**诚实的「我不知道」永远比虚假的「75%」更安全。**

### 11.4 Probability 不是 AI 猜涨跌

条件概率模块是**统计估计**（基于历史事件的条件频率 + Beta-Binomial 后验），
不是大语言模型的主观猜测。而且 LLM 在本系统里根本不参与概率计算。

---

## 第 12 章 Market Regime 教程（市场状态）

### 12.1 SCORE_UNAVAILABLE / REGIME_OPTIONAL_UNAVAILABLE 是允许的

MARKET REGIME 区块显示 `REGIME_OPTIONAL_UNAVAILABLE` 或提示
「Regime probability is unavailable」时，**这是允许的、正常的**。
原因：当前没有一份「经过 walk-forward 校准并达到 Brier 改进门槛」的
regime 运行结果。

### 12.2 区分两类状态

| 类别 | 例子 | 你该紧张吗 |
|---|---|---|
| **可选覆盖层不可用** | REGIME_OPTIONAL_UNAVAILABLE、PROBABILITY PASS_DEGRADED | 不。核心管线照常 |
| **核心管线失败** | DATA FAIL_BLOCKING、PIT FAIL_BLOCKING、RISK BLOCKED | 要。这影响交易 |

**判断口诀**：看 PIPELINE 表。只要 CALENDAR→SIGNAL 这些核心阶段是绿的，
regime / probability 的黄色或灰色就只是「可选增强没开」，不是系统坏了。

### 12.3 Regime 不改变核心结论（除非已校准）

- 未校准 / 不可用 → 对 alpha、仓位、风险限制**零影响**；
- 已校准（REGIME_CALIBRATED_*）→ 仅通过风险预算温和调整敞口
  （risk_off 时降低总敞口/波动/仓位乘子）。

所以看到 regime 是黄色/灰色，不必担心它会悄悄改变你的交易。

---

## 第 13 章 Benchmark 教程（基准）

### 13.1 SPY 与 QQQ 是什么 proxy

| 基准 | 代理的市场 |
|---|---|
| **SPY** | S&P 500（标普 500）大盘 |
| **QQQ** | Nasdaq-100（纳斯达克 100）科技成长 |

两者都是 ETF，作为市场表现的参照物（proxy）。

### 13.2 字段含义

- **Period Return**：基准在统计区间内的累计收益；
- **Annualized Volatility（Ann Vol）**：年化波动率；
- **N**：收益率观测数（= bars − 1）；
- **PIT Proxy**：状态标记，表示基准收益来自**与策略同一份
  PIT 认证数据**，保证日期语义一致（不会出现策略用 t、基准用 t+1）；
- **Start / End**：统计区间起止日期；
- **Max DD**：区间内最大回撤。

### 13.3 为什么比较策略不能只看收益率

只看收益率会严重误导。评估任何策略至少要看：

- **benchmark**：跑赢/跑输基准多少（超额收益）；
- **transaction cost（交易成本）**：频繁交易会侵蚀收益；
- **slippage（滑点）**：实际成交价与预期的偏差；
- **drawdown（回撤）**：最坏时亏多少，你能承受吗；
- **volatility（波动）**：收益的颠簸程度；
- **turnover（换手率）**：多频繁换仓（成本来源）；
- **walk-forward / OOS**：策略是否在未见过的数据上验证过。

一个「年化 30% 但回撤 60%、全靠未来函数」的策略，
远不如「年化 10%、回撤 10%、OOS 验证过」的策略可靠。

### 13.4 基准数据不可用时

- **SPY**（主基准）数据不可用 → 该行显示 `UNAVAILABLE`；
- **QQQ** 不在认证 PIT 研究域内 → 该行显示 `NOT_AVAILABLE`
  （说明 Nasdaq-100 proxy 缺失）。

两种情况系统都**不会伪造**基准数据，只会如实标注缺失。

---

## 第 14 章 Run Certificate 教程（运行证书）

### 14.1 为什么需要运行证书

每次 `daily` 运行都会生成一份**不可变的运行证书**（run certificate），
记录这次运行到底用了什么数据、什么配置、什么模型、得到了什么结果。
它的价值：

- **可追溯**：几个月后你能知道某个结论是怎么来的；
- **可复现**：相同的数据哈希 + 配置哈希 + 模型哈希 = 相同的结果；
- **可审计**：防止「事后改口」。

### 14.2 证书里的关键字段

证书 schema 为 `pat-quant-run-certificate-v2`。关键字段：

| 字段 | 含义 |
|---|---|
| **run_id** | 本次运行的唯一标识（如 `daily-0445725f...`） |
| **classification** | 运行分类（见 7.1） |
| **trading_use** | `MANUAL_REVIEW_REQUIRED` 或 `DO_NOT_USE_FOR_TRADING` |
| **analysis_date / trade_date** | 分析日 / 交易日 |
| **data_cutoff** | PIT 数据截止时间 |
| **config_hash** | 规范化运行配置哈希（canonical_run_config_hash） |
| **identity_hashes** | 身份指纹集（嵌套），含 `runtime_config_hash`、`strategy_parameter_hash`、`data_version_hash`、`portfolio_constraint_hash`、`risk_model_hash`、`cost_model_hash`、`model_approval_hash` |
| **model_versions** | 参与运行的模型版本列表 |
| **data_certification / stage_evidence** | 数据认证与各阶段证据 |
| **probability / portfolio / risk** | 概率、组合、风险证据 |
| **decision_counts / decision_recommendations** | 决策计数 / 正式决策建议 |
| **decision_traces** | 每个标的的决策证据链 |
| **benchmarks** | SPY / QQQ 基准证据 |
| **blockers / warnings** | 阻塞原因 / 警告 |
| **provenance** | 溯源信息：`data_hash`、`data_snapshot_id`、`pit_cutoff`、`git_commit`、`transaction_cost_assumption` 等 |

### 14.3 如何找到证书

证书保存在：

```text
reports/daily-runs/<run_id>/run_certificate.json
```

- 不指定 run-id 时，系统自动用**最新一份**证书；
- 要定位某一天：进入 `reports/daily-runs/`，按目录修改时间或
  证书里的 `analysis_date` 找。

用命令查看某个已持久化运行的特定区块：

```powershell
PersonalAlphaTerminal.exe decisions --run-id daily-xxxxxxxx   # 决策
PersonalAlphaTerminal.exe risk --run-id daily-xxxxxxxx        # 风险
PersonalAlphaTerminal.exe data --run-id daily-xxxxxxxx        # 数据认证
```

### 14.4 如何判断「今天的结果来自哪份数据和配置」

1. 打开今天的 `run_certificate.json`；
2. 看 `analysis_date`（用的哪天的数据）；
3. 看 `config_hash` 与 `identity_hashes`（用的什么配置与策略参数）；
4. 看 `provenance` 里的 `data_hash` / `data_snapshot_id`
   （数据来自哪个快照）。

如果这些哈希和你预期的一致，结果就是可信、可复现的。

---

## 第 15 章 Fail-Closed 教程（宁缺毋滥）

### 15.1 系统的核心安全哲学

> 系统宁愿「不给交易结论」，也绝不「猜一个结论」。

因为一个错误的交易结论可能让你亏真金白银，
而「没有结论」最多让你今天不交易。**不交易的代价远小于错误交易的代价。**

### 15.2 哪些情况会 fail-closed

| 触发条件 | 系统行为 |
|---|---|
| Market data failed（数据认证失败） | DATA FAIL_BLOCKING，下游全停 |
| PIT failed（时点证据不足） | PIT FAIL_BLOCKING |
| Portfolio missing（组合未初始化） | PORTFOLIO FAIL_BLOCKING，交易锁定 |
| Risk failed（风险检查不过） | RISK BLOCKED，决策不产生 |
| Decision incomplete（必需阶段缺失） | NOT_ACTIONABLE，无 BUY/SELL |

### 15.3 NO TRADE 是正确表现

上面任何一种情况下，看到 `NOT_ACTIONABLE` / `BLOCKED` / 空的决策表，
**都是系统在正确地保护你**。这不是 bug，不需要「修复」让它强行给结论。

**绝对不要**为了让系统「给出建议」而：
- 伪造数据、伪造组合、伪造 approval；
- 放宽校验、跳过闸门；
- 把诊断候选当成交易信号手动下单。

---

## 第 16 章 周末与节假日

### 16.1 周六 / 周日运行

美股周末不开盘，没有新数据。系统行为：

- **Analysis Date** = 最近一个已完成交易日（周五）；
- **Trade Date** = 下一个交易日（下周一）；
- **Latest Completed Session** = 周五。

所以周日运行看到「数据到周五」是**完全正常**的，
不是数据过期，也不是系统故障。

### 16.2 美国市场节假日运行

节假日（如感恩节、独立日）同样不开盘。系统自动跳过节假日，
使用最近一个真实交易日的数据，Trade Date 指向节假日后的下一个交易日。

### 16.3 字段对照

| 字段 | 周末运行时的值 | 说明 |
|---|---|---|
| Expected / Latest | 周五 | 最新可用数据 |
| Age（数据年龄） | 1-3 天 | 周末自然偏旧，正常 |
| Trade Date | 下周一 | 最早可执行日 |

**判断口诀**：只要 DATA PASS 且 `DATA READY`，数据日期「不是今天」
在周末/节假日是预期行为，不必担心。

---

## 第 17 章 LLM 配置（可选）

### 17.1 LLM 是做什么的、不做什么

LLM（大语言模型）在本系统里**完全是可选的、解释性的**：

**能做**：
- 用自然语言解释某一次运行的结果；
- 总结因子、决策、风险状况；
- 提供 `explain <symbol>` 的文字化说明。

**绝不做**：
- ❌ 不参与真实价格、PIT、因子、信号计算；
- ❌ 不参与组合优化、风险闸门；
- ❌ 不产生最终 BUY/SELL；
- ❌ 不在没有它时阻止核心量化引擎运行。

### 17.2 LLM OFFLINE 时系统照常工作

`LLM OPTIONAL/OFFLINE` 表示未配置或关闭 LLM。**核心 Quant Engine
不依赖 LLM**：API 不配置、余额不足、网络失败，都不影响
DATA → DECISION 的运行。分层状态行会显示 `LLM OPTIONAL/OFFLINE`，
其余照常。

### 17.3 如何配置 API Key

LLM provider 由环境变量 `PAT_LLM_PROVIDER` 控制，默认 `disabled`。
取值：`auto` / `openai` / `deepseek` / `anthropic` / `custom` /
`mock` / `disabled`。

**绝对不要把 API Key 写进 Git 或 config.yaml。** 只通过环境变量提供：

```powershell
# PowerShell（当前会话；密钥值不写入文件或聊天）
$env:PAT_LLM_PROVIDER = "deepseek"
# DEEPSEEK_API_KEY 必须由启动该进程的操作系统环境预先继承
PersonalAlphaTerminal.exe daily

# CMD
set PAT_LLM_PROVIDER=deepseek
rem DEEPSEEK_API_KEY 必须由启动该进程的操作系统环境预先继承
```

当前真实 Provider 只从操作系统/进程环境读取 `DEEPSEEK_API_KEY`；不要把
密钥写入 `.env`、配置模板、日志或报告。Provider 抽象仍可在未来扩展，
但当前运行不创建、也不要求其他 Provider 的密钥。模型与 Base URL 使用
`PAT_DEEPSEEK_MODEL`、`PAT_DEEPSEEK_BASE_URL` 等非秘密配置。

### 17.4 配置错误 / API 不可用怎么办

- **provider 设为 disabled 或 mock** → 不需要 key，LLM 功能关闭，量化照常；
- **设了 provider 但 key 为空/错误** → LLM 相关调用会失败或降级，
  但**核心管线不受影响**；
- **网络失败 / 余额不足** → 同上，LLM 层降级，量化照常。

原则：**LLM 永远是锦上添花，不是必需品。** 不确定就保持 `disabled`。

---

## 第 18 章 常见问题与故障排查（概览）

> 完整的分条排查手册见 `docs/TROUBLESHOOTING_ZH_CN.md`。
> 这里给出最常见问题的快速判断。

每条按「现象 → 含义 → 是否危险 → 该做什么 → 不要做什么」组织。

| 现象 | 快速判断 |
|---|---|
| DATA unavailable / provider timeout | 网络或数据源问题，重试或稍后再跑 |
| PIT failed / future observations > 0 | 严重，停止交易，检查数据 |
| portfolio not initialized | 正常，先 portfolio-init / import |
| risk blocked | 风险闸门拦截，看 Reasons，不要强行交易 |
| probability degraded | 设计内降级，不是故障 |
| regime unavailable | 可选层未开，不是故障 |
| benchmark unavailable | 基准数据缺失，显示 NOT_AVAILABLE，正常 |
| LLM offline | LLM 未配置，量化照常 |
| 窗口闪退 | 用命令行运行看报错，见 TROUBLESHOOTING |
| weekend no new bar | 周末无新数据，正常 |

**总原则**：
- 红色 / BLOCKED / Future rows > 0 → 停止交易，排查数据；
- 黄色 / DEGRADED / NOT_AVAILABLE → 多半是设计内降级，先看 PIPELINE
  核心阶段是否绿色；
- 看不懂 → 不交易，查 TROUBLESHOOTING_ZH_CN.md。

---

## 第 19 章 每日操作清单（Checklist）

每天运行后，按此清单核对：

```text
[ ] 1. daily 运行完成，无崩溃
[ ] 2. HEADER 分类明确（看懂是哪一种）
[ ] 3. DATA READY，DATA CERTIFICATION 显示 PASS
[ ] 4. PIT integrity = PASS
[ ] 5. Future rows = 0，Duplicates = 0，Invalid OHLC = 0
[ ] 6. PIPELINE 核心阶段（CALENDAR→SIGNAL）绿色
[ ] 7. Portfolio 状态正确（已初始化）
[ ] 8. Risk 未 BLOCKED（或理解为何 BLOCKED）
[ ] 9. 读 FINAL VALIDATED DECISIONS
[ ] 10. 若 actionable：查看 EXECUTION PLAN
[ ] 11. 人工审核每条建议（accept / reject / watch）
[ ] 12. 决定后在 Charles Schwab 手工下单
[ ] 13. 成交后 mark-executed 或整份重导同步持仓
[ ] 14. 确认 RUN CERTIFICATE 已保存（reports/daily-runs/）
```

**任何一步出现红色 / BLOCKED / Future rows > 0 → 停在第 5 步，
不要继续到交易。**

---

## 第 20 章 文档导航

| 文档 | 用途 |
|---|---|
| `docs/USER_GUIDE_ZH_CN.md` | 本教程（中文使用手册） |
| `docs/CLI_REFERENCE_ZH_CN.md` | 全部 CLI 命令参考（中文） |
| `docs/TROUBLESHOOTING_ZH_CN.md` | 完整故障排查手册（中文） |
| `ARCHITECTURE.md` | 系统架构 |
| `docs/LLM_CONFIGURATION.md` | LLM 配置（英文） |
| `docs/TERMINAL_GUIDE.md` | 终端指南（英文） |
| `docs/TROUBLESHOOTING.md` | 故障排查（英文） |
| `docs/QWEN_FINAL_TAKEOVER_REPORT.md` | 接管与修复最终报告 |

---

> **免责声明**：本软件是研究与决策支持工具，不构成投资建议。
> 历史表现不保证未来收益。示例中的所有数字仅为格式演示，
> 不代表任何买卖建议。交易决策与风险由使用者自行承担。


