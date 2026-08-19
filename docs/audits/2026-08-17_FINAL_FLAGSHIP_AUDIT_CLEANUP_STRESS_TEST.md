# Personal Alpha Terminal 旗舰量化系统审计、深度清理与合成极端压力测试

- 审计日期：2026-08-17
- 审计基线：`0b094db`（分支 `feature/agentic-quant-intelligence-round42-51`，相对远端领先 10 个提交）
- 当前版本：`1.2.0-rc.1`
- 压力证据：`reports/flagship-synthetic-stress/flagship_synthetic_stress.json`
- 压力证据 ID：`flagship-stress-2e327554ee1bd305`
- 结论边界：本报告不构成投资建议，不声称历史业绩、已证实 Alpha 或实盘可用性

## 1. 执行摘要

Personal Alpha Terminal 已经具备较强的工程安全骨架：唯一生产决策链、显式 PIT/数据/信号/组合/风险门禁、不可变证据哈希、严格人工执行边界、概率与 LLM 的零影响回退、广泛自动化测试，以及对缺失数据和未来数据的 fail-closed 处理。当前系统更接近一个“工程成熟、证据不足的人工量化决策终端”，而不是一个已经证明有 Alpha 的生产策略。

本次审计没有发现 P0 Critical。发现并修复了一项 P1 研究验证缺陷：Deflated Sharpe 的期望最大 Sharpe 公式实现错误，旧实现会低估多重试验选择偏差并高估 deflated Sharpe。该缺陷位于研究证据层；当前 Alpha 本来就未获历史生产认证，因此没有改变正式生产权重。

新的第一性原理合成压力测试通过真实 `USAdaptiveAlphaCoreV1 → DailyQuantPipeline → Risk Model → Dynamic Risk Budget → SLSQP Optimizer → Stress Gate → Trade Generator → Decision Engine` 链运行 10 个场景。所有场景保持 long-only、总敞口不超过 100%、概率正式影响 0%、LLM 正式影响 0%，未来/缺失/陈旧数据均正确阻塞。与此同时，10 个场景都至少一次出现优化器迭代上限；3 个场景出现 no-trade 后的单名上限失败。系统安全地阻塞，但可能在最需要减仓时无法给出可执行的去风险计划。

仓库清理删除了 pytest/mypy/ruff 缓存、旧审计 scratch、5 组 pytest basetemp、无引用且未被使用的 `.venv-old` 和 Python 缓存，约回收 484 MiB。正式账本、研究数据、运行证据、forward ledgers、备份和关键认证工件全部保留。

最终判断：可进入受控、人工、只观察/前向纸面验证阶段；不具备真实资金资格；当前没有已证明 Alpha，也无法给出可信年化收益区间。

## 2. 项目当前总体评级

| 维度 | 评级 | 结论 |
|---|---:|---|
| 工程就绪度 | B+ | 门禁、类型、测试、审计、人工执行边界较强；优化器压力可靠性和巨型模块拖累 |
| 量化完整性 | B- | 当前 PIT 操作链较严谨；历史 PIT、退市、标识和总收益数据不完整 |
| 合成压力鲁棒性 | C+ | 不变量全部保持且故障安全，但优化器在全部场景出现阶段性阻塞 |
| Forward evidence 成熟度 | D- | 真实预测 0、成熟结果 0、有效配对 N=0 |
| Paper/Shadow readiness | B-（有条件） | 适合人工 forward shadow；不等于自动 paper account 或可交易 Alpha |
| Real-capital readiness | F / 未就绪 | 历史认证、OOS、forward、优化器压力恢复均未闭环 |
| Alpha 证据 | D / 未证明 | 只有模型假设、当前截面输出和合成场景；没有可信历史/OOS/forward Alpha |
| 综合评级 | C+ | 工程平台明显领先于策略证据成熟度 |

## 3. 系统架构审计

### 3.1 实际生产链

当前唯一正式链为：

`CALENDAR → DATA → PIT → FEATURE → FACTOR → ALPHA → SIGNAL → PORTFOLIO → RISK/STRESS → DECISION → MANUAL EXECUTION PLAN → PERSISTENCE`

