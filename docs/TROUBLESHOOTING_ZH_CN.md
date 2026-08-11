# Personal Alpha Terminal — 故障排查手册（中文）

> 遇到问题时，**第一步永远是**：
>
> ```powershell
> PersonalAlphaTerminal.exe doctor
> ```
>
> 完整日志在 `%LOCALAPPDATA%\PersonalAlphaTerminal\logs`
> （开发环境为 `var/logs`），终端只显示安全摘要。
>
> 每条问题按「现象 → 含义 → 是否危险 → 应该做什么 → 绝对不要做什么」组织。

---

## 一、数据类问题

### 1.1 DATA UNAVAILABLE（数据不可用）

- **现象**：PIPELINE 中 DATA 阶段 FAIL_BLOCKING，没有最终决策。
- **含义**：数据提供方超时/限流、网络失败、schema 被拒绝，或缓存为空。
- **是否危险**：不危险，但今天不能交易。
- **应该做什么**：运行 `doctor`，查看 `data.log`，确认 provider 顺序与网络；
  网络恢复后运行 `refresh` 重试。
- **绝对不要做什么**：不要绕过数据闸门，不要手工插入伪造价格。

### 1.2 Provider Timeout / Network Error（提供方超时 / 网络错误）

- **现象**：刷新数据时报超时或连接错误；`data-provider test` 失败。
- **含义**：网络不通、对方限流、或可选 provider 未配置 key。
- **是否危险**：不危险。主数据源（Yahoo）失败时系统会尝试 fallback，
  且 fallback 数据同样要经过完整认证。
- **应该做什么**：检查网络；用 `data-provider status` 看各 provider 状态；
  稍后重试 `refresh`。
- **绝对不要做什么**：不要因为超时就认定「数据坏了」而去手工改数据。

### 1.3 DATA STALE（数据陈旧）

- **现象**：最新观测比预期的美股交易日旧。
- **含义**：漏了刷新、提供方故障、或缓存陈旧。
- **是否危险**：不危险。陈旧缓存是只读的，**不可能**凭它产生交易。
- **应该做什么**：看 DATA HEALTH 的 expected/latest/age/source 字段；
  连接恢复后 `refresh`。
- **绝对不要做什么**：不要用旧数据强行当作最新数据交易。

### 1.4 NETWORK / CACHE（网络与缓存）

- **现象**：主数据源失败；fallback 降级或缓存损坏。
- **含义**：断网、被反爬页面拦截、部分写入、校验/schema 不匹配。
- **是否危险**：缓存损坏可能让刷新失败，但不会污染已有数据。
- **应该做什么**：查 `data.log` 与缓存清单；恢复网络后刷新。
  HTML 页面永远不会被当作行情 CSV 接受。
- **绝对不要做什么**：只删除已确认损坏的缓存文件；
  **绝不**删除数据库或不可变快照。

---

## 二、PIT 与时点问题

### 2.1 PIT FAILED（时点验证失败）

- **现象**：PIPELINE 中 PIT 阶段 FAIL_BLOCKING。
- **含义**：时点证据不足——数据的可用时间（available_time）
  与决策时点不一致，存在使用未来信息的风险。
- **是否危险**：**危险信号**。这是系统最重要的完整性防线。
- **应该做什么**：停止一切交易；运行 `doctor`；检查最近是否有
  数据回填或时钟异常；必要时重新 `refresh`。
- **绝对不要做什么**：绝对不要为了「让 PIT 通过」而修改数据时间戳、
  放宽校验或绕过闸门。

### 2.2 Future Observations > 0（出现未来观测）

- **现象**：DATA CERTIFICATION 显示 `Future rows` 大于 0。
- **含义**：有数据的 available_time 晚于 PIT cutoff 却进入了计算——
  即「未来函数/数据泄漏」迹象。正常值必须是 0。
- **是否危险**：**严重**。任何 Future rows > 0 的运行都不可用于交易。
- **应该做什么**：立即停止交易；记录 Run ID；检查数据源是否回填了
  修正数据；联系维护者排查。
- **绝对不要做什么**：不要忽视这个指标继续交易。

---

## 三、组合（Portfolio）问题

### 3.1 PORTFOLIO NOT_INITIALIZED（组合未初始化）

- **现象**：REAL PORTFOLIO 显示 `Status NOT_INITIALIZED`，
  TRADING BLOCKED，RISK/DECISION/EXECUTION 为 NOT_RUN。
- **含义**：数据库里还没有真实组合账本（或有多个组合无法自动选择）。
- **是否危险**：不危险，这是 fail-closed 的正确保护。
- **应该做什么**：运行 `portfolio-init`（交互向导）或
  `portfolio-import`（CSV）建立账本；用 `portfolio-list` 确认只有一个组合。
