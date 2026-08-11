# Chinese Terminal Architecture

## 边界

终端采用 `Engine → immutable DailyQuantResult → Renderer`。引擎和持久化只使用稳定英文 enum/code；`zh-CN` 与 `en-US` 是纯显示映射，默认中文。Renderer 不重新计算 feature、factor、alpha、target、risk、cost 或 action，也不能修改 result。

## 信息层级

1. 今日量化总览：日期、分析/交易日、市场、cutoff、run id、耗时和数据/量化/组合/风险/交易状态。
2. 今日操作清单：合法时显示 BUY/SELL/HOLD/NO_ACTION；阻塞时立即显示唯一主要原因。
3. 投资组合与基准：NAV、现金、持仓、权重、文本 allocation bar；前向记录和 SPY/QQQ 的样本状态。
4. 数据与量化：Data Certification、PIT/股票池、Data Health、Alpha candidate、Probability。
5. 风险与执行：风险 evidence/gauge、raw→risk-adjusted target、外部券商手工执行计划和现金恒等式。
6. 审计：拒绝原因、主要/次要/可选 blocker、完整 stage pipeline、run certificate、今日总结。

Candidate、正式 Signal、风险批准 Decision、外部实际 Fill 分属不同对象和状态，中文展示不会合并这些语义。

## 颜色与宽度

- 绿色：PASS/正常；黄色：degraded、optional unavailable、insufficient sample；红色：真正 blocking；灰色：not run；蓝色：标题/信息。
- `display_width` 按 Unicode East Asian Width 和 combining mark 计算中英文 cell 宽度；Rich 负责表格折行。
- 低宽度终端减少辅助列但保留数值和 blocker。图表使用 `█` 表示已用量，ASCII `-` 表示余量：避免 U+2591 在旧 Windows GBK code page 触发编码崩溃。
- 图表只表达 result 中已有数值；数值始终是 source of truth。

## Locale 等价性

CLI `--locale zh-CN|en-US` 把同一个 `DailyQuantResult` 交给 renderer。回归测试比较渲染前后的 dataclass 内容、核心 blocker、金额和 run id，确保语言变化不会改变算法业务结果。
