# Dashboard 数据口径与交互说明

Personal Alpha Terminal 首页是研究摘要页，不是行情撮合终端。它只读取已经写入数据库且
状态为 `completed` 的最近结果；失败、运行中和未达到统计门槛的结果不会被包装成机会。

## 首页信息架构

| 区域 | 主要数据源 | 展示规则 |
|---|---|---|
| Market Overview | `prices`、`market_regime_runs` | 主要指数最新两个交易日、状态概率和输入完整度 |
| Alpha Center | `event_study_*`、`conditional_probability_*`、`relationship_*` | 仅展示最新完成运行；事件和概率必须满足最小样本门槛 |
| Portfolio | `portfolio_risk_runs`、`portfolio_risk_metrics` | 展示最新完成风险快照和前五大权重 |
| Research | `research_reports`、`factor_research_runs`、`backtest_runs` | 各取最近完成结果；AI 与确定性报告明确区分 |

首页聚合查询都有明确上限，页面数据缓存 45 秒。交互图表支持悬停、缩放、框选和导出；
响应式布局会在窄屏自动改为纵向。动画只用于轻量进入和悬停反馈，并遵守操作系统的
`prefers-reduced-motion` 设置。

## 风险等级口径

首页风险等级是可解释的提醒规则，不是预测概率：

- 首页任一指数数据超过 7 个自然日，或指数数据完全缺失：加 2 分；
- 市场状态为 Risk-Off：加 2 分；Neutral：加 1 分；
- 组合最大回撤不高于 -20%：加 2 分；不高于 -10%：加 1 分；
- 组合年化波动率不低于 30%：加 1 分。

总分 3 分及以上为 High，1–2 分为 Elevated，0 分为 Controlled。缺少输入时页面会
明确提示数据不足，不推断为低风险。

## 关键限制

- “今日事件”只有在事件日期与首页最新市场日期一致时才标记为今日，否则标记为最近触发。
- 条件概率展示贝叶斯平滑结果及置信区间，但历史条件概率不构成未来收益承诺。
- 组合首页的年化收益来自当前权重历史回放，不等于不可变交易账本计算的真实业绩。
- AI 报告只有在数据库中存在带来源的数据报告时展示；缺少密钥或证据时保留空状态。
- 首页数据新鲜度取各分析模块最近更新时间，不代表所有市场都已同步收盘。

## 启动

```powershell
streamlit run src/personal_alpha_terminal/dashboard/app.py
```

主题默认使用暗色模式。Streamlit 原生侧边栏可用于页面导航，图表工具栏用于交互与导出。
