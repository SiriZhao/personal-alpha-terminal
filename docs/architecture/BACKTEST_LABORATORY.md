# Backtest Laboratory

Backtest Laboratory 是 Personal Alpha Terminal 的专业日频回测层。它用于验证历史规则，不
预测未来价格，也不产生真实交易指令。

## 核心时序

```text
信号日收盘
  └─ 策略只读取当日及以前的价格、点时因子和已公开事件
       └─ 下一投资组合交易日开盘执行目标权重
            └─ 扣除手续费、费用与滑点
                 └─ 当日收盘按复权价格计价
```

同一收盘价既形成信号又作为成交价会产生未来函数，因此引擎不支持该模式。

## 模块

```text
backtest/
├── engine.py       # 数据门禁、交易日调度、成交与持仓账本
├── strategy.py     # 统一策略协议和四类可解释策略
├── metrics.py      # 收益、风险、胜率、盈亏比、换手率
├── report.py       # Strategy Report 与 Dashboard 图表载荷
├── repository.py   # 单一价格源读取和结果持久化
├── service.py      # 运行、保存、生成报告
└── schemas.py      # 不可变输入输出契约
```

策略参数、价格输入和成本配置共同参与 SHA256 数据指纹；只改变因子快照、事件列表或费用
假设也会产生新的指纹。自定义策略必须实现 `audit_payload()`，否则不能运行。

结果保存到：

- `backtest_runs`
- `backtest_daily_results`
- `backtest_rebalances`
- `backtest_summary_metrics`
- `research_reports`，其中 `report_type = strategy_backtest`

## 数据规则

每个回测拒绝以下输入：

- 同一资产、同一日期重复行情；
- 缺少 `event_time / available_time / ingested_time`，或三者顺序非法；
- 非有限或非正 OHLC；
- `low > open/close` 或 `high < open/close`；
- 负成交量；
- 缺少复权收盘价（默认）；
- 同一资产在同一次回测中拼接多个供应商；
- 缺少经过核验且带来源标识的交易日历；
- 交易日历乱序、重复、包含周末，或与行情日期冲突；
- 资产市场与回测市场不一致；
- 交易日数量低于配置下限。

默认安全配置要求同时传入 `BacktestDataset.calendar` 和非空
`BacktestDataset.calendar_source`。禁止从行情并集猜测交易日；只有显式关闭
`require_verified_calendar` 的诊断模式才允许推导日历，并写入
`INFERRED_TRADING_CALENDAR` 警告。诊断模式结果不得用于投资决策。

复权开盘价按以下口径推导：

```text
adjustment_ratio_t = adjusted_close_t / raw_close_t
adjusted_open_t = raw_open_t × adjustment_ratio_t
```

这能保持拆股和分红前后的持仓连续性，但仍依赖数据供应商企业行动记录的正确性。数据库
读取先调用统一价格源选择器，不能逐日挑选“更有利”的供应商。

停牌期间，持仓可在限定交易日内按最后复权收盘价估值，但不能成交。默认要求执行日的
`open_tradable is True`；未知状态也按不可成交处理。目标组合包含不可交易资产或需要卖出
停牌资产时，整个调仓会被拒绝并记录原因；超过陈旧价格上限则终止回测。成交容量只使用
执行日前的原始价成交额估算，订单名义金额超过 `maximum_adv_participation` 或历史成交量
观测不足时拒绝调仓，绝不使用执行日收盘成交量倒推开盘可成交性。

## 成本核算

手续费、费用和滑点都按单边交易名义金额计算。为了避免“先满仓再从不存在的现金中扣费”，
引擎求解成本后净值：

```text
NAV_after =
  NAV_before
  - cost_rate × Σ |NAV_after × target_weight_i - current_value_i|
```

然后以 `NAV_after` 设置目标头寸和现金。每次调仓都校验：

```text
NAV_before = NAV_after + transaction_cost
```

v1 只支持多头、无杠杆，目标权重合计不得超过 100%。

## 调仓频率

