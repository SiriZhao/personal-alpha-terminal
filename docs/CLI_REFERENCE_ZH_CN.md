# Personal Alpha Terminal — CLI 命令参考（中文）

> 本文档从 `src/personal_alpha_terminal/terminal/cli.py` 的
> `build_parser()` 与 `main()` 逐条核对，只描述代码中真实存在的命令。
> 命令名、参数、默认值与代码一致（基准：v1.1.0）。

可执行入口：`PersonalAlphaTerminal.exe`（发布版）或
`.\.venv\Scripts\python.exe main.py`（开发环境）。下文以 `pat` 代指。

---

## 全局选项（所有命令可用）

| 选项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--config` | 路径 | `config.yaml` | 指定配置文件路径 |
| `--no-refresh` | 开关 | 关 | 跳过市场数据刷新，直接用库内数据运行 |

**不带任何子命令**时，默认执行 `daily`（即 `pat` ≡ `pat daily`）。

---

## 1. daily — 运行并渲染完整每日量化链路

```text
pat daily
pat --no-refresh
```

- **用途**：刷新市场数据（除非 `--no-refresh`）→ 跑完整 12 阶段管线
  → 渲染终端 → 持久化不可变运行证书。
- **输出**：HEADER、PIPELINE、DATA CERTIFICATION、……、TODAY SUMMARY
  全套区块；证书写入 `reports/daily-runs/<run_id>/`。
- **失败情况**：配置缺失、数据库不可写、数据认证失败等会报错并以
  退出码 2 结束；数据不足时管线自身会 fail-closed（显示 BLOCKED，
  不产生交易）。

## 2. refresh — 强制刷新数据后运行

```text
pat refresh
```

- **用途**：等价于 `daily`，但**强制**刷新市场数据（忽略 `--no-refresh`）。
- **输出 / 失败**：同 `daily`。

## 3. data / factors / probability / risk / decisions — 查看已持久化区块

```text
pat data     [--run-id <run_id>]
pat factors  [--run-id <run_id>]
pat probability [--run-id <run_id>]
pat risk     [--run-id <run_id>]
pat decisions [--run-id <run_id>]
```

- **参数**：`--run-id`（可选）。省略时使用**最新一份**运行证书。
- **用途**：不重新计算，只从 `reports/daily-runs/<run_id>/run_certificate.json`
  读取并渲染对应区块的不可变证据。
- **输出**：JSON 面板 + 证书文件路径。
- **失败情况**：找不到任何已持久化运行时报
  `NO_PERSISTED_RUN; run daily or refresh first`（退出码 2）；
  指定了不存在的 run-id 同样报错。

## 4. doctor / diagnostics — 启动健康检查

```text
pat doctor
pat diagnostics   # doctor 的别名
```

- **用途**：检查配置、provider 顺序、缓存/报告目录可写性、数据库、
  迁移状态、数据目录、时区/日历、组合账本、LLM 可选状态等。
- **输出**：`PERSONAL ALPHA TERMINAL - DOCTOR` 表，逐项 PASS / WARN / FAIL。
- **失败情况**：任何一项 FAIL → 退出码 2。
  `Optional fallback data` 未配置只是 WARN（不影响日常运行）。

## 5. settings — 显示当前有效配置

```text
pat settings
```

- **用途**：以 JSON 输出当前生效的终端配置（含 `runtime_config_hash`
  与 `canonical_run_config_hash`）。
- **输出**：配置 JSON。
- **失败情况**：配置文件缺失或非法 → 退出码 2。

## 6. version — 显示版本

```text
pat version
```

- **输出**：`Personal Alpha Terminal <版本号>`。

## 7. research — 运行审计研究管线

```text
pat research
```

- **用途**：运行研究流水线（data → feature → factor → signal，
  不含组合/风险/决策）。
- **输出**：`Research pipeline: <status>`、run date、报告路径。
- **失败情况**：数据就绪闸门不允许研究时，显示
  `Research workflow blocked` 面板并以退出码 3 结束；
  研究失败以退出码 2 结束。

## 8. backtest — 检查 PIT 回测执行闸门

```text
pat backtest
```

- **用途**：检查历史回测是否被允许执行（PIT 门控）。
- **输出**：`Historical Backtest: <status>` 面板与原因。
- **失败情况**：闸门不允许（如历史成分/退市证据不足）→ 退出码 3。

## 9. init-config — 生成默认配置文件

```text
pat init-config
```

- **用途**：若 `config.yaml` 不存在则写入默认配置。
- **输出**：`Created configuration: <path>`。
- **失败情况**：配置已存在时提示 `Configuration already exists` 并
  以退出码 0 结束（不覆盖）。

## 10. data-provider status / test — 可选数据提供方诊断

```text
pat data-provider status
pat data-provider test twelve-data
pat data-provider test alpha-vantage
```

- **参数**：`test` 子命令必须指定 provider（`twelve-data` 或 `alpha-vantage`）。
- **用途**：查看/测试**可选**的独立数据源（用于诊断与降级），
  **不运行策略、不改动组合**。
- **输出**：`status` 显示各 provider 的角色/配置/可达性/最新会话；
  `test` 显示 `PASS latest=... rows=... cache=...` 或失败类别。
- **失败情况**：provider 未配置或请求失败 → 退出码 3。
  这些是可选服务，`NOT_CONFIGURED` 不影响日常就绪。

## 11. accept / reject / watch — 记录人工审阅结论

```text
pat accept  <recommendation_id> --run-id <run_id> [--reason "<文本>"]
pat reject  <recommendation_id> --run-id <run_id> [--reason "<文本>"]
pat watch   <recommendation_id> --run-id <run_id> [--reason "<文本>"]
```

- **参数**：
  - `recommendation_id`（位置参数，必填）：建议 ID；
  - `--run-id`（必填）：建议所属的运行 ID；
  - `--reason`（可选）：审阅备注。
- **用途**：记录你对某条正式决策建议的人工审阅结论。
  **ACCEPT 不会改变持仓、不会下单。**
- **失败情况**：`recommendation_id` 未绑定到指定 run 时报
  `recommendation ... is not bound to immutable run ...`（退出码 2）。

## 12. mark-executed — 录入真实成交

```text
pat mark-executed <recommendation_id> --run-id <run_id> --price 100.50 --quantity 10 [--fees 0] [--fill-id <id>] [--timestamp <ISO>] [--notes "<文本>"] [--external-reference <id>]
```

- **参数**：
  - `recommendation_id`（位置，必填）、`--run-id`（必填）；
  - `--price`（必填，float）：成交价；
  - `--quantity`（必填，float）：成交数量；
  - `--fees`（可选，float，默认 0）：手续费；
  - `--fill-id`（可选）：**唯一**成交标识，多笔部分成交必须各不相同；
  - `--timestamp`（可选）：成交时间；
  - `--notes` / `--external-reference`（可选）：备注 / 外部引用。
- **用途**：把你在 Schwab 手工成交的一笔录入账本，**真实更新股数与现金**。
  部分成交累计不得超过批准数量，未填满时订单保持 `PARTIAL`（重启安全）。
- **失败情况**：run 绑定校验失败、fill-id 重复、累计超量等会报错。

## 13. cancel-execution — 取消执行

```text
pat cancel-execution <recommendation_id> --run-id <run_id> --reason "<文本>"
```

- **参数**：`recommendation_id`（位置，必填）、`--run-id`（必填）、
  `--reason`（必填，审计原因）。
- **用途**：取消一条尚未完成的执行。**不会联系 Schwab。**
- **失败情况**：run 绑定校验失败或状态不允许取消时报错。

## 14. modify-execution — 修改执行数量

```text
pat modify-execution <recommendation_id> --run-id <run_id> --quantity 20 --reason "<文本>"
```

- **参数**：`recommendation_id`（位置，必填）、`--run-id`（必填）、
  `--quantity`（必填，float）、`--reason`（必填）。
- **用途**：调整未执行订单的批准数量。**不会联系 Schwab。**
- **失败情况**：run 绑定校验失败或状态不允许修改时报错。

## 15. portfolio-init — 初始化真实组合账本

```text
# 交互式向导（推荐）
pat portfolio-init

