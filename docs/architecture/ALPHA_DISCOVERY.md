# Alpha Discovery Engine

Alpha Discovery Engine 用于从历史数据中生成和淘汰可解释的因子假设。它不预测价格、不生成
交易指令，也不会把训练集最优结果包装成 Alpha。

## 因子库

| 类别 | 因子 | 口径 |
|---|---|---|
| 价值 | PE、PB、PS、FCF Yield | 估值使用当日原始收盘价 |
| 成长 | Revenue Growth、EPS Growth | 同一财务来源、点时同比 |
| 质量 | ROE、ROIC、Gross Margin、Debt Ratio | `available_at` 早于市场收盘 |
| 动量 | 1M、3M、6M、12M | 21/63/126/252 个交易日复权收益 |
| 波动 | 3M Volatility、6M Maximum Drawdown | 复权日收益和价格路径 |
| 技术 | MA20/60 Distance、Wilder RSI14、MACD(12,26,9) | 均使用复权收盘价 |
| 市场环境 | VIX、利率、美元指数、市场宽度 | 每日只有一个市场样本 |

市场环境因子不会复制到每只股票后把股票数当成独立样本。其 IC 使用每个日期唯一的环境值
与当日等权市场未来收益进行时间序列相关分析。

## IC 方法

股票因子先在每个截面日期计算：

```text
IC_t = Spearman(factor_rank_t, forward_return_t+h)
```

然后以 IC 日期序列计算均值、中位数、标准差、ICIR、正向比例和单样本 t 检验。Pearson IC
仅作为线性敏感性对照。统计样本量是有效日期数，不是股票行数。

低值优先因子会保留原始 IC，同时报告方向调整 IC：

```text
directional_ic = raw_ic × (-1 for low-is-better factors)
```

## 防过拟合控制

1. 再平衡间隔不得短于未来收益窗口。
2. Train / Validation / Test 按日期顺序切分，不随机打乱。
3. 分区边界会清除标签终点触及下一分区的样本。
4. 训练集只负责筛选单因子。
5. 验证集负责选择等权、方向调整的因子组合。
6. 测试集在组合排名冻结后才计算。
7. 因子筛选和组合筛选分别使用 Benjamini-Hochberg FDR。
8. 高相关因子组合被拒绝；组合最多三个因子。
9. 测试失败的候选保留为 `test_not_confirmed`，不会隐藏。

测试集结果不能再次用于修改因子、方向、权重或阈值；任何修改都必须建立新研究版本和新测试
区间。

## 运行

先确保数据库包含足够长的复权价格和点时基本面记录：

```powershell
python -m personal_alpha_terminal.scripts.run_alpha_discovery `
  --market US `
  --start-date 2015-01-01 `
  --end-date 2025-12-31 `
  --horizon 21 `
  --rebalance-interval 21
```

默认每个 Train / Validation / Test 至少需要 12 个非重叠日期，每个截面至少 20 只股票。
数据不足会明确失败，而不是降低门槛或填充模拟结果。

结果保存到：

- `alpha_discovery_runs`
- `alpha_factor_evaluations`
- `alpha_combination_results`
- `research_reports`，其中 `report_type = alpha_discovery`

`data_fingerprint` 对因子定义、形成日期、证券、因子值和未来收益做 SHA256，可用于确认两次
研究是否使用完全相同的输入。

## Alpha 报告

报告包含适用市场、研究区间、数据指纹、数据来源、切分日期、IC、FDR q-value、组合的
训练/验证/锁定测试结果、因子定义、风险和失效条件。

证据质量上限为 80，表示样本、显著性和跨期稳定性的综合等级，不是未来成功概率。

## 已知限制

- 当前股票池仍受历史证券主数据和退市覆盖限制。
- close-to-close IC 不是可成交价格回测；实盘研究必须增加下一可成交价、成本和滑点。
- 停牌证券的未来交易日窗口可能跨越更长自然日；重叠标签会被剔除。
- 免费复权和基本面数据可能发生历史修订。
- 宏观因子相关性不构成因果证据。
- 产业、国家、规模和市场状态中性化尚未作为默认 IC 口径实现。
