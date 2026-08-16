"""ROUND24 Chinese brief terminal renderer (B2, B4, H1).

Facts and LLM interpretation are visually separated:
【量化事实】 comes only from immutable artifacts; 【AI 解读】 is clearly
marked as interpretation.  The renderer never presents LLM text as a
database fact.
"""

from __future__ import annotations

from typing import Any

BRIEF_TITLE = "【AI 中文研判 · DeepSeek】"


def render_brief_v2(brief: dict[str, Any]) -> str:
    """ROUND25 PHASE 3: full 19-section DailyAIBriefV2 (default terminal view)."""

    payload = brief.get("brief") or {}
    model = str(brief.get("model", "deepseek-v4-flash"))
    status = str(brief.get("llm_status", "PASS_DEGRADED"))
    source = str(brief.get("source", "RULE_BASED_DETERMINISTIC_V2"))
    grounding = str(brief.get("semantic_grounding_status", ""))
    lines = [
        "【AI 每日市场与量化研判】",
        f"模型:{model} | LLM 状态:{status} | 来源:{source}",
        "角色:ADVISORY / EXPLANATION | 生产决策影响:NONE | 交易/目标权重/买卖权限:NONE",
    ]
    if grounding == "AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH":
        issues = "; ".join(
            str(item) for item in (brief.get("semantic_grounding_issues") or [])
        )
        lines.append(
            f"⚠ 语义接地校验失败,已隔离(AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH):{issues}"
        )
    lines.append("")
    sections = (
        ("一、执行摘要", "executive_summary"),
        ("二、今日正式量化结论", "formal_conclusions"),
        ("三、美股市场整体状态", "market_state"),
        ("四、主要指数与风格变化", "index_analysis"),
        ("五、市场宽度与内部结构", "breadth_analysis"),
        ("六、行业 / 风格 / 因子轮动", "factor_rotation"),
        ("七、宏观环境", "macro_context"),
        ("八、今日重要市场新闻", None),
        ("九、企业 / SEC 重点事件", None),
        ("十、当前组合分析", "portfolio_risk_analysis"),
        ("十一、今日每个正式操作的逐项解释", None),
        ("十二、AI 对正式操作的看法", None),
        ("十三、组合层 AI Review", None),
        ("十四、AI 反方审查", None),
        ("十五、ETF 研究观察 · 不需要操作", None),
        ("十六、风险集中度分析", "portfolio_risk_analysis"),
        ("十七、反方观点 / 风险质疑", "bear_case"),
        ("十八、隔夜与开盘风险", "overnight_risk"),
        ("十九、SPY / QQQ benchmark 对照", "index_analysis"),
        ("二十、未来 1-5 个交易日需要重点观察的事项", None),
        ("二十一、数据 / 模型局限", None),
        ("二十二、最终人工执行提示", None),
    )
    news_rows = payload.get("important_news") or []
    sec_events = payload.get("sec_events") or []
    action_rows = payload.get("formal_action_explanations") or []
    commentary_rows = payload.get("action_commentaries") or []
    portfolio_review = payload.get("portfolio_review") or {}
    devils_rows = payload.get("devils_advocate") or []
    etf_rows = payload.get("etf_research_analysis") or []
    uncertainties = payload.get("uncertainties") or []
    watchlist = payload.get("watchlist_next_sessions") or []
    limitations = payload.get("data_limitations") or []
    manual_notes = payload.get("manual_execution_notes") or []
    for title, key in sections:
        lines.append(title)
        if key is None:
            if title == "八、今日重要市场新闻":
                for row in news_rows:
                    lines.append(
                        f"[{row.get('evidence_ref')}] {row.get('headline')}"
                    )
                    lines.append(f"  为什么重要:{row.get('why_matters')}")
                    lines.append(
                        f"  影响:{row.get('affected')} | 组合关系:{row.get('portfolio_link')} "
                        f"| 证据强度:{row.get('strength')}"
                    )
                if not news_rows:
                    lines.append("当前没有已持久化的市场新闻。")
            elif title == "九、企业 / SEC 重点事件":
                for row in sec_events:
                    lines.append(f"- {row}")
                if not sec_events:
                    lines.append("当前没有企业 / SEC 重点事件。")
            elif title == "十一、今日每个正式操作的逐项解释":
                for row in action_rows:
                    lines.append(f"—— {row.get('symbol')} ({row.get('action')})")
                    lines.append(f"量化 Alpha:{row.get('quant_alpha', '不适用')}")
                    lines.append(f"目标权重:{row.get('target_weight', '不适用')}")
                    lines.append(f"风险贡献:{row.get('risk_contribution', '不适用')}")
                    lines.append(f"预计成本:{row.get('cost', '不适用')}")
                    lines.append(f"AI 解读:{row.get('ai_explanation', '')}")
                    lines.append(f"证据引用:{row.get('evidence_refs', [])}")
                if not action_rows:
                    lines.append("本轮没有正式操作建议。")
            elif title == "十二、AI 对正式操作的看法":
                for row in commentary_rows:
                    lines.append(f"—— {row.get('ticker')} ({row.get('formal_action')})")
                    lines.append(f"公司:{row.get('company_name', 'UNAVAILABLE')}")
                    lines.append(
                        f"LLM 观点:{row.get('llm_view', 'NEUTRAL')} | "
                        f"支持度 {row.get('support_level', 0)}"
                    )
                    lines.append(f"业务摘要:{row.get('business_summary', '')}")
                    lines.append(f"为何量化可能喜欢:{row.get('why_quant_may_like_it', '')}")
                    lines.append(f"近期正面催化:{row.get('recent_positive_catalysts', [])}")
                    lines.append(f"近期负面催化:{row.get('recent_negative_catalysts', [])}")
                    lines.append(f"关键风险:{row.get('key_risks', [])}")
                    lines.append(f"反方论证:{row.get('llm_counterargument', '')}")
                    lines.append(f"人工复核重点:{row.get('human_review_focus', '')}")
                    lines.append("")
                if not commentary_rows:
                    lines.append("本轮没有逐标的 AI commentary。")
            elif title == "十三、组合层 AI Review":
                if portfolio_review:
                    lines.append(f"组合主题:{portfolio_review.get('theme', '')}")
                    lines.append(f"行业集中:{portfolio_review.get('industry_concentration', {})}")
                    lines.append(f"最大行业:{portfolio_review.get('top_sector', '')}")
                    lines.append(f"主要风险:{portfolio_review.get('major_risk_sources', [])}")
                    lines.append(f"现金评价:{portfolio_review.get('cash_level_comment', '')}")
                    lines.append(
                        "状态:AI_OPINION_NOT_A_FORMAL_INSTRUCTION;"
                        "正式现金/权重/风险以 FormalFactPacket 为准。"
                    )
                else:
                    lines.append("本轮没有组合层 AI Review。")
            elif title == "十四、AI 反方审查":
                for row in devils_rows:
                    lines.append(f"—— {row.get('ticker')}")
                    lines.append(f"失败模式:{row.get('quant_signal_failure_modes', [])}")
                    lines.append(f"近期负面:{row.get('recent_negative_events', [])}")
                    lines.append(f"结论:{row.get('conclusion', '')}")
                if not devils_rows:
                    lines.append("本轮没有反方审查记录。")
            elif title == "十五、ETF 研究观察 · 不需要操作":
                for row in etf_rows:
                    lines.append(
                        f"- {row.get('symbol')} [{row.get('sleeve')}] "
                        f"研究目标权重 {row.get('research_target_weight', '不适用')}"
                    )
                    lines.append("  是否需要操作:否 | 交易权限:NONE / RESEARCH_ONLY")
                    lines.append(f"  指标:{row.get('metric_note', '不适用')}")
                    lines.append(f"  AI 解读:{row.get('ai_interpretation', '')}")
                if not etf_rows:
                    lines.append("当前没有 ETF 研究观察标的。")
            elif title == "二十、未来 1-5 个交易日需要重点观察的事项":
                for row in watchlist:
                    lines.append(f"- {row}")
            elif title == "二十一、数据 / 模型局限":
                for row in limitations:
                    lines.append(f"- {row}")
                for row in uncertainties:
                    lines.append(f"- 不确定性:{row}")
            elif title == "二十二、最终人工执行提示":
                for row in manual_notes:
                    lines.append(f"- {row}")
                lines.append("- 请勿把研究候选当作正式持仓或订单。")
            continue
        value = payload.get(key)
        if isinstance(value, str) and value:
            lines.append(value)
        else:
            lines.append("不适用。")
        lines.append("")
    lines.append("")
    lines.append("正向视角【AI 解读】")
    lines.append(payload.get("bull_case", "暂无。"))
    return "\n".join(lines)


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
