# Conditional Probability Overlay

## 职责

该层估计“条件发生后，未来收益分布相对无条件基准如何变化”，不预测确定价格，也不能独立触发重仓。核心量为：

`Probability Lift = P(positive return | condition) - P(positive return)`

必须同时保留条件概率、无条件概率、Lift、原始样本量、有效样本量、区间、平均/中位收益、5% 尾部、最大不利收益、扣成本期望、窗口、状态、数据年龄和证据等级。

## 已实现的统计保护

- 事件可用时间检查与 right censoring；
- 同日去重和持有窗口 overlap removal；
- 默认最少 30 个条件样本；
- 基于 lag-1 自相关折扣的 effective sample size；
- Beta-Binomial 平滑；
- Wilson/后验区间与 Lift 保守区间；
- moving-block Bootstrap 收益区间；
- Fisher exact 原始检验；
- hypothesis family 内 Benjamini-Hochberg FDR；
- OOS、校准、漂移、新鲜度和证据衰减门禁；
- 小样本、区间过宽、成本后期望非正或 Lift 不确定时输出“证据不足”。

Bonferroni 已在 Market Graph/Lead-Lag 候选关系层保留；Conditional Overlay 使用 FDR 管理预注册假设族。不得先扫描无限条件再只报告显著结果。

## 决策规则

Overlay 可以提高/降低已有信号的可信度、排序和仓位上限。正向修正受 `positive_overlay_limit` 限制；负向修正允许更强，以符合本金保护的不对称目标。以下任一情况禁止作为仓位证据：数据质量 BLOCKED、非 OOS、未通过校准、发生漂移、样本不足、ESS 不足、FDR 不通过、数据过期。

Graph 只生成候选；Event Study 定义事件和异常反应；本模块量化条件证据；Backtest 验证可交易性；Portfolio Engine 决定风险容量。相关、Granger 或图边都不得表述为因果。

## 尚未完成

真实市场条件族尚未预注册；没有冻结 OOS 概率预测序列，因而没有真实 Brier Score、reliability curve 或漂移基线。当前校准、漂移和 Bootstrap 测试使用确定性夹具，只证明实现行为，不证明 Alpha。真实数据认证前本层维持 Experimental。

