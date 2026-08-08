from personal_alpha_terminal.portfolio.management_schemas import PortfolioManagementResult
from personal_alpha_terminal.reports.schemas import ReportDocument


def render_portfolio_management_report(
    result: PortfolioManagementResult,
) -> ReportDocument:
    def metric(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.2%}"

    def ratio(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.3f}"

    lines = [
        f"# {result.portfolio_name} Portfolio Report",
        "",
        "> 仅供投资研究与风险管理。再平衡结果是分析提示，不是订单，也不会自动交易。",
        "",
        "## 组合概览",
        "",
        f"- 分析区间：{result.start_date.isoformat()} 至 {result.as_of_date.isoformat()}",
        f"- 期末价值：{result.base_currency} {result.total_value:,.2f}",
        f"- 期初价值：{result.base_currency} {result.opening_value:,.2f}",
        f"- 期间净外部资金流：{result.base_currency} {result.net_external_flow:,.2f}",
        f"- 期间损益：{result.base_currency} {result.period_pnl:,.2f}",
        f"- 最近一日收益率：{metric(result.latest_daily_return)}",
        f"- 累计时间加权收益：{metric(result.cumulative_return)}",
        f"- 年化收益：{metric(result.annualized_return)}",
        f"- 年化波动率：{metric(result.annualized_volatility)}",
        f"- 最大回撤：{metric(result.max_drawdown)}",
        f"- Sharpe：{ratio(result.sharpe_ratio)}",
        f"- Sortino：{ratio(result.sortino_ratio)}",
        f"- Beta：{ratio(result.beta)}",
        f"- 年化 Jensen Alpha：{metric(result.alpha)}",
        f"- 有效收益观测：{result.observation_count}",
        "",
        "## 资产配置",
        "",
        "### 资产类别",
        "",
    ]
    lines.extend(
        f"- {key}: {value:.2%}"
        for key, value in sorted(
            result.asset_class_exposure.items(), key=lambda item: item[1], reverse=True
        )
    )
    lines.extend(["", "### 行业暴露", ""])
    lines.extend(
        f"- {key}: {value:.2%}"
        for key, value in sorted(
            result.industry_exposure.items(), key=lambda item: item[1], reverse=True
        )
    )
    lines.extend(["", "### 币种暴露", ""])
    lines.extend(
        f"- {key}: {value:.2%}"
        for key, value in sorted(
            result.currency_exposure.items(), key=lambda item: item[1], reverse=True
        )
    )
    lines.extend(["", "### 单一资产风险", ""])
    if result.positions:
        lines.extend(
            f"- {item.symbol} ({item.asset_class}, {item.currency}): "
            f"{item.weight:.2%}; {result.base_currency} {item.market_value:,.2f}"
            for item in result.positions
        )
    else:
        lines.append("- 当前没有证券类持仓。")

    lines.extend(["", "## 再平衡分析", ""])
    if result.rebalance_suggestions:
        for item in result.rebalance_suggestions:
            action = "增加" if item.action == "increase" else "减少"
            lines.append(
                f"- {item.label}: 当前 {item.current_weight:.2%}，目标 "
                f"{item.target_weight:.2%}；分析提示{action}约 "
                f"{result.base_currency} {abs(item.indicative_value):,.2f}。"
            )
    else:
        lines.append("- 未配置目标权重，或所有偏离均低于阈值。")
    lines.append("- 上述金额未考虑税费、买卖价差、流动性和最小交易单位，不可直接作为订单。")

    sources = (
        "portfolio_transactions:event_time,available_time,ingested_time",
        "prices:unadjusted_close:selected_consistent_source",
        "fx_rates:daily_pair_rate",
        "portfolio_allocation_targets:latest_effective_set",
        f"data_fingerprint:{result.data_fingerprint}",
    )
    methodology = (
        "持仓和现金由不可变交易账本按交易日顺序重建。",
        "买卖、分红和费用属于组合内部现金流；入金和出金从时间加权收益中剔除。",
        "使用未复权收盘价，避免与显式分红重复计收益；拆股必须记录为 split 事件。",
        "跨币种资产和现金逐日换算为组合基准币种。",
        "Beta 为组合与基准日收益协方差除以基准方差；Alpha 为年化 Jensen alpha。",
        "再平衡仅比较当前权重与版本化目标权重，不生成、不发送交易指令。",
    )
    risks = (
        "收盘价估值无法反映盘中成交时点，日内资金流采用期末现金流约定。",
        "遗漏交易、分红、税费、拆股或汇率会直接造成收益和成本口径错误。",
        "未覆盖衍生品、卖空、融资杠杆、税务批次和经纪商特定费用规则。",
        "Beta 和 Alpha 是历史线性统计量，不代表因果关系或未来表现。",
        "再平衡提示未考虑税务、滑点、流动性和个人适当性。",
    )
    if result.warnings:
        lines.extend(["", "## 数据与模型警告", ""])
        lines.extend(f"- {item}" for item in result.warnings)
    lines.extend(["", "## 数据来源", ""])
    lines.extend(f"- {item}" for item in sources)
    lines.extend(["", "## 计算逻辑", ""])
    lines.extend(f"- {item}" for item in methodology)
    lines.extend(["", "## 风险与已知限制", ""])
    lines.extend(f"- {item}" for item in risks)
    return ReportDocument(
        report_type="portfolio_management",
        as_of_date=result.as_of_date,
        subject_key=str(result.portfolio_id),
        title=f"{result.portfolio_name} Portfolio Report",
        markdown="\n".join(lines) + "\n",
        data_sources=sources,
        methodology=methodology,
        risk_factors=risks,
    )