`ApplicationService.run_daily_quant_report()` 调用 `DailyQuantOrchestrator`；量化核心最终进入 `DailyQuantPipeline`。终端 renderer 只消费不可变 `DailyQuantResult`，不重新计算因子、权重或动作。这一边界在实现与测试中一致。

### 3.2 优势

- 数据、策略参数、组合约束、风险模型、成本模型、运营策略和审批工件均有独立身份哈希。
- 阶段 manifest 串联输入/输出哈希，run certificate 绑定最终链根。
- 研究与日常操作数据分层；当前上市目录不会被冒充为历史成分股。
- 数据、PIT、未来数据、信号、组合、风险、决策任一硬门禁失败都会清空可执行腿。
- 正式组合只有一个人工维护账本；接受建议不会修改持仓，只有真实手工 fill 才更新现金和持仓。
- LLM、新闻和概率模块失败不会降低 Classical Quant Core 的门禁。

### 3.3 主要架构风险

- 代码规模已达约 496 个源文件；`terminal/cli.py` 约 3,867 行、`daily_orchestrator.py` 约 3,303 行、`daily_renderer.py` 约 2,041 行、`forward_shadow_operations.py` 约 1,717 行。模块边界存在，但编排与终端层已形成高认知负担。
- 多个 Round 审计/阶段性模块仍位于 `src/`，增加长期维护面和重复语义风险。
- `docs/CURRENT_STATUS.*` 仍基于 2026-08-15 的旧提交，而当前 HEAD 已到 Round59；“当前真相”文档存在时效漂移。
- `pyproject.toml` 使用依赖范围但没有提交跨平台锁文件；可重复安装弱于代码级可重复运行。

## 4. 数据与 PIT 完整性审计

### 4.1 当前操作链

当前 forward/daily 操作数据链具有以下已实现控制：

- 每条价格记录含事件时间、可用时间、摄取时间和 provider lineage。
- 未来可用记录在特征、横截面和生产输入层均被过滤或阻塞。
- 当前 Nasdaq Trader 目录明确标记为 `CURRENT_OPERATIONAL_PIT` / current listings only。
- 股票、ETF、指数和 benchmark 角色分离；SPY/QQQ 不进入普通股横截面 Alpha 排名。
- 最低价格、历史长度、覆盖率、缺失率、ADV、median dollar volume、公司行动连续性和特征可用性逐级过滤。
- 重复日期、错误标的、币种/单位错误、周末 bar、收盘前可用时间、极端调整收益、冻结 OHLC、长缺口和零成交量序列都有质量检查。
- Benchmark 与策略使用同一 PIT return frame 和同一 cutoff。

### 4.2 公司行动与标识

`PointInTimeTotalReturnBuilder` 使用永久证券 ID、不可变 action/revision ID 和可用时间；split、reverse split、stock dividend、cash dividend 有显式计算。merger consideration、spin-off、rights、delisting payment、ADR ratio change 没有明确估值时直接 fail closed，这是正确的保守边界。

### 4.3 未闭环证据

当前 `historical_data_acquisition.json` 明确显示：

- 历史 membership 行数 0；membership coverage 0%。
- delisted count 0，unknown lifecycle count 8,833。
- 缺历史 identifier history、delisting return、PIT corporate actions 和 PIT total-return vintages。
- 实际价格覆盖仅约 2024-08-07 至 2026-08-11，低于研究基线所需区间。
- Benchmark PIT total-return convention 尚未完整认证。

因此 `NOT_CERTIFIABLE` 是正确状态。这里是“证据不足”，不是软件 bug。

## 5. Alpha / 因子 / 概率模型审计

### 5.1 当前正式 Champion 的真实内容

`USAdaptiveAlphaCoreV1` 当前实际使用：

- 12-1 momentum：252 日回看，跳过最近 21 日。
- 126 日 log-price trend slope。
- 63 日低波动因子。
- 横截面 1%/99% winsorization、robust z-score、行业中位数中心化、log market-cap 残差化。
- 21-session 预期超额收益系数：momentum 0.006、trend 0.003、low-vol 0.002。

`quality_coefficient=0.0`，因此当前 Champion 并没有正式质量因子贡献；value、growth、fundamental quality 也不在最终权重链。`quality_constrained_medium_term_momentum` 的信号名比实际因子内容更宽泛。

### 5.2 预期收益语义

