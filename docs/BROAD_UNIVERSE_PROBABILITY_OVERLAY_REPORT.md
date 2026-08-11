# Broad Universe & Probability Overlay Closure Report

## 1. Executive Summary

本轮完成了 broad-universe 与 probability-overlay 的生产架构闭环，但没有制造生产批准：

- Alpha 股票池不再直接取固定 18-symbol bootstrap。正式选择从 Nasdaq Trader 当前全市场目录开始，经证券类型、PIT 数据、流动性、特征完整性逐层缩小。
- 2026-08-10 实际运行读取 8,833 个当前上市证券；7,475 个非测试、非 ETF 证券；4,957 个保守识别的普通股；受本地已认证行情覆盖限制，最终 factor eligible 为 9。
- ETF 与指数不进入股票横截面排名；SPY/QQQ 为 benchmark，其他 ETF 仅可作为风险参考或既有持仓。
- Probability Overlay 已接入真实 expected-return → portfolio → recommendation 因果路径，但最新运行没有合格 artifact，因此状态为 `RESEARCH_ONLY`，Base Alpha 保持不变。
- 历史 research data 仍为 `NOT_CERTIFIABLE`，策略仍为 `DIAGNOSTIC_ONLY`，最新 daily run 为 `VALID_ANALYSIS_NON_ACTIONABLE`，0 个正式操作。

## 2. 修改前 Architecture

旧路径为 `DEFAULT_SYMBOLS` / `MINIMUM_US_RESEARCH_UNIVERSE` → symbol registry → certified daily snapshot → stock 与 ETF 混合价格截面 → factor/alpha。18 个 bootstrap symbol 同时承担下载、benchmark、风险参考和 Alpha 截面的职责。

旧 probability 路径只把 calibration/evidence 用于 confidence 展示；`expected_excess_return`、portfolio target 和 recommendation 没有正式 consumer。

## 3. 修改后 Architecture

正式路径为：

`Official Current Directory → Current Security Master → PIT Visibility → Security Type → Data Quality → t-1 Liquidity → Factor Eligibility → Equity-only Cross Section → Base Alpha → Gated Probability Overlay → Expected Return → Portfolio → Risk → Recommendation`

固定 18-symbol tuple 仅保留为增量数据 bootstrap/reference 兼容层，不再定义 Alpha universe。最终 optimizer 只接收当日 Alpha 合格股票与当前实际持仓；未持有的 benchmark/risk reference 不进入优化。

## 4. Universe 数据来源

- 当前上市 metadata：Nasdaq Trader `nasdaqlisted.txt` 与 `otherlisted.txt`。
- 最新真实目录：provider retrieved at `2026-08-11T16:59:53.836827+00:00`，source timestamp `0811202612:11`。
- 当前目录 content hash：`4af011716456c1a37851b7c43a3002db5f77049592331fce3ace16a0701bc57e`。
- 价格/成交量/PIT total return：现有已认证 daily database；目录本身不被误当作历史 membership 数据。
- Provider capability 明确声明：当前目录不提供 historical membership、delisting、identifier history、PIT corporate-action vintages 或 total-return vintages。

## 5. Universe 过滤规则

默认允许 XNYS、XNAS、XASE 普通股；ADR/REIT 必须显式开启，当前均关闭。默认排除 ETF、ETN、preferred、warrant、rights、units、closed-end fund、OTC、测试证券和异常 financial status。

数据/可交易性门槛：price ≥ $5；至少 252 个 session；t-1 及以前 20-session ADV 与 median dollar volume 均 ≥ $10m；valid-bar coverage ≥ 98%；missing ratio ≤ 2%；corporate-action integrity 与 feature availability 必须成立。任何 future observation 直接 fail closed。

## 6. 当前实际 Universe Size

| 层级 | 数量 |
|---|---:|
| US listed securities | 8,833 |
| Listed non-test/non-ETF | 7,475 |
| Conservative common-stock type eligible | 4,957 |
| Data eligible | 9 |
| Liquidity eligible | 9 |
| Factor eligible | 9 |
| Signal eligible | 9 |

因此已经摆脱“固定 18 个 symbol 定义 Alpha universe”的软件结构，但尚未获得覆盖数千股票的合格 PIT 价格/公司行动数据。9 不是配置目标，而是本次真实数据覆盖经过门禁后的结果。

