"""ROUND29: AIActionCommentary and portfolio/devil's-advocate review.

The formal ticker, action and target weight are always copied from the
machine-generated facts. LLM text may add interpretation but cannot change any
formal number. If an LLM commentary payload is invalid, the deterministic
commentary remains.
"""

from __future__ import annotations

from typing import Any

LLM_VIEWS = frozenset(
    {"SUPPORTIVE", "NEUTRAL", "CAUTIOUS", "CONTRARIAN", "INSUFFICIENT_INFORMATION"}
)

ACTION_COMMENTARY_KEYS = frozenset(
    {
        "ticker",
        "company_name",
        "formal_action",
        "formal_target_weight",
        "llm_view",
        "support_level",
        "business_summary",
        "why_quant_may_like_it",
        "recent_positive_catalysts",
        "recent_negative_catalysts",
        "key_risks",
        "what_could_make_signal_wrong",
        "valuation_or_fundamental_context_if_available",
        "sector_context",
        "market_context",
        "earnings_or_filing_context",
        "event_risk",
        "liquidity_comment",
        "portfolio_role",
        "correlation_or_overlap_comment",
        "llm_counterargument",
        "human_review_focus",
    }
)


def _news_for_symbol(news: dict[str, Any] | None, symbol: str) -> list[dict[str, Any]]:
    if not isinstance(news, dict):
        return []
    rows = news.get("clusters")
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict) and symbol in (row.get("symbols") or [])
    ]


