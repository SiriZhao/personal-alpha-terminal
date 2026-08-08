# US Adaptive Alpha Research Strategy v0.1

## 定位与结论

本框架以 Capital Preservation Objective 为首要约束，在证据允许时研究长期风险调整后 Alpha。它不是本金保证、指数点位预测器或自动交易系统。股票、ETF、短债代理和现金管理工具都可能亏损；历史与模拟结果不保证未来表现。

当前状态：**研究工程已实现并通过本地测试；真实数据验证未完成；不可进入真实资金；仅可进入前向观察。** 数据不足或数据门禁失败时，不生成目标组合是正常输出。

## 架构

```text
Certified point-in-time data
  -> independent Sleeve signal
  -> Conditional Evidence overlay
  -> Market Regime score/budget overlay
  -> Momentum Crash risk reduction
  -> Portfolio and liquidity constraints
  -> research grade + position range + trace ids
```

各 Sleeve 独立生成信号、成本、回撤和 OOS 证据；任一 Sleeve 的异常不会污染其他 Sleeve。组合层只接收通过能力和数据门禁的结果。

| Sleeve | v0.1 状态 | 说明 |
|---|---|---|
| Price Momentum | Experimental | 仅 PIT total-return 数据认证后可研究 |
| Quality-Constrained Momentum | Disabled | 缺 PIT fundamentals 认证 |
| Sector Rotation | Isolated | 避免与个股动量重复计票 |
| Post-Earnings Drift | Disabled | 缺可靠 earnings available time |
| Market Regime | Score-only overlay | 未校准不得称 Probability |
| Conditional Probability | Experimental overlay | 不能单独创建持仓 |
| Graph / Lead-Lag | Watchlist only | 非因果、不能直接给仓位 |
| Defensive Allocation | Cash only | 防御 ETF 需另行认证 |
| Experimental Sleeve | Hard-capped | 默认资金上限 5%，当前仍为研究零资本 |

## 因子与权重

同一趋势暴露中的 12-1、6M、3M、MA、MACD、距 52 周高点和趋势斜率只能作为 Momentum Sleeve 的子组件，不得跨 Sleeve 重复分配资本。财务因子必须满足 `available_time <= decision_cutoff`，否则自动禁用。

`factor_weighting.compare_factor_weighting` 比较等权、理论固定权重、滚动 IC、风险约束和正则化五种方法。接口刻意不接受 locked-test 数据；复杂方法只有在验证集改善超过不确定性门槛时才被选择，否则回退等权。参数敏感性和真实 OOS 比较仍待冻结数据完成。

## 决策拆解

每个标的保留：基础请求权重、条件证据乘数、市场状态乘数、Momentum Crash 乘数、风险约束后权重、建议区间、阻断原因、失效条件与 trace IDs。条件证据只能修正已有正向基础信号；负向或证据不足的基础信号不能被概率层升级为持仓。

## 已实现与未实现

已实现：fail-closed 数据能力门禁、Sleeve 注册、条件证据统计、FDR、校准/漂移检查、平滑市场风险预算、Momentum Crash 连续削减、组合约束、五种资产配置、五种因子权重比较、阶段门禁和 Streamlit 研究页。

已测试：22 项新模块定向测试；项目完整本地套件 279/279；全项目 Ruff 与严格 mypy 通过。

仅设计/待数据：真实 QCM 信号生产、行业中性化、真实 Sleeve 收益序列、税费/券商点差、短债 ETF 防御分配、完整基准套件、冻结 OOS、前向观察。

安全阻断：没有明确认证标志时，即使数据库存在少量数据，也不得打开 PIT universe、fundamentals、公司行动、基准或校准能力。