- `daily`：每个交易日收盘形成信号，下一交易日开盘执行。
- `monthly`：仅当下一交易日进入新月份时形成信号。
- `quarterly`：仅当下一交易日进入新季度时形成信号。

样本最后一个未完成月份或季度不会被当作期间末，避免使用样本终点的未来信息。

## 指标定义

- 总收益：`ending_NAV / initial_NAV - 1`。
- 年化收益：按 252 个交易日进行几何年化。
- 年化波动：净日收益样本标准差乘 `sqrt(252)`。
- Sharpe：净日超额收益均值除以样本标准差后年化。
- Sortino：净日超额收益均值除以下行偏差后年化。
- 最大回撤：净值相对历史高点的最小值。
- 胜率：已闭合的“本次调仓前开盘净值到下次调仓前开盘净值”收益中正收益比例；零收益
  进入分母，样本末尚未闭合的持有期不进入胜率和盈亏比。每期包含本次调仓成本，不包含
  下次调仓成本。
- 盈亏比：上述盈利持有期平均收益 / 亏损持有期平均绝对收益。
- 换手率：单边交易名义金额 / 调仓前净值。

胜率和盈亏比不是逐笔证券交易统计；报告会显式注明统计粒度。

## 程序化调用

```python
from datetime import date

from personal_alpha_terminal.backtest.repository import BacktestRepository
from personal_alpha_terminal.backtest.schemas import BacktestConfig
from personal_alpha_terminal.backtest.service import BacktestService
from personal_alpha_terminal.backtest.strategy import FactorQuantileStrategy
from personal_alpha_terminal.reports.service import ResearchReportService

config = BacktestConfig(
    start_date=date(2015, 1, 1),
    end_date=date(2025, 12, 31),
    rebalance_frequency="monthly",
    commission_bps=2,
    fee_bps=1,
    slippage_bps=5,
)

# FactorSnapshot 同时保存 as_of_date 和 available_at；不得包含未来收益标签。
strategy = FactorQuantileStrategy(
    factor_name="roe",
    factor_snapshots=point_in_time_roe_snapshots,
    top_quantile=0.20,
)

service = BacktestService(
    BacktestRepository(session),
    ResearchReportService(session),
)
result, report = service.run_from_database(
    market="US",
    asset_ids=historical_universe_asset_ids,
    strategy=strategy,
    config=config,
    calendar=verified_exchange_sessions,
    calendar_source="licensed_exchange_calendar:v2026-07-31",
)
session.commit()
```

生产研究必须传入历史时点股票池。只使用今天仍上市的证券会产生幸存者偏差。

## Strategy Report 与可视化

`render_strategy_report()` 输出：

- 净收益和风险指标；
- 年度收益；
- 可验证的优势；
- 适用条件；
- 风险和失效条件；
- 数据来源、数据指纹、执行方法和数据警告；
- 证据质量评分。该评分不是盈利概率，且上限为 90。

`visualization_payload()` 提供 Dashboard 可直接使用的数据：

- `equity_curve`
- `drawdown_curve`
- `annual_returns`
- `risk_analysis`

## 已知限制

- 通用成本模型尚未自动实现 A 股卖出印花税、最低佣金、港股交易征费和各市场差异化费用；
  未显式校准前不得把默认成本视为真实净收益。
- `open_tradable` 必须由独立的停复牌/交易状态数据填充；Yahoo/AKShare 日线本身不能证明
  开盘集合竞价可成交，因此数据库回测会安全拒绝未知状态。
- ADV 容量是粗略上限，不等于订单簿冲击、涨跌停排队或真实成交概率。
- v1 不支持做空、杠杆或跨市场同时回测。
- 跨市场组合需要时区交易日历、外汇账本和异步收盘处理，不能用本引擎强行拼接。
- 免费行情的复权历史可能被修订。
- 如果历史股票池缺少退市证券，结果仍有幸存者偏差。
- 参数搜索、策略挑选和反复查看测试集会造成过拟合；最终策略必须使用锁定样本外区间和
独立前向观察验证。
