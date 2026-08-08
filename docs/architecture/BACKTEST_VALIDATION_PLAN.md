# Backtest Validation Plan

## 冻结协议

在任何正式结果前冻结：数据快照 ID 与哈希、样本区间、Universe 规则、因子公式、事件规则、调仓频率、成本模型、假设族、训练/验证/测试边界和主要评价门禁。Locked Test 打开后不得反复调参；失败即记录失败，下一版本使用新的预注册协议。

## 数据要求

- point-in-time S&P 500/研究股票池与退市证券；
- 公司行动 announcement/available/effective time；
- 决策时可得的 PIT total-return OHLCV；
- NYSE/NASDAQ 交易日历、时区和下一可交易开盘；
- earnings 与 fundamentals 的真实 available time；
- 数据冲突、复权和缺失全部通过认证。

当前这些真实数据条件未全部满足，因此正式回测状态为 **NOT RUN / BLOCKED**。

## 基准

SPY、VOO、QQQ、数据期允许时 QQQM、等权 S&P 500、简单 12-1 动量、简单 200 日均线、原项目策略。基准必须使用一致现金流、分红、税费、汇率和执行口径。

## 验证设计

1. chronological Train / Validation / Locked Test；
2. 标签窗口 purging 与边界 embargo；
3. expanding/rolling walk-forward；
4. 下一可交易时点成交，不能同一收盘价看见又成交；
5. commission、fee、spread、slippage、税费和 FX 可配置；
6. prior ADV 容量与不可成交整次调仓处理；
7. 参数扰动、时间/股票池/状态切片；
8. moving-block Bootstrap 或 Monte Carlo 路径稳健性；
9. 预注册假设族的 FDR/Bonferroni；
10. 每个 Sleeve 与 Ensemble 分开报告成本、换手、回撤和失效环境。

## 指标与多目标门禁

报告 CAGR、相对 SPY 超额、IR、Sharpe、Sortino、Calmar、最大回撤及持续时间、CVaR、最差日/月/季/年、月胜率、滚动 1/3 年超额、Beta、Alpha、换手、总成本、容量、暴露、策略/因子贡献、现金和尾部损失。

门禁阈值不在代码中武断写死。冻结研究协议应依据样本长度和策略周期确定，并至少要求：OOS 不依赖少数年份/股票；参数扰动不崩溃；扣费后有正证据；回撤与收益匹配；相对简单基准有增量；收益可成交。任何单项高 CAGR 都不能覆盖数据或风险失败。

## 市场切片

单独报告牛市、熊市、震荡、危机反弹、高波动、高相关性，以及 2008、2020、2022、2023–2025。禁止只展示成功案例。现有历史报告明确尚无认证冻结数据，因此不引用其占位结果为策略证据。

