# Deterministic Decision Engine

Personal Alpha Terminal 1.0.0 将研究结果与人工组合操作之间增加了独立、可审计的决策层。

## 数据流

`ResearchDataGate → Quant inputs → DecisionEngine → Action Center → Human review → Paper order`

- 输入只允许来自确定性代码：因子评分、Market Regime Score、风险评分、条件证据、组合优化目标和当前持仓。
- AI 输出不是 `DecisionCandidate` 的字段，不能改变排名、目标权重、操作或风险门禁。
- `ResearchDataGate` 非 `APPROVED` 时，运行结果只能是 `BLOCKED`，且建议集合为空。
- 条件证据小于最小样本、未校准、无锁定样本外验证、过期或时间戳位于决策之后时，候选被拒绝。
- 建议在信号生成之后的下一可交易时点才能执行。

## 可解释输出

每条建议保存：

- `factor`、`regime`、`risk`、`conditional` 和 `portfolio_target_delta` 的独立贡献；
- 当前权重、目标权重和建议股数；
- 数据来源、样本量、证据等级、风险因素、最早执行时间和失效时间；
- 量化评分与证据可信度评分。

证据可信度是来源、样本、样本外验证、校准和新鲜度的质量评分，不是上涨概率。

## 人工确认

接受、拒绝和观望写入不可变 `decision_history`。接受 BUY/SELL 只创建 `paper_decision_orders`，不会创建真实交易流水，也不会改变 `portfolio_positions`。

## 安全限制

- 不连接券商，不自动下单。
- 无数据、数据冲突或认证不足时显示 `No Decision Generated`。
- 历史和模拟结果不保证未来表现。
- 真实数据认证与实盘认证是独立门禁，不因产品版本号而自动通过。