因子输出先产生 21-session expected excess return，组合层再按 `252/horizon` 年化并进行衰减。该语义在代码中一致，但系数属于 engineering-default / provisional 参数，没有可信历史 OOS 校准。数值可作为排序/优化输入，不能解释为已验证的真实年化 Alpha。

### 5.3 Deflated Sharpe 缺陷

旧实现把第二个分位点写成 `(1-1/N)^e`，而注释和标准近似要求 `1-1/(N·e)`。这会低估多试验下的期望最大 Sharpe，从而高估 deflated Sharpe。

本次已修复，并新增精确公式回归测试。该修复提高研究证据保守性，不改变当前正式生产策略，因为历史研究认证仍为 `NOT_CERTIFIABLE`。

### 5.4 Probability Overlay

概率 overlay 的正式 consumer 链存在，且只有 exact identity、完整哈希、locked OOS、walk-forward、after-cost、multiple-testing 和 calibration 全部合格才会修改 expected return。

当前工件状态：

- `RESEARCH_ONLY`
- locked OOS sessions = 0
- sample size = 0
- production effects = 0
- ranking/target/recommendation 均未改变
- fallback = `BASE_FACTOR_ALPHA`

概率模块当前对最终建议的正式影响确实为 0%，不是“实现了但偷偷生效”。

## 6. 组合构建与风险控制审计

### 6.1 组合约束

默认约束包括：单名 12%、行业 30%、相关簇 35%、HHI 0.18、最低现金 10%、最大 gross 90%、目标波动 15%、beta 0 至 1.05、L1 turnover 30%、size exposure 0.35、ADV participation 2%。

候选全集直接进入 optimizer，没有固定 Top-N 截断，也没有固定持仓数量上限。实际持仓数量由预期收益、风险、成本、流动性和最小交易阈值共同决定。

### 6.2 已确认优势

- SLSQP 结果经过 long-only、gross、单名、换手、HHI、波动、beta、size、行业和相关簇二次校验。
- 交易成本模型在 optimizer 和 trade generator 共用，避免优化与执行成本语义分叉。
- ADV participation 超限会直接拒绝交易，而不是静默缩小成本。
- 风险模型使用 Ledoit-Wolf shrinkage、PSD 修正和 condition-number 检查；失稳时可降级为 diagonal covariance，再失败则阻塞。
- 风险预算根据 drawdown、realized volatility、correlation jump 和 HHI 收缩 gross/position budget。

### 6.3 已确认问题

1. 10 个合成场景均至少一次出现 `optimizer failed: Iteration limit reached`。系统没有生成非法权重，但 blocked decision 比例达到 1/5 至 4/5。
2. 中度熊市、快速交替、行业崩盘和流动性冲击出现 `single-name limit failed after no-trade processing`。当前持仓因价格漂移略高于 12% 时，no-trade band 可能保留旧权重，随后硬约束校验又拒绝整个目标，形成约束死锁。
3. 严重风险下 `allow_new_risk=False` 时，只要存在一个未持有且 expected return 为正的证券，当前实现会阻塞整个构建，而不是继续生成“只减仓/只卖出”的去风险目标。
4. 合成行业崩盘和极端离散场景中，决策间持仓漂移的最大单名权重约达到 17%。12% 是 rebalance target 限制，不是连续监控/强制减仓限制。
5. 风险模型可同时处理 1,171 个证券，但实质是高维样本协方差 shrinkage；252 至 376 个观察对 1,171 维风险面仍有较高估计不确定性。

## 7. LLM / 新闻 / 事件系统审计

### 7.1 当前权限

当前 LLM event/company/debate/semantic alpha 路径为 `SHADOW`：

- production lambda = 0
- formal economic influence = 0%
- production source = Quant-only
- optimizer 仍是最终权重权威
- auto execution = disabled
- manual confirmation = enabled

即使构造 `PROMOTION_PASS`，默认 `LLMInfluencePolicy` 仍未启用且 Level 1 不能产生正式 lambda。本次“LLM 与 Quant 完全相反”探针验证 `mu_final == mu_quant`。

### 7.2 信息价值与风险

结构化事件、证据 ID、时间 cutoff、prompt/model/version/hash、token、成本和 schema validation 有较强审计性；外部文本被视为不可信数据，不能改系统 prompt 或生成交易。

