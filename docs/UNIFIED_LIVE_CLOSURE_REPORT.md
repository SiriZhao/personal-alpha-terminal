# Unified Live Closure Report

Date: 2026-08-11

## 结论

系统现只有一套正式 daily quant path 和一个用户维护账本 `main`。本地 `main` 已初始化为 USD 100,000、零持仓、NAV 100,000；初始现金以不可变 deposit 事件落账。程序不自动下单，用户确认与真实外部成交回填继续分离。

当前状态是 **VALID_ANALYSIS_NON_ACTIONABLE**：live DATA、PIT、FEATURE、FACTOR 正常，组合账本就绪；SIGNAL 因 `USAdaptiveAlphaCoreV1` 没有真实 `PRODUCTION_APPROVED` artifact 而严格阻塞，后续 portfolio construction、risk、decision、execution plan 不运行且操作数为 0。

## 软件收口

- 删除第二套交易产品代码、CLI、运行目录与产品文档；正确的账本、人工确认、实际 fill、next-session、费用、NAV/PnL 和审计能力统一使用既有正式模块。
- config/CLI 以唯一名称 `main` 选择组合，数据库仍保留安全的整数外键；`portfolio-init/show/import/update` 均支持该稳定身份。
- 初始化现金不再是 UI 默认值，而是数据库中的可审计入金事件；删除了经核验无持仓、无交易的旧 `$1,000,000` 空账本。
- 修复策略阻塞时 cash-only 组合实际 cash/invested 权重错误复用目标权重的问题。
- 修复因 SIGNAL 门禁失败而把已经完成的 DATA/PIT/FEATURE/FACTOR 分析误分为 invalid 的状态语义；交易 `actionable` 条件没有放宽。
- Renderer 只消费 `DailyQuantResult`；zh-CN/en-US 不进入引擎、哈希、gate 或 persistence。

## Blocker 分类

- `SOFTWARE_BLOCKER`: 0（正式组合选择、状态传播、Windows 图表编码和 locale 接线已修复）。
- `DATA_BLOCKER`: historical membership、delisting、security identifier history、PIT corporate actions、PIT total return、dataset-bound calendar 不完整。
- `STRATEGY_BLOCKER`: 没有 252+ locked OOS、walk-forward、survivorship-safe、same-PIT benchmark 和 after-cost 稳定性证据；批准注册表为空。

## E2E

真实本地 no-refresh daily 使用 `main`：DATA/PIT/FEATURE/FACTOR `PASS`，SIGNAL
`FAIL_BLOCKING`，组合 NAV/cash 100,000、现金权重 100%，正式 action 0。固定时间双跑得到
相同 canonical input hash
`9e87711e864879b2125fcf08495daeb02c0a894a129e1bde3aea77235dd38ac7` 和 canonical
result hash `f0ef0aaab8c6d0057023e25c84ebb80e9863457af7f6fa7b7203097c7458b574`。
run ID 属于每次运行身份，按设计不同。

前向实际运行记录从此使用 daily certificates + 正式 portfolio transaction/fill ledger 积累。当前尚无第一个同步收盘观察期，因此 Portfolio/SPY/QQQ 归一化曲线与 Sharpe/CAGR/Sortino/年化 alpha 均诚实显示 `INSUFFICIENT_SAMPLE`。

## 安全边界

生产认证门槛未修改；没有创建 approval artifact、没有推荐 BUY/SELL、没有连接 broker、没有伪造概率或 regime。Charles Schwab / 外部券商仅手动执行。

验证：Ruff PASS；strict mypy PASS（357 source files）；full pytest **617 passed in
57.42s**；repository secret scan PASS。Git/GitHub push 证据在最终交付中记录。
