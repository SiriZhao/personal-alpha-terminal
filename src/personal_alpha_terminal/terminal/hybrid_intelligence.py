"""Read-only Chinese renderer for hybrid intelligence artifacts."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from personal_alpha_terminal.intelligence.agentic_models import (
    HybridActionView,
    HybridIntelligenceStatus,
    HybridSecurityView,
    MarketIntelligenceSnapshot,
    PortfolioSemanticRiskReport,
)


def render_hybrid_intelligence(
    console: Console,
    *,
    status: HybridIntelligenceStatus,
    securities: tuple[HybridSecurityView, ...],
    actions: tuple[HybridActionView, ...] = (),
    market: MarketIntelligenceSnapshot | None = None,
    portfolio_risk: PortfolioSemanticRiskReport | None = None,
) -> None:
    console.print(
        Panel(
            "LLM 解释事件和语义增量；最终仓位只由 Portfolio Optimizer + Risk Engine 计算。",
            title="【Hybrid Intelligence Quant System】",
            border_style="cyan",
        )
    )
    _status(console, status)
    if market is not None:
        _market(console, market)
    _securities(console, securities)
    if actions:
        _actions(console, actions)
    if portfolio_risk is not None:
        _portfolio_risk(console, portfolio_risk)


def render_hybrid_intelligence_document(
    console: Console,
    document: dict[str, object],
) -> None:
    raw_status = document.get("status")
    if not isinstance(raw_status, dict):
        raise ValueError("hybrid intelligence artifact requires a status object")
    raw_securities = document.get("securities", ())
    raw_actions = document.get("actions", ())
    securities = tuple(
        HybridSecurityView.model_validate(item)
        for item in raw_securities
        if isinstance(item, dict)
    ) if isinstance(raw_securities, (list, tuple)) else ()
    actions = tuple(
        HybridActionView.model_validate(item)
        for item in raw_actions
        if isinstance(item, dict)
    ) if isinstance(raw_actions, (list, tuple)) else ()
    raw_market = document.get("market")
    raw_risk = document.get("portfolio_semantic_risk")
    render_hybrid_intelligence(
        console,
        status=HybridIntelligenceStatus.model_validate(raw_status),
        securities=securities,
        actions=actions,
        market=(
            MarketIntelligenceSnapshot.model_validate(raw_market)
            if isinstance(raw_market, dict)
            else None
        ),
        portfolio_risk=(
            PortfolioSemanticRiskReport.model_validate(raw_risk)
            if isinstance(raw_risk, dict)
            else None
        ),
    )


def _status(console: Console, status: HybridIntelligenceStatus) -> None:
    table = Table(show_header=False, box=None)
    table.add_column("字段", style="bold cyan")
    table.add_column("状态")
    rows = (
        ("LLM Provider / Model", f"{status.provider} / {status.model}"),
        ("Data Freshness", status.data_freshness),
        ("Event Intelligence", status.event_intelligence),
        ("Company Intelligence", status.company_intelligence),
        ("Market Intelligence", status.market_intelligence),
        ("Semantic Alpha", status.semantic_alpha),
        ("Promotion Gate", status.promotion_gate),
        ("Formal Economic Influence", f"{status.formal_economic_influence:.2%}"),
        ("Auto Execution", status.auto_execution),
        ("Manual Confirmation", status.manual_confirmation),
        ("Pre-optimizer Top-N", "null"),
        ("Fixed Holdings Cap", "null"),
    )
    for label, value in rows:
        table.add_row(label, value)
    console.print(Panel(table, title="【LLM STATUS】", border_style="yellow"))


def _market(console: Console, market: MarketIntelligenceSnapshot) -> None:
    table = Table(title="【市场智能】")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("Quant Regime", market.quant_regime)
    table.add_row("LLM Interpretation", market.llm_interpreted_regime)
    table.add_row("Risk On", f"{market.risk_on_score:.2f}")
    table.add_row("Risk Off", f"{market.risk_off_score:.2f}")
    table.add_row("Macro Uncertainty", f"{market.macro_uncertainty:.2f}")
    table.add_row("Market Event Score", f"{market.market_event_score:.2f}")
    table.add_row("Sector Context", ", ".join(market.sector_context) or "--")
    table.add_row("Commentary", market.regime_commentary or "--")
    console.print(table)


def _securities(console: Console, securities: tuple[HybridSecurityView, ...]) -> None:
    table = Table(title="【公司与决策智能】")
    table.add_column("股票")
    table.add_column("公司 / 主营")
    table.add_column("Quant Rank", justify="right")
    table.add_column("Base Alpha", justify="right")
    table.add_column("Semantic", justify="right")
    table.add_column("Applied", justify="right")
    table.add_column("Final Alpha", justify="right")
    table.add_column("Quant × LLM")
    table.add_column("Influence")
    for item in securities:
        company = f"{item.company_name}\n{item.business_summary}"
        table.add_row(
            item.symbol,
            company,
            f"{item.quant_rank:.4f}",
            f"{item.base_expected_alpha:.2%}",
            f"{item.semantic_event_alpha:.2%}",
            f"{item.applied_llm_adjustment:.2%}",
            f"{item.final_expected_alpha:.2%}",
            item.debate.value,
            f"{item.production_influence:.2%}",
        )
    console.print(table)
    for item in securities:
        details = (
            f"Confidence: {item.confidence:.2f}\n"
            f"Expected Horizon: {item.expected_horizon_sessions or '--'} sessions\n"
            f"Latest Event: {item.latest_event or '--'}\n"
            f"Bull Case: {item.bull_case or '--'}\n"
            f"Bear Case: {item.bear_case or '--'}\n"
            f"Catalysts: {', '.join(item.catalysts) or '--'}\n"
            f"Invalidation: {', '.join(item.invalidation) or '--'}\n"
            f"Semantic Risk: {item.semantic_risk or '--'}\n"
            f"LLM Influence Level: {item.influence_level.value}"
        )
        console.print(Panel(details, title=f"【{item.symbol} 归因】"))


def _actions(console: Console, actions: tuple[HybridActionView, ...]) -> None:
    table = Table(title="【操作清单】")
    table.add_column("股票")
    table.add_column("Current", justify="right")
    table.add_column("Quant-only", justify="right")
    table.add_column("Hybrid", justify="right")
    table.add_column("Final Risk-adjusted", justify="right")
    table.add_column("Action")
    for item in actions:
        table.add_row(
            item.symbol,
            f"{item.current_weight:.2%}",
            f"{item.quant_only_target:.2%}",
            f"{item.hybrid_target:.2%}",
            f"{item.final_risk_adjusted_target:.2%}",
            item.action,
        )
    console.print(table)
    console.print("最终权重来自 Optimizer + Risk Engine，不是 LLM。")


def _portfolio_risk(
    console: Console,
    report: PortfolioSemanticRiskReport,
) -> None:
    table = Table(title="【组合语义风险】")
    table.add_column("主题")
    table.add_column("股票")
    for theme, symbols in report.common_theme_clusters.items():
        table.add_row(theme, ", ".join(symbols))
    if not report.common_theme_clusters:
        table.add_row("--", "未发现有证据支持的共同主题")
    console.print(table)
    console.print(
        Panel(
            f"Semantic Concentration: {report.semantic_concentration_score:.2f}\n"
            f"Confidence: {report.confidence:.2f}\n"
            f"{report.portfolio_narrative}",
            title="【风险解释】",
        )
    )