但当前没有真实配对 forward outcome，无法证明 LLM 增量信息价值。代码中已经存在 Level 2-5 和 bounded overlay 结构，未来若开放权限，必须经过独立版本、真实 forward evidence、回撤/换手约束和人工批准；现阶段不应提高决策影响。

## 8. 回测、OOS 与 Forward Evidence 审计

### 8.1 Backtest 实现质量

生产 backtest engine 使用 raw execution price、next-session execution、现金/持仓/成本会计、公司行动、PIT universe、stale-price limit、benchmark/alpha/risk attribution，并校验最终 PnL accounting invariant。研究框架还包含 purged walk-forward、embargo、FDR、non-overlapping label、parameter perturbation 和 data-mining risk。

### 8.2 当前证据状态

| 证据层 | 当前状态 | 可支持的结论 |
|---|---|---|
| 历史回测 | `NOT_CERTIFIABLE` | 不能用于可信年化收益/Alpha 估计 |
| Locked OOS | 0 sessions | 不能证明概率、因子或组合增量价值 |
| Forward Quant | 没有成熟、独立、足量样本 | 不能证明稳定性或 Alpha |
| Forward LLM Shadow | real predictions 0；matured outcomes 0；paired N=0 | 只能证明运行与治理基础设施 |
| 合成压力 | 本次 10 场景 | 只能证明数值/约束/故障行为，不能证明收益 |

当前 forward shadow 基础设施具备 session identity、不可变预测/结果、maturity calendar、exact-session outcome 和 promotion evaluator，但“基础设施存在”不等于“证据已经积累”。

## 9. 工程质量与开源项目成熟度

### 9.1 最终门禁

- 全量 pytest：`1338 passed, 1 warning`
- Quant-critical：`6 passed`
- 新增旗舰压力与故障探针：`3 passed`
- Ruff：PASS
- mypy strict：PASS，496 个源文件
- Secret scan：`SECRET_SCAN_PASS`

### 9.2 安全与配置

- `.env`、真实账本、报告、缓存和个人交易数据均由 Git 忽略。
- 配置文件不包含持仓或密钥；持仓只来自账本。
- secrets scan 有自动测试覆盖。
- 无 broker API、无自动下单、无模拟 fill 自动写账。

### 9.3 开源成熟度缺口

- `pyproject.toml` 声明 `Proprietary`，仓库不具备真正开源许可证条件。
- 没有提交依赖锁文件/SBOM 的稳定发布绑定；依赖范围可能随时间漂移。
- 巨型 orchestrator/CLI/renderer 降低可维护性和审查局部性。
- 当前状态文档落后于代码和测试事实。
- Python 3.14 下 SQLite 默认 datetime adapter 有 1 条 deprecation warning。

## 10. 项目清理内容与前后变化

### 10.1 删除内容

| 类别 | 处理 |
|---|---|
| `.mypy_cache` 与 Round53/54/55 mypy caches | 删除 |
| `.pytest_cache`、`.pytest-tmp`、全部 `.pytest-tmp-*` | 删除 |
| `reports/pytest-basetemp-*` 5 组 | 删除 |
| `.ruff_cache`、`.codex-temp`、Python `__pycache__`/bytecode | 删除 |
| `audit-tmp` | 删除 |
| `.venv-old` | 确认无代码引用、无进程使用后删除 |
| `.gitignore` | 增加 `.mypy-cache-*/`、`/audit-tmp/`、pytest basetemp 防复发规则 |

首次清理回收约 484 MiB；最终验证又生成并随后移除了 88.95 MiB 测试/字节码缓存，该临时增量不计入首次回收量。部分 Python 3.14 pytest 目录带异常 ACL，本次只对已验证的临时目录重置自身 ACL 后删除。

### 10.2 明确保留

- `.venv` 当前有效环境。
- `var/operational`、`var/research-data`、`var/backups`、概率/forward/LLM ledgers。
- `reports/daily-runs`、`reports/data-snapshots`、`reports/evidence-bundles`、`reports/validation-artifacts`。
- `data/cache`、当前 broad-universe 数据和关键 provenance。
- `artifacts/latest` 下所有认证/阻塞工件。