- **绝对不要做什么**：不要期望系统自动生成一个「假组合」来解锁交易——
  系统被明确禁止这样做。

### 3.2 Portfolio File Corrupted / CSV 导入失败

- **现象**：`portfolio-import` 报缺列、重复代码、非法数量/成本、
  文件损坏、无法匹配证券主数据等错误。
- **含义**：CSV 不符合要求（表头、编码、数值、格式）。
- **是否危险**：不危险——校验失败时**不会写入任何数据**。
- **应该做什么**：先不带 `--commit` 预览，按错误提示逐行修正；
  参照 `docs/user-guide/portfolio_import_template.csv` 的格式；
  确认文件是 UTF-8 编码。
- **绝对不要做什么**：不要直接导入券商原始导出文件而不整理格式；
  不要就地修改券商的源文件。

### 3.3 组合数据与实际不符

- **现象**：终端显示的持仓/现金与 Schwab 实际不一致。
- **含义**：交易后没有同步账本（系统不会自动感知券商变化）。
- **是否危险**：会导致后续分析基于错误持仓——需要尽快修正。
- **应该做什么**：用 `mark-executed` 补录成交，或用最新持仓 CSV
  `portfolio-import --commit` 整份重导。
- **绝对不要做什么**：不要在持仓不符的情况下继续执行新的交易建议。

---

## 四、风险 / 决策 / 概率 / Regime / 基准问题

### 4.1 RISK BLOCKED（风险阻塞）

- **现象**：RISK 阶段 BLOCKED，决策不产生。
- **含义**：风险检查不通过（相关性、压力、集中度、波动、size 证据缺失等）。
- **是否危险**：不危险——这正是风险引擎在保护你。
- **应该做什么**：读 RISK 面板的 Reasons 与 REJECTED SIGNALS 区块，
  理解被拒原因。
- **绝对不要做什么**：不要绕过风险闸门，不要手工构造「看起来安全」的
  数据让风险通过。

### 4.2 PROBABILITY DEGRADED（概率降级）

- **现象**：PROBABILITY 阶段黄色 `PASS_DEGRADED`，
  提示 no calibrated conditional overlay。
- **含义**：没有经过 OOS 校准的概率模型，系统诚实降级。
- **是否危险**：**不危险，不是故障**。确定性基础 alpha 不受影响。
- **应该做什么**：无需处理。理解「不显示概率」比「假概率」更安全即可。
- **绝对不要做什么**：不要把降级当成系统损坏去「修复」，
  更不要为了消除黄色而伪造校准工件。

### 4.3 REGIME UNAVAILABLE（市场状态不可用）

- **现象**：MARKET REGIME 显示 `REGIME_OPTIONAL_UNAVAILABLE` 或 SCORE_UNAVAILABLE。
- **含义**：没有已校准的市场状态结果。Regime 是**可选覆盖层**，
  不属于核心量化管线。
- **是否危险**：**不危险**。核心管线（DATA→DECISION）照常运行。
- **应该做什么**：无需处理。只要 PIPELINE 核心阶段是绿色，系统就正常。
- **绝对不要做什么**：不要因为这一项是灰/黄就认为系统整体故障。

### 4.4 BENCHMARK UNAVAILABLE（基准不可用）

- **现象**：BENCHMARK 区块中 SPY 或 QQQ 显示 NOT_AVAILABLE。
- **含义**：该基准的数据缺失或不可靠。
- **是否危险**：不危险。系统**不会伪造**基准数据。
- **应该做什么**：检查数据认证中该标的是否 certified；刷新数据。
- **绝对不要做什么**：不要手工填入基准收益。

---

## 五、LLM 问题

### 5.1 LLM OFFLINE / ERROR

- **现象**：解释功能不可用，但 Quant 分析照常 READY。
- **含义**：未配置 API key、401/429 错误、超时、模型或 base URL 无效。
- **是否危险**：不危险。**LLM 是可选的**，核心量化引擎完全不依赖它。
- **应该做什么**：检查 LLM 配置（环境变量）；不需要解释功能就保持
  `PAT_LLM_PROVIDER=disabled`；修正凭据后重试。
- **绝对不要做什么**：不要把 API key 写进 config.yaml 或提交到 Git。

---

## 六、运行环境问题

### 6.1 命令窗口闪退 / 立刻关闭