# 非交互（脚本）
pat portfolio-init --name "My Portfolio" --cash 25000 --position AAPL=10:150.25 --position SPY=5
```

- **参数**：
  - `--name`（可选，默认 `My Portfolio`）：组合名称；
  - `--cash`（可选，float）：现金余额。**传了 `--cash` 就不进交互向导**；
  - `--currency`（可选，默认 `USD`）；
  - `--position`（可选，可重复）：`TICKER=SHARES[:AVERAGE_COST]`。
- **交互向导触发条件**：终端可交互（stdin 是 TTY）且未设
  `PAT_NONINTERACTIVE=1` 且未传 `--cash`。向导逐步询问名称/现金/持仓，
  支持 `cancel`、错误重输、最终确认（y/N）。
- **校验**：cash ≥ 0、shares ≥ 0（不支持做空）、ticker 非空且合法、
  无 NaN/Inf、无重复 ticker。
- **保存**：原子事务（要么全部保存，要么完全不保存）。
- **输出**：`Created portfolio id=<N>; broker connection: NONE`。
- **失败情况**：向导中取消 → 退出码 1；非交互未给 `--cash` → 报错；
  校验失败 → 提示重新输入或报错。

## 16. portfolio-import — 从 CSV 导入持仓

```text
# 预览（默认，不写入）
pat portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10