## 7. PIT / Survivorship 状态

当前 daily 截面为 `CURRENT_PIT_ONLY`：目录、价格与 eligibility observation 均要求 `available_at <= decision_time`；ADV 只读取 `trade_date < universe_date`。同一可见 PIT 内容的 eligibility content hash 可复现。

历史 survivorship 状态仍为 `UNVERIFIED`。当前目录禁止倒填历史；缺 historical membership、delistings、permanent identifier history、PIT corporate actions 与 PIT total-return vintages。因此不能声明 survivorship-safe，也不能用本次 current universe 进行历史 production certification。

## 8. ETF / Benchmark Segregation

Alpha factors 与排名只消费 `alpha_price_frame`（普通股）。SPY/QQQ 只用于同 PIT benchmark。其他 ETF 可进入 risk-return history 或覆盖已有持仓，但其 sector 标记为 `REFERENCE:*`、size exposure 为中性值，且不生成股票 Alpha。指数/VIX 继续为 optional regime/reference，不会被当作股票。

## 9. Factor Pipeline

Momentum、trend、low-volatility 仍按既有冻结定义计算。winsorization、robust normalization、sector centering 与 PIT market-cap residualization 只在当日 factor-eligible equity 截面内执行。缺 sector/size/coverage 证据时维持 `NOT_VALIDATED`，未降低门槛。

新增不变量覆盖未来 membership、future observation、t-1 ADV、ETF/ADR/warrant 排除、专业数据门槛与确定性 hash。隔离 E2E 的 sector fixture 也已改为在 equity-only 截面自身满足原有中性化要求，不再借 ETF 凑分组。

## 10. Probability Pipeline

正式职责是估计经过 locked OOS 校准的 benchmark-relative residual return，而不是显示一个上涨百分比。每个 evidence 绑定 symbol、condition、样本数、wins/losses、raw/prior/posterior、credible interval、expected residual return、available time、model/data version。

`ProductionDailyQuantInputAssembler.assemble_research()` 调用 `apply_probability_overlay()`；其输出 signals 进入 `DailyQuantInput`。`portfolio.construction._expected_returns()` 随后读取每个 `AlphaSignal.expected_excess_return`。这是 probability 的真实生产 consumer 链。

## 11. Calibration 方法

基础 calibration 增加 Brier、log loss、ECE、reliability bins、calibration slope/intercept。Overlay approval 最少要求 252 locked-OOS sessions、4 个 walk-forward folds、ECE ≤ 0.05、slope 0.8–1.2、|intercept| ≤ 0.10，并要求比 base Brier、net Sharpe 与 benchmark alpha 有增量。

最新真实运行 N=0，所有 calibration metrics 为 null，状态 `PROBABILITY_NOT_CALIBRATED`；没有输出虚假概率。

## 12. Overlay Formula / Mechanism

唯一允许机制为 `OOS_NET_RESIDUAL_SHRINKAGE`：

`adjusted expected excess return = base expected excess return + capped(shrinkage × locked-OOS expected residual return)`

它不是 `probability × alpha`。系数、cap、condition whitelist、multiple-testing 方法及 exact identity 全部绑定 immutable artifact。只有 artifact 为 `PRODUCTION_APPROVED` 才执行。

## 13. 无数据泄漏说明

Universe、price feature、factor、probability evidence 均检查 available time。目录或 observation 在 decision time 之后不可见；future row 会 fail closed。Probability label/evidence 只能来自 artifact 内的 train/validation/embargo/locked-OOS 分割；运行时 evidence 的 `as_of`、`available_at`、model/data identity 均必须匹配。

## 14. Production Approval Gate

Overlay 状态包括 `RESEARCH_ONLY / VALIDATING / PRODUCTION_APPROVED / REJECTED / DEGRADED`。批准同时要求：research dataset certified、exact strategy/parameter/data/universe/model/calibration identity、locked OOS、walk-forward、multiple-testing control、校准通过、成本已进入 residual 与 PnL、net OOS 指标相对 BASE 改善。

artifact 缺失、损坏、未来可用、identity 不匹配、样本不足或校准/OOS 失败时，系统返回原始 Base signals，不阻塞 deterministic core，也不改变 recommendation。