内置 `maintenance artifacts cleanup --dry-run` 返回 0 个到期文件，因此没有越过仓库 retention policy 删除正式证据。

## 11. 五类及扩展合成市场压力测试

### 11.1 方法

- 完全本地、固定种子、第一性原理生成。
- 使用虚构 2099 日历，明确避免历史危机数据和历史趋势查询。
- 24 个合成证券、6 个行业、260 个 warmup sessions、105 个压力 sessions、21-session rebalance。
- 五类核心 benchmark 终值被约束为 -75%、-50%、-22%、+4%、+45%。
- 每个决策点重新运行正式因子、风险模型、风险预算、optimizer、stress gate、交易和决策链。
- 收益按实际生成的可执行目标和 blocked/no-action 行为滚动计算。

### 11.2 结果

以下全部是“合成场景结果”，不是历史业绩或收益预测。

| 场景 | 组合收益 | 基准收益 | 超额 | 波动 | 最大回撤 | 平均现金 | 平均持仓 | L1换手 | 成本拖累 | Ready/Blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 极端系统性崩盘 | -25.06% | -75.00% | +49.94% | 27.87% | -16.57% | 84.33% | 5.8 | 0.458 | 0.485% | 4/1 |
| 严重熊市 | -21.88% | -50.00% | +28.12% | 20.80% | -25.86% | 67.56% | 7.2 | 0.898 | 0.373% | 4/1 |
| 中度熊市 | -12.77% | -22.00% | +9.23% | 14.76% | -16.71% | 50.88% | 12.2 | 0.600 | 0.125% | 2/3 |
| 正常混合 | -1.10% | +4.00% | -5.10% | 8.66% | -4.06% | 43.64% | 11.6 | 0.598 | 0.033% | 2/3 |
| 强势牛市 | +21.18% | +45.00% | -23.82% | 12.52% | -3.59% | 47.77% | 10.8 | 0.600 | 0.033% | 2/3 |
| 因子反转/动量崩溃 | -2.70% | -12.00% | +9.30% | 15.89% | -9.86% | 61.89% | 10.8 | 0.294 | 0.016% | 1/4 |
| 快速交替/假突破 | -2.02% | 0.00% | -2.02% | 19.16% | -8.64% | 64.46% | 8.0 | 0.599 | 0.033% | 2/3 |
| 集中行业崩盘/轮动 | -11.32% | -18.00% | +6.68% | 20.22% | -19.84% | 33.33% | 12.0 | 0.300 | 0.017% | 1/4 |
| 流动性/滑点爆炸 | -11.26% | -20.00% | +8.74% | 18.70% | -14.88% | 45.47% | 12.0 | 0.300 | 0.421% | 1/4 |
| 极端离散/优化器稳定性 | +6.48% | +8.00% | -1.52% | 18.66% | -13.57% | 64.91% | 7.0 | 0.865 | 0.048% | 4/1 |

### 11.3 解释

- 崩盘场景的相对收益主要来自高现金和低 gross，不是已证明 Alpha。
- 强牛市只捕获约一半基准涨幅，显示防守型现金配置有明显机会成本。
- 正常、快速切换和强牛市的相对收益为负，说明系统并非稳定 benchmark-beater。
- 流动性/滑点场景成本拖累升至约 0.42%，成本模型确实影响目标和收益。
- 因子反转场景损失小于基准，但 4/5 决策阻塞，不能据此认定因子鲁棒。

## 12. 极端尾部风险与系统失效模式

### 12.1 通过项

- 所有场景 long-only 保持。
- gross 始终不超过 100%。
- 没有 NaN/Inf 权重或负资产净值。
- 没有固定 Top-N 或固定持仓上限被引入。
- 概率 unavailable 时回退 Classical，不改变 signals。
- LLM 与 Quant 冲突时正式影响保持 0。
- 未来时间戳、缺失数据坍塌、陈旧授权均 fail closed。

### 12.2 失效模式