def build_deterministic_action_commentaries(
    *,
    facts: dict[str, Any],
    dossiers: dict[str, dict[str, Any]] | None = None,
    news: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a schema-valid, non-fabricated commentary for every formal action."""

    dossiers = dossiers or {}
    formal = facts.get("formal_actions") or facts.get("actions") or []
    commentaries: list[dict[str, Any]] = []
    for item in formal:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "")
        action = str(item.get("action") or "")
        target_weight = item.get("target_weight")
        risk_contribution = item.get("risk_contribution")
        expected_alpha = item.get("expected_alpha")
        dossier = dossiers.get(symbol, {})
        company_name = str(dossier.get("company_name") or "UNAVAILABLE")
        symbol_news = _news_for_symbol(news, symbol)
        recent_positive = (
            [str(row.get("canonical_headline") or row.get("title")) for row in symbol_news]
            if symbol_news
            else []
        )
        recent_negative = (
            [str(row.get("canonical_headline") or row.get("title")) for row in symbol_news]
            if symbol_news
            else []
        )
        support_level = 50
        llm_view = "NEUTRAL" if company_name != "UNAVAILABLE" else "INSUFFICIENT_INFORMATION"
        if company_name == "UNAVAILABLE":
            support_level = 0
        commentaries.append(
            {
                "ticker": symbol,
                "company_name": company_name,
                "formal_action": action,
                "formal_target_weight": target_weight,
                "llm_view": llm_view,
                "support_level": support_level,
                "business_summary": str(
                    dossier.get("business_summary")
                    or "公司业务资料当前不可用;禁止 LLM 凭记忆编造。"
                ),
                "why_quant_may_like_it": (
                    f"正式量化链给出 {action},预期 Alpha "
                    f"{expected_alpha if expected_alpha is not None else '不适用'},"
                    f"风险贡献 {risk_contribution if risk_contribution is not None else '不适用'}。"
                ),
                "recent_positive_catalysts": recent_positive
                or ["未发现可靠近期正面事件证据。"],
                "recent_negative_catalysts": recent_negative
                or ["未发现可靠近期负面事件证据。"],
                "key_risks": [
                    "历史研究认证 NOT_CERTIFIABLE",
                    "size neutralization degraded",
                    "事件风险与流动性风险需人工复核",
                ],
                "what_could_make_signal_wrong": (
                    "价格快速反转、公司/行业负面事件、流动性恶化或与市场 regime 冲突。"
                ),
                "valuation_or_fundamental_context_if_available": (
                    str(dossier.get("industry") or "UNAVAILABLE")
                ),
                "sector_context": str(dossier.get("sector") or "UNAVAILABLE"),
                "market_context": "LLM 不替代市场 regime;当前 regime 状态为 REGIME_UNAVAILABLE。",
                "earnings_or_filing_context": (
                    str(dossier.get("recent_filings") or "无可用 PIT filing evidence")
                ),
                "event_risk": recent_negative
                or ["未发现可靠反方证据。"],
                "liquidity_comment": "ADV/impact 数据当前未在 AI 层重新计算;以量化风险证书为准。",
                "portfolio_role": (
                    f"正式 {action} 建议,目标权重 "
                    f"{target_weight if target_weight is not None else '不适用'},"
                    f"风险贡献 {risk_contribution if risk_contribution is not None else '不适用'}。"
                ),
                "correlation_or_overlap_comment": (
                    "ETF look-through 不可用;AI 层不虚构持仓重叠。"
                ),
                "llm_counterargument": (
                    "该量化信号可能失败于反转、公司事件、流动性或集中风险;"
                    "未发现可靠反方证据时明确标注无证据。"
                ),
                "human_review_focus": (
                    "核实现价、流动性、近期事件和人工风险判断后再执行。"
                ),
            }
        )
    return commentaries


def build_deterministic_portfolio_review(
    *,
    facts: dict[str, Any],
    dossiers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """AI portfolio review based only on formal facts and current metadata."""

    dossiers = dossiers or {}
    formal = facts.get("formal_actions") or facts.get("actions") or []
    sectors: dict[str, int] = {}
    for item in formal:
        symbol = str(item.get("symbol") or "")
        sector = str(dossiers.get(symbol, {}).get("sector") or "UNKNOWN")
        sectors[sector] = sectors.get(sector, 0) + 1
    top_sector = max(sectors, key=lambda item: sectors[item]) if sectors else "UNKNOWN"
    risk = facts.get("risk") or {}
    return {
        "theme": "当前组合主题由正式 optimizer 结果决定;AI 只做解释。",
        "industry_concentration": dict(sorted(sectors.items(), key=lambda item: -item[1])),
        "top_sector": top_sector,
        "size_characteristics": "CURRENT_ONLY size evidence;未倒填历史。",
        "beta_volatility": {
            "expected_volatility": risk.get("expected_volatility"),
            "gross_exposure": risk.get("gross_exposure"),
            "cash_target": risk.get("cash_target"),
        },
        "major_risk_sources": list(risk.get("reasons") or ["UNAVAILABLE"]),
        "major_alpha_sources": "USAdaptiveAlphaCoreV1 formal alpha only.",
        "correlation_comment": "相关性与重叠风险以风险引擎为准;AI 不虚构。",
        "homogeneous_stock_comment": "未做 AI 层同质化判定;需基于风险模型相关矩阵。",
        "most_vulnerable": "未识别;无可靠反方证据时不做编造。",
        "strongest_quant_signal": "由正式 target/risk contribution 决定。",
        "llm_most_aligned": "无 LLM 自定义立场时保持 NEUTRAL。",
        "llm_most_concerned": "无可靠反方证据时保持 CAUTIOUS。",
        "common_risks": ["NOT_CERTIFIABLE", "size neutralization degraded", "事件/流动性风险"],
        "macro_sensitivity": "REGIME_UNAVAILABLE;AI 不替代 regime。",
        "event_sensitivity": "由 pre-execution 和新闻层标记人工复核。",
        "cash_level_comment": (
            f"现金目标 {risk.get('cash_target')};这是 optimizer 在成本/风险下的结果,"
            "不是 AI 可修改的正式数字。"
        ),
        "next_1_5_days": "观察正式标的新闻、pre-execution 状态与市场 regime。",
        "opinion_status": "AI_OPINION_NOT_A_FORMAL_INSTRUCTION",
    }


def build_deterministic_devils_advocate(
    *,
    facts: dict[str, Any],
    news: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-action devil's advocate review; never fabricates negative evidence."""

    formal = facts.get("formal_actions") or facts.get("actions") or []
    rows: list[dict[str, Any]] = []
    for item in formal:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "")
        symbol_news = _news_for_symbol(news, symbol)
        rows.append(
            {
                "ticker": symbol,
                "quant_signal_failure_modes": [
                    "价格反转",
                    "公司/行业负面事件",
                    "流动性恶化",
                    "估值或事件风险",
                    "拥挤交易",
                    "regime 冲突",
                ],
                "recent_negative_events": [
                    str(row.get("canonical_headline") or row.get("title"))
                    for row in symbol_news
                ]
                or ["未发现可靠反方证据"],
                "industry_risk": "UNAVAILABLE",
                "valuation_risk": "UNAVAILABLE",
                "liquidity_risk": "UNAVAILABLE",
                "event_risk": "以 pre-execution 为准",
                "crowding_risk": "UNAVAILABLE",
                "abnormal_price_behavior": "UNAVAILABLE",
                "regime_conflict": "REGIME_UNAVAILABLE",
                "conclusion": (
                    "未发现可靠反方证据"
                    if not symbol_news
                    else "存在已持久化新闻;建议人工复核。"
                ),
            }
        )
    return rows