# 提交（真实写入）
pat portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --commit

# 显式指定现金
pat portfolio-import my_holdings.csv --portfolio-id 1 --as-of 2026-08-10 --cash 25000 --commit
```

- **参数**：
  - `csv`（位置，必填）：CSV 文件路径；
  - `--portfolio-id`（必填，int）：目标组合 ID；
  - `--as-of`（必填）：持仓生效日期 `YYYY-MM-DD`；
  - `--commit`（开关）：真正写入账本；缺省只预览；
  - `--cash`（可选，float）：显式现金覆盖，**省略时绝不偷偷假定现金**。
- **CSV 格式**：表头 `ticker,shares`（兼容 `symbol,quantity`），
  可选列 `average_cost` / `cost_basis`；UTF-8 编码。
- **校验**：schema、重复 ticker、非正股数（0 与负数都拒绝）、NaN/Inf、损坏文件；
  失败时明确指出错误位置，不写入任何数据。
- **现金行为**：`--cash` 与 CSV 内 CASH 行都缺省时，保留组合现有现金不变，
  绝不假定现金。
- **输出**：预览显示将导入的内容；commit 后更新账本。
- **失败情况**：文件不存在/损坏、组合 ID 不存在、校验失败 → 退出码 2。

## 17. portfolio-list / portfolio — 列出组合

```text
pat portfolio-list
pat portfolio      # 别名
```

- **用途**：列出所有真实组合账本（id / 名称 / 货币 / 现金）。
- **输出**：组合列表。无组合时显示
  `QUANT ANALYSIS READY · PORTFOLIO REQUIRED · TRADING BLOCKED` 提示
  并以退出码 3 结束。

## 18. portfolio-show — 查看单个组合详情

```text
pat portfolio-show --portfolio-id 1
```

- **参数**：`--portfolio-id`（必填，int）。
- **用途**：显示指定组合的 id / 名称 / 货币 / 现金 / as_of，
  以及逐持仓明细（Ticker / Shares / Average cost）。
- **失败情况**：组合 ID 不存在 → 报错。

## 19. explain — 解释某个标的的决策证据链

```text
pat explain AAPL [--run-id <run_id>]
```

- **参数**：`symbol`（位置，必填）；`--run-id`（可选，默认最新证书）。
- **用途**：从运行证书读取该标的的 `decision_traces`，逐条展示证据。
- **输出**：`DECISION TRACE / <SYMBOL> / <run_id>` 表 + 证书路径 +
  `LLM contribution: NONE`。
- **失败情况**：该标的不在这次运行中 → 退出码 2。

---

## 退出码约定

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 用户取消（如 portfolio-init 向导取消） |
| 2 | 命令执行失败（文件/IO/运行时/参数错误，或 doctor 有 FAIL） |
| 3 | 闸门阻塞（research/backtest/provider test 被门控拦截） |

---

## 命令速查表

| 命令 | 一句话用途 |
|---|---|
| `daily` | 跑完整每日链路并渲染（默认命令） |
| `refresh` | 强制刷新数据后跑链路 |
| `data` / `factors` / `probability` / `risk` / `decisions` | 查看已持久化的对应区块 |
| `doctor` / `diagnostics` | 启动健康检查 |
| `settings` | 显示有效配置与哈希 |
| `version` | 显示版本 |
| `research` | 跑研究管线 |
| `backtest` | 检查 PIT 回测闸门 |
| `init-config` | 生成默认 config.yaml |
| `data-provider status` / `test` | 可选数据源诊断 |
| `accept` / `reject` / `watch` | 记录人工审阅 |
| `mark-executed` | 录入真实成交 |
| `cancel-execution` / `modify-execution` | 取消/修改执行 |
| `portfolio-init` | 初始化真实组合 |
| `portfolio-import` | 从 CSV 导入持仓 |
| `portfolio-list` / `portfolio` | 列出组合 |
| `portfolio-show` | 查看组合详情 |
| `explain` | 解释某标的的决策证据链 |