1. **优化器无可执行恢复路径**：iteration limit 后直接 blocked；没有保守的可行投影或 sell-only fallback。
2. **no-trade 与硬约束冲突**：no-trade 保留轻微超限持仓，后置校验拒绝整个组合。
3. **连续风险控制不足**：目标权重合规不代表两个 rebalance 之间持续合规；最大漂移约 17%。
4. **去风险阻塞**：severe risk budget 可阻塞全部新构建，而不是允许纯减仓。
5. **高现金依赖**：尾部保护效果高度依赖现金；在牛市产生显著 underparticipation。
6. **静态成本假设**：即使将 spread/slippage 放大 25 倍，仍是日频确定性模型，不包含订单簿、开盘竞价、partial fill 和非线性冲击路径。

## 13. 收益 / Alpha 能力评估

### 13.1 四类证据分离

| 类型 | 当前证据 | 结论 |
|---|---|---|
| 历史/OOS | 历史数据 `NOT_CERTIFIABLE`；locked OOS=0 | 不能估计可信年化收益或历史 Alpha |
| Forward | real paired N=0；matured outcomes=0 | 尚无前向 Alpha 证据 |
| 合成压力 | 本报告 10 场景 | 证明安全行为和风险暴露，不证明预测能力 |
| 理论/模型隐含 | momentum/trend/low-vol 工程系数 | 正 Alpha 在理论上可想象，但项目特定置信度很低 |

### 13.2 直接回答

- **系统当前有 demonstrated alpha 吗？** 没有。
- **正 expected alpha 合理吗？** 作为中期 momentum/trend/low-vol 的理论先验，低置信度下“可能”；作为该项目的已验证结论，不成立。
- **能否给出可信年化收益？** 不能。任何点估计或窄区间都会制造虚假精度。
- **适合 forward paper/shadow 吗？** 有条件适合：人工、只读/手工执行、保留 blocked/no-action、每日记录真实结果。
- **适合真实资金吗？** 不适合。

## 14. 当前优势

- 对 PIT、未来数据、当前/历史 universe 边界的认识明显高于一般个人量化项目。
- 失败时不伪造因子、概率、风险或交易。
- 人工执行、真实 fill、账本和不可变证据边界清晰。
- 概率和 LLM 都有实际 consumer/forward 基础设施，但当前严格保持零生产影响。
- 组合没有硬编码 Top-N/持仓数，optimizer 接收完整候选集合。
- 测试、mypy、ruff、secret scan 和量化不变量覆盖较强。
- 数据、参数、成本、风险、组合与运行证据身份分离，审计性好。

## 15. P0/P1/P2/P3 问题清单

| ID | 级别 | 类型 | 问题 | 状态 |
|---|---|---|---|---|
| P0 | Critical | - | 未发现会绕过 PIT/风险/人工执行并自动下单的缺陷 | 无 |
| P1-01 | High | confirmed defect | Deflated Sharpe 多试验期望最大值公式错误 | 本次已修复并回归测试 |
| P1-02 | High | confirmed defect | 全部 10 个压力场景出现阶段性 SLSQP iteration-limit | 未修复；保持 fail closed |
| P1-03 | High | confirmed defect | no-trade 后处理可保留超限旧权重，随后硬约束拒绝整个目标 | 未修复；需约束感知后处理 |
| P1-04 | High | design limitation | severe risk 下缺 sell-only / risk-reduction fallback | 未修复；涉及组合语义，需独立审批 |
| P1-05 | High | insufficient evidence | 历史 membership、退市、标识、公司行动、PIT total return 不完整 | 数据采购/构建前无法关闭 |
| P1-06 | High | insufficient evidence | 无可信历史 OOS、无成熟 forward、无 demonstrated Alpha | 需时间与真实数据 |
| P1-07 | High | design limitation | Champion 实际只有 momentum/trend/low-vol；quality/value/growth 未正式参与 | 需研究认证，不应直接加权 |
| P1-08 | High | design limitation | 两次 rebalance 间单名漂移可超过 12%，合成最大约 17% | 需连续风险监控/强制减仓规则研究 |
| P2-01 | Medium | design limitation | 1,171 维风险面主要依赖短样本 shrinkage covariance | 需 robust/factor risk 对照验证 |
| P2-02 | Medium | design limitation | 成本模型是静态日频 bps + sqrt participation | 真实 fill 校准不足 |
| P2-03 | Medium | design limitation | Regime 当前 observation-only，风险反应主要滞后于 realized risk | 符合保守策略，但保护延迟 |
| P2-04 | Medium | confirmed defect | `CURRENT_STATUS` 落后于当前 HEAD/Round59 | 应由验证流水线更新 |
| P2-05 | Medium | design limitation | 多个 1,000-3,800 行巨型模块降低可维护性 | 应按稳定边界渐进拆分 |
| P2-06 | Medium | confirmed limitation | Proprietary license + 无依赖锁，不满足旗舰开源发布标准 | 发布前需决策与补齐 |
| P3-01 | Low | confirmed defect | Python 3.14 SQLite datetime adapter deprecation warning | 后续迁移显式 adapter |
| P3-02 | Low | confirmed defect | `quality_constrained` 命名与 quality 权重 0 的事实不完全一致 | 文档/命名应更精确 |

