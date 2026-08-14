"""ROUND24 Chinese brief terminal renderer (B2, B4, H1).

Facts and LLM interpretation are visually separated:
【量化事实】 comes only from immutable artifacts; 【AI 解读】 is clearly
marked as interpretation.  The renderer never presents LLM text as a
database fact.
"""

from __future__ import annotations

from typing import Any

BRIEF_TITLE = "【AI 中文研判 · DeepSeek】"


def render_brief_header(brief: dict[str, Any]) -> str:
    model = str(brief.get("model", "deepseek-v4-flash"))
    status = str(brief.get("llm_status", "PASS_DEGRADED"))
    source = str(brief.get("source", "RULE_BASED_DETERMINISTIC"))
    influence = str(brief.get("production_influence", "NONE"))
    return (
        f"{BRIEF_TITLE}\n"
        f"模型:{model}\n"
        f"角色:量化结果解释 / 风险情报辅助\n"
        f"生产决策影响:{influence}\n"
        f"LLM 状态:{status} | 来源:{source}\n"
        "交易权限:NONE | 目标权重权限:NONE | 买卖权限:NONE"
    )


def render_brief_compact(brief: dict[str, Any]) -> str:
    lines = [render_brief_header(brief)]
    payload = brief.get("brief") or {}
    summary = payload.get("summary") or "暂无摘要。"
    lines.append("")
    lines.append("一、今日量化结论【AI 解读】")
    lines.append(summary)
    actions = payload.get("action_explanations") or []
    if actions:
        lines.append("")
        lines.append("操作解读(仅列前 5 条):")
        for item in actions[:5]:
            lines.append(f"- {item.get('symbol')}: {item.get('ai_interpretation', '')}")
        if len(actions) > 5:
            lines.append(f"... 其余 {len(actions) - 5} 条见完整研判 "
                         f"(python main.py intelligence brief)")
    portfolio_risks = payload.get("portfolio_risks") or []
    if portfolio_risks:
        lines.append("")
        lines.append("重点风险【AI 解读】")
        for risk in portfolio_risks[:3]:
            lines.append(f"- {risk}")
    lines.append("")
    lines.append("按完整研判: python main.py intelligence brief --full")
    return "\n".join(lines)


def render_brief_full(
    brief: dict[str, Any], facts: dict[str, Any] | None = None
) -> str:
    payload = brief.get("brief") or {}
    lines = [render_brief_header(brief), ""]
    facts_section = facts or {}
    pit_events = facts_section.get("pit_events") or []
    lines.append("一、今日量化结论")
    lines.append("【量化事实】")
    lines.append(
        f"分析日期 {facts_section.get('analysis_date', '不适用')},"
        f"交易日 {facts_section.get('trade_date', '不适用')},"
        f"因子数 {facts_section.get('factor_count', '不适用')},"
        f"候选数 {facts_section.get('candidate_count', '不适用')}。"
    )
    lines.append("【AI 解读】")
    lines.append(payload.get("summary", "暂无。"))
    lines.append("")
    lines.append("二、市场环境")
    lines.append("【量化事实】")
    for benchmark in facts_section.get("benchmarks") or []:
        lines.append(
            f"基准 {benchmark.get('symbol')} 期间收益 "
            f"{benchmark.get('period_return')},年化波动 "
            f"{benchmark.get('annualized_volatility')}。"
        )
    lines.append("【AI 解读】")
    lines.append(payload.get("market_interpretation", "暂无。"))
    lines.append("")
    lines.append("三、组合结构解读")
    lines.append("【量化事实】")
    lines.append(f"组合信息来自不可变运行证书:{facts_section.get('portfolio', {})}")
    lines.append("【AI 解读】")
    lines.append(payload.get("portfolio_interpretation", "暂无。"))
    lines.append("")
    lines.append("四、今日买入/减仓逻辑")
    for item in payload.get("action_explanations") or []:
        lines.append(f"—— {item.get('symbol')}")
        lines.append(f"量化 Alpha:{item.get('quant_alpha', '不适用')}")
        lines.append(f"趋势:{item.get('trend', '不适用')}")
        lines.append(f"波动:{item.get('volatility', '不适用')}")
        lines.append(f"风险目标:{item.get('risk_target', '不适用')}")
        lines.append(f"流动性:{item.get('liquidity', '不适用')}")
        lines.append(f"组合作用:{item.get('portfolio_role', '不适用')}")
        lines.append(f"PIT 事件:{item.get('pit_events', '不适用')}")
        lines.append(f"AI 解读:{item.get('ai_interpretation', '')}")
        lines.append(f"证据引用:{item.get('evidence_refs', [])}")
    if not payload.get("action_explanations"):
        lines.append("本轮没有最终操作建议。")
    lines.append("")
    lines.append("五、重点风险")
    lines.append("【AI 解读】")
    for risk in payload.get("portfolio_risks") or ["暂无。"]:
        lines.append(f"- {risk}")
    lines.append("")
    lines.append("六、SEC / 企业事件")
    lines.append("【量化事实】")
    if pit_events:
        for event in pit_events:
            lines.append(
                f"- {event.get('symbol')}: {event.get('event_type')} "
                f"@ {event.get('effective_at')}(证据 {event.get('evidence_ref')})"
            )
    else:
        lines.append("当前没有可用于任何证券的 PIT 企业事件证据。")
    lines.append("【AI 解读】")
    for risk in payload.get("event_risks") or ["暂无。"]:
        lines.append(f"- {risk}")
    lines.append("")
    lines.append("七、ETF / 大类资产观察")
    etf_section = facts_section.get("etf") or {}
    lines.append("【量化事实】")
    lines.append(f"ETF 池:{etf_section.get('universe', {})}")
    for target in etf_section.get("targets") or []:
        lines.append(
            f"- {target.get('symbol')} [{target.get('sleeve')}] 目标权重 "
            f"{target.get('target_weight')} | {target.get('rationale', '')}"
        )
    lines.append("【AI 解读】")
    lines.append("ETF 不适用公司级 SEC 事件分析;成分穿透 UNAVAILABLE。")
    lines.append("")
    lines.append("八、与 SPY / QQQ 的关系")
    lines.append("【量化事实】")
    lines.append("基准数据见第二节;组合与基准的相对行为由风险引擎计算。")
    lines.append("【AI 解读】")
    lines.append(payload.get("market_interpretation", "暂无。"))
    lines.append("")
    lines.append("九、数据与模型局限")
    lines.append("【量化事实】")
    for gap in facts_section.get("data_gaps") or ["未记录到数据缺口。"]:
        lines.append(f"- {gap}")
    lines.append("【AI 解读】")
    for gap in payload.get("data_gaps") or ["暂无。"]:
        lines.append(f"- {gap}")
    for uncertainty in payload.get("uncertainties") or []:
        lines.append(f"- 不确定性:{uncertainty}")
    lines.append("")
    lines.append("反向视角【AI 解读】")
    lines.append(payload.get("contrarian_view", "暂无。"))
    lines.append("")
    lines.append("AI 最终评价:")
    lines.append(payload.get("summary", "暂无。"))
    return "\n".join(lines)
