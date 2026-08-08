# Scenario Simulator

Scenario Simulator 用于回答“如果一组明确假设发生，当前组合在给定线性敏感度下会怎样变化”。
它不是价格预测器，也不会给出发生概率、目标价格或交易指令。

## 1. 架构

```text
当前组合风险快照
        +
版本化资产—因子映射
        +
有来源标签的情景冲击
        ↓
ScenarioEngine
        ↓
资产影响 → 组合影响 → 区间 / 覆盖率 / 证据质量
        ↓
ORM 审计快照 + Scenario Report + Dashboard 图表
```

核心代码位于 `src/personal_alpha_terminal/scenario_simulator/`：

- `schemas.py`：带单位和不变量校验的领域对象。
- `catalog.py`：风险因子字典、直接指数代理映射和内置模板。
- `calibration.py`：从同一历史窗口、已注明来源的序列校准冲击。
- `engine.py`：确定性敏感度计算、覆盖率、区间和证据质量。
- `repository.py`：版本化映射、不可变情景定义、运行与资产结果。
- `service.py`：读取已完成组合估值、运行、保存报告和多情景比较。
- `report.py`：确定性 Scenario Report 和图表载荷。

## 2. 风险因子与单位

| 因子 | 单位 | 敏感度含义 |
|---|---|---|
| NASDAQ / S&P 500 / 中国股票 | `decimal_return` | 因子变化 1% 对资产收益的变化 |
| 联邦基金利率 / 美国 10 年期收益率 | `basis_points` | 因子变化 100bp 对资产收益的变化 |
| 美元指数 / 原油 / 黄金 | `decimal_return` | 因子变化 1% 对资产收益的变化 |
| 中国增长状态 | `standard_score` | 状态分数变化 1 单位对资产收益的变化 |

美元指数是宏观经济敏感度；非基准币种持仓的直接汇率换算是另一条独立输入，二者不能混用。

## 3. 计算方法

对资产 \(i\)：

```text
factor_return_i = Σ(sensitivity_i,f × normalized_shock_f)
asset_return_i = (1 + factor_return_i) × (1 + currency_return_i) - 1
portfolio_return = Σ(current_weight_i × asset_return_i)
```

利率冲击按 `magnitude_bp / 100` 转为“每 100bp”单位。现金收益固定为零。资产损失下限为
-100%。敏感性区间分别使用每条映射的低/高系数，并对负冲击进行符号安全排序；它不是统计
置信区间。

## 4. 资产—风险因子映射

映射必须包含：

- 资产、风险因子和截至日期；
- 中心敏感度及低/高界；
- 方法、数据来源和 0–100 的证据质量。

系统只自动提供接近恒等的代理映射：

- `QQQ` / `QQQM` → NASDAQ；
- `SPY` / `VOO` / `IVV` → S&P 500；
- `GLD` / `IAU` → 黄金；
- `USO` / `BNO` → 原油。

系统不会替单只股票虚构 Beta、久期或商品敏感度。未映射资产在计算中按不变处理，并明确计入
`uncovered_weight`；这通常会低估风险。Dashboard 可登记带来源说明的版本化映射。

## 5. 内置情景

- 2008 Financial Crisis Proxy；
- 2020 Pandemic Drawdown Proxy；
- 2022 Tightening Cycle Proxy；
- AI Valuation Unwind；
- China Economic Recovery。

前三项是近似的历史种子模板，不是精确历史重放，证据级别固定为 `illustrative`。使用真实
资金前，应从选定、已核验且同口径的价格/收益率序列调用 `calibrate_historical_scenario`
重新生成。AI 估值回撤和中国复苏明确标记为假设情景，不得称为历史事件。

## 6. 证据质量与风险等级

`confidence_score` 表示输入证据质量，不是情景发生概率。它综合：

- 情景是来源校准、用户假设还是示意模板；
- 已映射权重及映射本身的证据质量；
- 未覆盖权重；
- 校验警告。

示意模板最高 55；未覆盖权重超过 20% 时最高 60；任何结果最高 90。损失风险等级：

- `Medium`：组合变化不高于 -5%；
- `High`：不高于 -10%；
- `Critical`：不高于 -20%；
- 其他为 `Low`。

等级衡量该情景下的损失幅度，不代表发生概率。

## 7. Dashboard

启动终端后进入“情景模拟”：

1. 选择已有已估值组合；
2. 检查映射覆盖率，必要时登记有依据的敏感度；
3. 选择内置模板，或输入自定义因子、基点和汇率假设；
4. 运行后查看风险地图、资产敏感性热力图和逐资产贡献；
5. 使用“情景比较”在同一组合快照上比较多个模板。

每次运行都会保存情景定义版本、组合日期、资产影响、输入数据指纹和确定性报告。

## 8. 已知限制

- 大冲击下线性敏感度可能失效；
- 当前不模拟波动率反馈、相关性突变、流动性缺口、市场冲击和管理层反应；
- 期权等非线性资产不能只用线性敏感度；
- 静态当前权重不是历史动态持仓；
- 没有映射的资产被假设不变，必然偏乐观；
- 内置近似模板不能替代授权数据的精确历史重放。

因此，Scenario Report 只应与既定风险预算比较；仓位调整和对冲仍需独立审批与验证。
