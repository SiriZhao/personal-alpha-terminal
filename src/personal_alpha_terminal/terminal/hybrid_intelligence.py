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
    production_closure: dict[str, object] | None = None,
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
    if production_closure is not None:
        _production_closure(console, production_closure)


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
    raw_closure = document.get("production_closure")
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
        production_closure=raw_closure if isinstance(raw_closure, dict) else None,
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
    table.add_column("Probability", justify="right")
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
            (
                f"{item.probability_contribution:.2%}"
                if item.probability_contribution is not None
                else "N/A"
            ),
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


def _production_closure(console: Console, closure: dict[str, object]) -> None:
    formal = closure.get("formal_influence")
    market = closure.get("market_participation")
    counterfactuals = closure.get("counterfactual_ledger")
    attribution = closure.get("decision_attribution")
    decision_audit = closure.get("llm_decision_audit")

    if isinstance(decision_audit, dict):
        _llm_decision_audit(console, decision_audit)

    if isinstance(formal, dict) or isinstance(market, dict):
        table = Table(title="【ROUND66 市场参与与正式影响】")
        table.add_column("字段")
        table.add_column("值")
        if isinstance(market, dict):
            table.add_row("Champion", str(closure.get("champion", "--")))
            table.add_row("Current gross", _percent(market.get("current_gross")))
            table.add_row("Target gross", _percent(market.get("target_gross")))
            table.add_row("Current cash", _percent(market.get("current_cash")))
            table.add_row("Target cash", _percent(market.get("target_cash")))
            table.add_row("Current beta", _number(market.get("current_beta")))
            table.add_row("Target beta", _number(market.get("target_beta")))
            table.add_row("Participation policy", str(market.get("policy", "--")))
            table.add_row("Adaptive policy", str(market.get("adaptive_policy", "--")))
        if isinstance(formal, dict):
            table.add_row("Quant influence", _percent(formal.get("quant")))
            table.add_row("Probability influence", _percent(formal.get("probability")))
            table.add_row("LLM influence", _percent(formal.get("llm")))
            table.add_row("Adaptive influence", _percent(formal.get("adaptive_participation")))
        console.print(table)

    if isinstance(counterfactuals, dict):
        table = Table(title="【四路决策反事实账本】")
        table.add_column("路径")
        table.add_column("状态")
        table.add_column("Target hash")
        table.add_column("Count", justify="right")
        for name, raw in counterfactuals.items():
            if not isinstance(raw, dict):
                continue
            target_hash = str(raw.get("target_hash", "--"))
            table.add_row(
                str(name),
                str(raw.get("status", "--")),
                target_hash[:16],
                str(raw.get("target_count", "--")),
            )
        console.print(table)

    if isinstance(attribution, list):
        table = Table(title="【Decision Attribution】")
        table.add_column("股票")
        table.add_column("Quant", justify="right")
        table.add_column("Probability", justify="right")
        table.add_column("LLM", justify="right")
        table.add_column("Regime", justify="right")
        table.add_column("Risk", justify="right")
        table.add_column("Final alpha", justify="right")
        table.add_column("Confidence", justify="right")
        for raw in attribution:
            if not isinstance(raw, dict):
                continue
            table.add_row(
                str(raw.get("symbol", "--")),
                _signed_percent(raw.get("quant_contribution")),
                _signed_percent(raw.get("probability_contribution")),
                _signed_percent(raw.get("llm_contribution")),
                _signed_percent(raw.get("regime_contribution")),
                _signed_percent(raw.get("risk_adjustment")),
                _signed_percent(raw.get("final_expected_alpha")),
                _number(raw.get("confidence")),
            )
        if table.row_count:
            console.print(table)


def _llm_decision_audit(console: Console, audit: dict[str, object]) -> None:
    """Compact Chinese operator view for structured LLM decision provenance."""

    table = Table(title="【LLM 决策审计】")
    table.add_column("字段")
    table.add_column("值")
    table.add_row("影响级别", str(audit.get("influence_level", "L0_COMMENTARY")))
    table.add_row("正式影响", _percent(audit.get("formal_influence")))
    table.add_row(
        "当前状态",
        "降级：量化路径继续"
        if audit.get("degraded_ai")
        else "结构化：等待硬门禁与人工确认",
    )
    table.add_row(
        "组合判断",
        str(audit.get("portfolio_view") or audit.get("market_view") or "证据不足"),
    )
    table.add_row("主要风险", str(audit.get("dominant_risk") or "以 Risk Engine 为准"))
    table.add_row("是否存在分歧", "是" if audit.get("disagreements") else "否/未识别")
    table.add_row("操作理由", str(audit.get("reason") or "LLM 不改变正式仓位"))
    console.print(table)
    disagreements = audit.get("disagreements")
    if isinstance(disagreements, list):
        for item in disagreements:
            if not isinstance(item, dict):
                continue
            console.print(
                f"{item.get('symbol', '--')}: Quant={item.get('quant_view', '--')} | "
                f"LLM={item.get('llm_view', '--')} | "
                f"{item.get('category', 'DATA_UNCERTAIN')} | "
                f"融合={item.get('fusion_result', 'QUANT_ONLY')}"
            )


def _percent(value: object) -> str:
    return f"{float(value):.2%}" if isinstance(value, (int, float)) else "N/A"


def _signed_percent(value: object) -> str:
    return f"{float(value):+.2%}" if isinstance(value, (int, float)) else "N/A"


def _number(value: object) -> str:
    return f"{float(value):.4f}" if isinstance(value, (int, float)) else "N/A"