- **现象**：双击 exe 后窗口一闪而过。
- **含义**：通常是发布包不完整、写权限被拒、缺运行时文件、磁盘空间不足。
- **是否危险**：不危险，但无法使用。
- **应该做什么**：把整个 ZIP 解压到普通本地目录（**不要只复制 exe，
  必须保留 `_internal` 目录**）；从命令行运行 exe 查看报错；
  检查 `boot.log` / `error.log`。
- **绝对不要做什么**：不要从 onedir 发布包里只拷 exe 文件。

### 6.2 Python / 运行时依赖问题（开发环境）

- **现象**：开发环境运行报 `ModuleNotFoundError`、Python 版本错误。
- **含义**：虚拟环境未激活、依赖未安装、或 Python 版本不匹配
  （开发支持 3.12–3.14，项目 .venv 为 3.12）。
- **是否危险**：不危险。
- **应该做什么**：
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
  .\.venv\Scripts\python.exe main.py
  ```
- **绝对不要做什么**：不要用系统全局 Python 混装依赖后运行。

### 6.3 权限错误（Permission Error）

- **现象**：写报告/数据库/缓存时报权限错误。
- **含义**：目录不可写（如放在受保护的系统目录）。
- **是否危险**：不危险，但无法持久化。
- **应该做什么**：把项目放在当前用户可写的目录；`doctor` 会检查
  Cache / Reports 目录可写性。
- **绝对不要做什么**：不要用管理员权限「硬闯」——先换到正常目录。

### 6.4 TEMP 目录 ACL 问题

- **现象**：某些操作（尤其测试）报临时目录创建失败。
- **含义**：Windows TEMP 目录权限异常。
- **是否危险**：不危险。
- **应该做什么**：把 TMP/TEMP 指向项目内隔离目录
  （如 `.var\test-tmp`）再运行；或修复用户 TEMP 目录权限。
- **绝对不要做什么**：不要修改系统级 ACL 设置来解决单个应用问题。

### 6.5 报告无法写入（Report Cannot Write）

- **现象**：运行成功但 `reports/daily-runs/` 没有新证书。
- **含义**：report_dir 不可写或磁盘已满。
- **是否危险**：不危险，但失去了可追溯证据。
- **应该做什么**：`doctor` 检查 Reports 目录；清理磁盘空间；
  确认 `config.yaml` 的 `report_dir` 指向可写路径。
- **绝对不要做什么**：不要在没有证书的情况下声称「运行成功可交易」。

### 6.6 Windows 路径问题

- **现象**：路径含中文/空格/特殊字符时报错。
- **含义**：某些组件对非 ASCII 路径敏感。
- **是否危险**：不危险。
- **应该做什么**：把项目放在纯英文、无空格的短路径下。
- **绝对不要做什么**：不要修改系统区域设置来迁就路径问题。

### 6.7 时区问题（Timezone Issue）

- **现象**：analysis date / trade date 与预期不符；会话状态异常。
- **含义**：本机时钟错误、时区错误、夏令时边界、或美股提前收盘日。
- **是否危险**：可能导致用错交易日数据——需要修正。
- **应该做什么**：运行 `doctor` 看 Timezone/calendar 行；
  校准 Windows 时钟与时区；对照报告里的 analysis/trade 日期。
- **绝对不要做什么**：不要用「日历日加减」代替交易日历逻辑。

### 6.8 周末没有新数据（Weekend No New Bar）

- **现象**：周六/周日运行，数据停在周五，没有新 bar。
- **含义**：**这是正常行为**。美股周末不开盘，系统使用最近一个
  已完成交易日（周五）的数据，Trade Date 指向下周一。
- **是否危险**：不危险，完全符合预期。
- **应该做什么**：无需处理。确认 Analysis Date = 周五、
  Trade Date = 下周一即可。
- **绝对不要做什么**：不要试图构造「周末的 bar」或把周六/周日
  当作交易日。

---

## 七、快速决策表

| 看到什么 | 结论 |
|---|---|
| Future rows > 0 / PIT FAIL | **停止交易**，排查数据 |
| DATA FAIL_BLOCKING | 停止交易，检查网络/数据源后 refresh |
| PORTFOLIO NOT_INITIALIZED | 正常保护，portfolio-init / import |
| PROBABILITY PASS_DEGRADED | 正常降级，无需处理 |
| REGIME UNAVAILABLE | 可选层未开，无需处理 |
| BENCHMARK NOT_AVAILABLE | 基准数据缺失，不伪造 |
| LLM OFFLINE | LLM 可选，量化照常 |
| NO_ACTION | 管线完整但无调仓，正常 |
| NOT_ACTIONABLE / BLOCKED | 证据不足，不交易是正确结果 |

**总原则：看不懂就不交易；红色就停；黄色先看核心管线是否绿。**