def validate_llm_action_commentaries(
    payload: Any,
    *,
    allowed_symbols: frozenset[str],
) -> tuple[bool, str]:
    if not isinstance(payload, list):
        return False, "action_commentaries must be a list"
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != ACTION_COMMENTARY_KEYS:
            return False, f"action_commentaries[{index}] invalid keys"
        if item.get("ticker") not in allowed_symbols:
            return False, f"action_commentaries[{index}] ticker not formal"
        if item.get("llm_view") not in LLM_VIEWS:
            return False, f"action_commentaries[{index}] invalid llm_view"
        support = item.get("support_level")
        if not isinstance(support, int) or not 0 <= support <= 100:
            return False, f"action_commentaries[{index}] support_level must be int 0..100"
    return True, ""


def validate_llm_portfolio_review(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "portfolio_review must be an object"
    return True, ""


def validate_llm_devils_advocate(
    payload: Any,
    *,
    allowed_symbols: frozenset[str],
) -> tuple[bool, str]:
    if not isinstance(payload, list):
        return False, "devils_advocate must be a list"
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or item.get("ticker") not in allowed_symbols:
            return False, f"devils_advocate[{index}] invalid ticker"
    return True, ""


def merge_llm_action_commentaries(
    *,
    base: list[dict[str, Any]],
    llm: list[dict[str, Any]],
    facts: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge LLM interpretation while forcing formal fields from facts."""

    formal_by_symbol = {
        str(item.get("symbol")): item
        for item in (facts.get("formal_actions") or facts.get("actions") or [])
        if isinstance(item, dict)
    }
    base_by_symbol = {item["ticker"]: item for item in base}
    merged: list[dict[str, Any]] = []
    for row in llm:
        symbol = str(row.get("ticker") or row.get("symbol") or "")
        formal = formal_by_symbol.get(symbol)
        if formal is None:
            continue
        base_row = base_by_symbol.get(symbol, {})
        merged_row = dict(base_row)
        if isinstance(row.get("commentary"), str) and row.get("commentary"):
            merged_row["why_quant_may_like_it"] = str(row["commentary"])
            merged_row["llm_counterargument"] = str(row["commentary"])
        merged_row.update(
            {
                key: value
                for key, value in row.items()
                if key not in {
                    "ticker",
                    "symbol",
                    "action",
                    "formal_action",
                    "target_weight",
                    "formal_target_weight",
                    "commentary",
                }
            }
        )
        merged_row["ticker"] = symbol
        merged_row["formal_action"] = str(formal.get("action") or "")
        merged_row["formal_target_weight"] = formal.get("target_weight")
        merged.append(merged_row)
    return merged


def merge_llm_portfolio_review(
    *,
    base: dict[str, Any],
    llm: dict[str, Any],
) -> dict[str, Any]:
    """Merge LLM portfolio review without allowing formal portfolio numbers to change."""

    merged = dict(base)
    protected = {"beta_volatility", "cash_level_comment"}
    if isinstance(llm.get("summary"), str):
        merged["theme"] = str(llm["summary"])
    if isinstance(llm.get("concentration"), str):
        merged["major_risk_sources"] = [str(llm["concentration"])]
    if isinstance(llm.get("execution"), str):
        merged["common_risks"] = [str(llm["execution"])]
    for key, value in llm.items():
        if key in protected:
            continue
        merged[key] = value
    merged["opinion_status"] = "AI_OPINION_NOT_A_FORMAL_INSTRUCTION"
    return merged


def merge_llm_devils_advocate(
    *,
    base: list[dict[str, Any]],
    llm: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge devil's advocate rows by ticker; keep deterministic when absent."""

    by_symbol = {row.get("ticker"): row for row in base}
    merged: list[dict[str, Any]] = []
    for row in llm:
        symbol = row.get("ticker") or row.get("symbol")
        deterministic = by_symbol.get(symbol)
        if deterministic is None:
            continue
        combined = dict(deterministic)
        if isinstance(row.get("argument"), str):
            combined["quant_signal_failure_modes"] = [str(row["argument"])]
        if isinstance(row.get("counter"), str):
            combined["conclusion"] = str(row["counter"])
        combined.update(row)
        merged.append(combined)
    return merged