## 16. 后续升级建议与优先级

### 最高优先级

1. 为 optimizer 增加不改变风险上限的确定性可行解恢复：约束投影、当前组合去风险投影、sell-only fallback；任何 fallback 仍必须经过全部后置约束。
2. 使 no-trade/minimum trade 规则对硬约束超限让路：若当前持仓违反单名/行业/gross/风险限制，风险修复交易不得被 no-trade band 吞掉。
3. 建立“只减仓不增仓”模式的独立不变量与测试，避免 severe risk 时整个建议链阻塞。
4. 获取或构建可认证的历史 membership、delisting、identifier、PIT corporate actions 和 total-return 数据；在此之前保持 `NOT_CERTIFIABLE`。

### 第二优先级

5. 用 factor-risk / robust covariance / resampled optimization 与当前 Ledoit-Wolf 方案做 locked OOS 对照，不直接替换生产模型。
6. 用真实手工 fills 校准 spread、slippage、impact 和开盘可执行性误差。
7. 累积至少一个完整市场周期的 forward observations；概率至少满足 252 locked-OOS sessions，LLM 至少满足现行 120 observations / 40 sessions 等门槛，并要求 after-cost 增量证据。
8. 自动生成并校验 `CURRENT_STATUS`，绑定 HEAD、测试结果和当前运行证据。

### 工程维护

9. 渐进拆分 CLI、orchestrator 和 renderer，不改量化语义。
10. 若目标是开源，选择许可证、增加依赖锁/可重复构建和 release SBOM 验证。

## 17. Paper Trading / Real Capital readiness

### Paper / Forward Shadow

结论：**有条件就绪**。

允许范围：

- 继续 Quant-only 正式源和 LLM zero-authority。
- 手工确认、手工券商执行或纯观察，不增加自动 paper account。
- 每个决策保存 run certificate、目标、blocked reason、实际 fill、成本和 outcome。
- blocked/no-action 必须视为真实结果，不能人工挑选成功样本。
- 优先观察 optimizer blocked rate、实际现金利用、单名漂移和成本偏差。

### Real Capital

结论：**未就绪**。

至少需要：

- survivorship-safe 历史数据认证。
- locked OOS / walk-forward / after-cost 结果。
- 足量独立 forward sessions 和成熟 outcomes。
- optimizer 压力恢复路径关闭 P1-02/P1-03/P1-04。
- 真实 fill 成本校准和生产 parity 验证。
- 明确的人类资本额度、最大损失和紧急停止制度。

## 18. 最终结论

Personal Alpha Terminal 的核心价值目前是“严格、可审计、不会轻易越权的量化决策基础设施”，而不是“已证明能持续跑赢市场的策略”。工程门禁和人工执行边界已经达到较高水平；数据历史、Alpha 证据和压力下的优化器可用性明显落后。

本次清理没有损害正式证据，本次代码修复没有改变生产 Alpha/组合/风险政策。本次压力测试证明系统在极端条件下通常会安全阻塞，而不是生成非法交易；但 blocked 不能被等同于有效风险管理，因为现实持仓会继续承受市场风险。

最终 verdict：

- Engineering readiness：`B+`
- Quant integrity：`B-`
- Synthetic stress robustness：`C+ / PASS_WITH_WARNINGS`
- Forward evidence maturity：`D-`
- Paper-trading readiness：`CONDITIONAL YES / MANUAL FORWARD SHADOW`
- Real-capital readiness：`NO`
- Alpha evidence：`NOT DEMONSTRATED`
- Overall grade：`C+`