## 15. BASE vs OVERLAY OOS Results

真实结论：`NOT_EXECUTED / INSUFFICIENT_CERTIFIED_RESEARCH_DATA`。当前没有 survivorship-safe historical dataset，不能合法打开 locked OOS，也没有 BASE 与 OVERLAY 的 after-cost 比较。未生成任何 production approval artifact。

## 16. Transaction Costs / Slippage

Gate 要求 commission、spread、slippage、impact 真正进入 overlay residual 与组合 PnL；approval policy 要求 `costs_included=true` 和 `residual_return_net_of_costs=true`。最新 overlay 没有运行 OOS，因此成本后 metrics 为 null，而不是假设为零。

## 17. Benchmark Comparison

正式比较绑定 SPY，并保留 QQQ 辅助基准，二者使用与策略相同的 completed-session PIT convention。最新 daily benchmark 数据可用，但这不构成 Overlay OOS comparison。

## 18. Portfolio Impact

受控因果链测试证明：相同 market data、base alpha、portfolio 与 risk，仅切换为 exact-match `PRODUCTION_APPROVED` evidence 时，D 的 expected excess return 可由 1.1% 变为 2.1%，进而改变 target weight 与非 HOLD recommendation。该数值只存在于 `TEST_FIXTURE`，不是市场结论。

真实 latest run 中 overlay inactive，所以 expected return、rank、target 和 recommendation 均未改变；正式操作为 0。

## 19. Risk Impact

Broad universe 后，风险输入明确分为 equity Alpha 与 reference/current-holding history。sector、single-name、size、liquidity、beta、volatility、turnover、HHI、correlation 与成本门禁保持不变。参考 ETF 不参与股票中性化，但已有参考资产持仓仍可被测量、约束和减仓。

## 20. Tests

- Ruff：通过。
- strict mypy：360 个源码文件通过。
- Full pytest：639 tests passed in 51.87s。
- 专项：26 tests passed，覆盖 current directory classification、PIT membership/available time、t-1 ADV、hash reproducibility、overlay approval/fallback、exact identity、immutable hash、causal expected-return→weight→recommendation、以及完整 portfolio E2E。
- 真实 daily 连续双跑：canonical input/result、directory、eligibility、factor/candidate counts 与 classification 全部一致。

## 21. Known Limitations

1. 当前 metadata provider 仅提供 current listings，不提供历史 lifecycle/membership。
2. 本地已认证行情只覆盖 broad directory 中 9 个普通股，因此当前横截面仍小，不能代表目标 4,957-stock 范围。
3. 无合格历史 dataset，无法执行 BASE vs OVERLAY locked OOS。
4. Probability calibration N=0；Market Regime 仍 optional unavailable。

## 22. Remaining Blockers

按优先级：

1. `HISTORICAL_MEMBERSHIP_INCOMPLETE` / `DELISTING_HISTORY_INCOMPLETE`。
2. `SECURITY_IDENTIFIER_HISTORY_INCOMPLETE`。
3. `CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE` / `PIT_TOTAL_RETURN_HISTORY_INCOMPLETE`。
4. 数千股票的可靠、增量式 PIT OHLCV/volume coverage 尚未建立。
5. `LOCKED_OOS_EVIDENCE_UNAVAILABLE`、`BASE_OVERLAY_AFTER_COST_COMPARISON_UNAVAILABLE`、`CALIBRATION_EVIDENCE_UNAVAILABLE`。

## 23. Production Readiness

- Broad current-universe architecture：已落地。
- Historical PIT/survivorship certification：未达到，`NOT_CERTIFIABLE`。
- USAdaptiveAlphaCoreV1：`DIAGNOSTIC_ONLY`。
- Probability Overlay：`RESEARCH_ONLY`，真实 production path 已接线但 inactive。
- Daily analysis：可运行且可复现；最新到 SIGNAL gate 后因策略未批准而 fail closed。
- Live recommendation：当前不可合法生成。

机器证书：`artifacts/latest/universe_certification.json` 与 `artifacts/latest/probability_overlay_certification.json`。两者由 `scripts/export_broad_universe_probability_certifications.py` 从真实 run/config/cache 生成并计算 canonical artifact hash。
