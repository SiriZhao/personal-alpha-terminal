"""ROUND24 deterministic Chinese brief fallback (B7).

When DeepSeek is unavailable, times out, or violates the schema, the terminal
still shows a natural Chinese brief assembled strictly from the quant facts.
It is always labeled ``LLM PASS_DEGRADED`` and never invents content.
"""

from __future__ import annotations

from typing import Any

from personal_alpha_terminal.ai_advisory.schemas import SCHEMA_VERSION


def _pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "不适用"
    return f"{number * 100:.{digits}f}%"


def _action_line(item: dict[str, Any]) -> str:
    symbol = item.get("symbol")
    action = item.get("action") or "无操作"
    instrument_type = item.get("instrument_type", "COMMON_STOCK")
    sleeve = item.get("sleeve", "EQUITY_ALPHA")
    kind = "ETF" if instrument_type == "ETF" else "股票"
    if kind == "ETF":
        pit_text = "ETF:不适用公司级 SEC 事件分析。"
    else:
        pit_text = "当前没有可用于该证券的 PIT 企业事件证据。"
    alpha = _pct(item.get("expected_alpha"))
    target = _pct(item.get("target_weight"))
    current = _pct(item.get("current_weight"))
    return (
        f"{symbol}({kind}/{sleeve}):量化 Alpha 预期 {alpha},当前权重 {current},"
        f"目标权重 {target},动作 {action}。{pit_text}"
    )


def build_deterministic_brief(facts: dict[str, Any]) -> dict[str, Any]:
    """Assemble a schema-valid deterministic Chinese brief from facts alone."""

    actions = facts.get("formal_actions") or facts.get("actions") or []
    buy_count = sum(1 for item in actions if item.get("action") == "BUY")
    sell_count = sum(1 for item in actions if item.get("action") == "SELL")
    hold_count = len(actions) - buy_count - sell_count
    summary = (
        f"今日量化流水线于 {facts.get('analysis_date')} 完成分析,面向交易日 "
        f"{facts.get('trade_date')}。共生成 {len(actions)} 条操作建议:"
        f"买入 {buy_count} 条,卖出 {sell_count} 条,其余 {hold_count} 条。"
        f"研究认证状态为 {facts.get('research_certification_state')},"
        f"LLM 生产影响为 {facts.get('llm_mode')},概率生产权重为 "
        f"{facts.get('probability_influence')}。"
    )
    market_interpretation = (
        "市场环境描述基于已进入事实集的基准与流水线状态,不包含任何未经验证的"
        "新闻或预测。基准 SPY/QQQ 的最新可观测状态与流水线各阶段状态均来自"
        "不可变运行证书。"
    )
    universe = facts.get("universe") or {}
    etf_universe = (facts.get("etf") or {}).get("universe") or {}
    research_candidates = facts.get("research_candidates") or []
    research_names = sorted(
        {str(item.get("symbol")) for item in research_candidates if item.get("symbol")}
    )
    research_text = (
        (
            f"ETF 研究候选共 {len(research_names)} 个"
            f"({', '.join(research_names)}),当前均为 RESEARCH_CANDIDATE 状态,"
            "交易权限 NONE,不属于今日执行计划;它们的研究目标权重只是候选配置"
            "方向,尚未进入 SIGNAL→PORTFOLIO→RISK→DECISION→EXECUTION 正式链,"
            "不能被理解为持仓或买卖指令。"
        )
        if research_names
        else "当前没有可展示的 ETF 研究候选。"
    )
    portfolio_interpretation = (
        f"股票池证书成员 {universe.get('members', '不适用')} 个;ETF 池中核心"
        f"候选 {etf_universe.get('core_eligible', '不适用')} 个,战术候选 "
        f"{etf_universe.get('tactical_eligible', '不适用')} 个,复杂产品被策略"
        f"默认拦截 {etf_universe.get('blocked_complex', '不适用')} 个。"
        "组合解释只基于优化器输出的目标权重与风险贡献,ETF 成分穿透信息"
        "当前不可用(ETF look-through: UNAVAILABLE)。"
        f"{research_text}"
    )
    action_explanations = []
    for item in actions:
        symbol = item.get("symbol")
        if not symbol:
            continue
        action_explanations.append(
            {
                "symbol": symbol,
                "quant_alpha": _pct(item.get("expected_alpha")),
                "trend": "见 factor_statistics",
                "volatility": "见 risk 部分",
                "risk_target": _pct(item.get("risk_contribution")),
                "liquidity": item.get("data_quality"),
                "portfolio_role": (
                    item.get("sleeve", "EQUITY_ALPHA")
                    if item.get("instrument_type") == "ETF"
                    else "EQUITY_ALPHA"
                ),
                "pit_events": (
                    "ETF:不适用公司级 SEC 事件分析。"
                    if item.get("instrument_type") == "ETF"
                    else "当前没有可用于该证券的 PIT 企业事件证据。"
                ),
                "ai_interpretation": _action_line(item),
                "evidence_refs": [f"run-certificate:{facts.get('_run_id', 'UNKNOWN')}"],
            }
        )
    event_risks = [
        "本简报未发现可引用的已验证 PIT 事件;所有事件声明均以证据库为准。"
    ]
    warnings = facts.get("warnings") or []
    portfolio_risks = [str(item) for item in warnings][:8] or [
        "流水线未报告额外风险警告。"
    ]
    contrarian_view = (
        "反向视角提示:本简报的解释完全基于已冻结的量化事实,不得被理解为"
        "对任何证券未来表现的预测;历史研究仍为 NOT_CERTIFIABLE。"
    )
    uncertainties = [
        "历史研究认证状态为 NOT_CERTIFIABLE,当前结果不代表可回测的历史有效性。",
        "ETF 成分穿透(holdings look-through)当前不可用,重叠风险仅基于相关性。",
        "LLM 研判不参与任何交易决策,其解释不构成操作依据。",
    ]
    data_gaps = [str(item) for item in facts.get("data_gaps", [])] or [
        "未记录到数据缺口。"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": summary,
        "market_interpretation": market_interpretation,
        "portfolio_interpretation": portfolio_interpretation,
        "action_explanations": action_explanations,
        "event_risks": event_risks,
        "portfolio_risks": portfolio_risks,
        "contrarian_view": contrarian_view,
        "uncertainties": uncertainties,
        "data_gaps": data_gaps,
    }
