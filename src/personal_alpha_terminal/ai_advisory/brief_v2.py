"""ROUND25 PHASE 3/6: DailyAIBriefV2 -- multi-stage DeepSeek analysis.

PASS 1: fact extraction / structured summary
PASS 2: portfolio & risk critic
PASS 3: market / news synthesis
PASS 4: final Chinese daily brief (strict JSON)

Each stage produces structured JSON.  A failed stage degrades to its
deterministic counterpart; the other stages continue.  The final brief is
schema-validated, then passed through the semantic-grounding validator, then
quarantined on any mismatch.  The LLM keeps zero authority over trades,
weights or strategy parameters.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from personal_alpha_terminal.agents.llm.schemas import LLMRequest
from personal_alpha_terminal.ai_advisory.action_commentary import (
    build_deterministic_action_commentaries,
    build_deterministic_devils_advocate,
    build_deterministic_portfolio_review,
    merge_llm_action_commentaries,
    merge_llm_devils_advocate,
    merge_llm_portfolio_review,
    validate_llm_action_commentaries,
    validate_llm_devils_advocate,
    validate_llm_portfolio_review,
)
from personal_alpha_terminal.ai_advisory.facts_v3 import build_facts_v3
from personal_alpha_terminal.ai_advisory.grounding import (
    GROUNDING_OK,
    GROUNDING_QUARANTINED,
    validate_semantic_grounding,
)
from personal_alpha_terminal.ai_advisory.grounding_v3 import (
    SECTION_LEVEL_QUARANTINED,
    quarantine_sections,
)
from personal_alpha_terminal.ai_advisory.schemas import (
    LLM_BUY_SELL_AUTHORITY,
    LLM_TARGET_WEIGHT_AUTHORITY,
    LLM_TRADE_AUTHORITY,
    PRODUCTION_INFLUENCE,
)

SCHEMA_VERSION_V2 = "ai-brief-zh-v2"
PROMPT_VERSION_V2 = "ai-brief-zh-prompt-v2"

V2_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "executive_summary",
        "formal_conclusions",
        "market_state",
        "index_analysis",
        "breadth_analysis",
        "factor_rotation",
        "macro_context",
        "important_news",
        "sec_events",
        "formal_action_explanations",
        "etf_research_analysis",
        "action_commentaries",
        "portfolio_review",
        "devils_advocate",
        "company_dossiers",
        "portfolio_risk_analysis",
        "overnight_risk",
        "bear_case",
        "bull_case",
        "uncertainties",
        "watchlist_next_sessions",
        "data_limitations",
        "manual_execution_notes",
    }
)

NEWS_ENTRY_KEYS = frozenset(
    {"evidence_ref", "headline", "why_matters", "affected", "portfolio_link", "strength"}
)

ACTION_EXPLANATION_KEYS_V2 = frozenset(
    {
        "symbol",
        "action",
        "quant_alpha",
        "target_weight",
        "risk_contribution",
        "cost",
        "ai_explanation",
        "evidence_refs",
    }
)

ETF_RESEARCH_KEYS_V2 = frozenset(
    {
        "symbol",
        "sleeve",
        "research_target_weight",
        "metric_note",
        "ai_interpretation",
        "evidence_refs",
    }
)

SYSTEM_PROMPT_V2 = (
    "你是个人量化终端的中文每日市场与量化研判引擎。你的唯一角色是:把已经由确定性"
    "量化流水线计算出的结果,用专业、自然、诚实、完整的中文解释给用户。\n"
    "硬性规则:\n"
    f"1. 你只能解释输入事实里出现的内容。禁止编造新闻、SEC 文件、分析师观点或任何"
    f"输入中没有的事件。每条新闻必须带 evidence_ref,且只能引用 facts.news 里存在"
    f"的 id。\n"
    f"2. 你的交易权限 = {LLM_TRADE_AUTHORITY},目标权重权限 = "
    f"{LLM_TARGET_WEIGHT_AUTHORITY},买入卖出权限 = {LLM_BUY_SELL_AUTHORITY},"
    f"生产决策影响 = {PRODUCTION_INFLUENCE}。你不得给出任何直接买卖指令,不得修改"
    f"任何权重。\n"
    "3. 必须区分事实与解释:量化数字是事实,你对它们的看法是解释。\n"
    "4. 语义域硬性隔离:formal_actions 是正式量化结论;research_candidates 是研究"
    "候选(交易权限 NONE,不属于今日执行计划),只能写“研究候选,尚未进入正式交易链”;"
    "context_only 只是上下文,绝不能描述为目标仓位。绝不能把研究候选描述为“当前"
    "组合配置/持仓/已买入”,绝不能给它们任何 BUY/SELL 表述。\n"
    "5. 组合现金、正式动作数量、正式总敞口只能引用输入数字,禁止自行加减或发明。\n"
    "6. 数字单位必须与输入声明一致:momentum_252_21 是 12 个月累计收益(decimal),"
    "momentum_vol_ratio 是动量/年化波动率无量纲比值,禁止称作 Alpha 或乘 100。\n"
    "7. 只输出一个 JSON 对象,严格匹配给定 schema,不要输出任何其它文本、代码块"
    "标记或解释。全部内容使用简体中文。\n"
)


def _raw_call(
    provider_factory: Callable[[], Any] | None,
    *,
    model: str,
    user_prompt: str,
    max_tokens: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """One raw structured call; returns (payload|None, usage)."""

    usage: dict[str, Any] = {
        "status": "NOT_CALLED",
        "latency_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    if provider_factory is None:
        return None, usage
    request = LLMRequest(
        system_prompt=SYSTEM_PROMPT_V2,
        user_prompt=user_prompt,
        temperature=0.2,
        prompt_version=PROMPT_VERSION_V2,
        as_of=datetime.now(UTC),
        max_tokens=max_tokens,
        thinking="disabled",
    )
    try:
        response = provider_factory().generate(request)
    except Exception as exc:  # noqa: BLE001 - provider isolation boundary
        usage["status"] = type(exc).__name__.upper()
        return None, usage
    content = str(getattr(response, "content", "") or "").strip()
    usage.update(
        {
            "status": "OK" if content else "EMPTY_RESPONSE",
            "latency_ms": int(getattr(response, "latency_ms", 0) or 0),
            "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(response, "completion_tokens", 0) or 0),
        }
    )
    if not content:
        return None, usage
    usage["raw_response"] = content
    normalized = content
    if normalized.startswith("```"):
        first = normalized.find("\n")
        last = normalized.rfind("```")
        normalized = (
            normalized[first + 1 : last].strip()
            if first != -1 and last > first
            else normalized
        )
        usage["normalization"] = "MARKDOWN_FENCE_REMOVED"
    # Deterministic syntax-only normalization.  It never invents absent
    # sections, symbols, weights or news facts.
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = re.sub(r",\s*([}\]])", r"\1", normalized)
    try:
        decoder = json.JSONDecoder()
        payload, end = decoder.raw_decode(normalized.lstrip())
        trailing = normalized.lstrip()[end:].strip()
        if trailing:
            usage["normalization"] = "TRAILING_PROSE_IGNORED"
    except json.JSONDecodeError:
        usage["status"] = "JSON_DECODE_ERROR"
        usage["parse_error_class"] = "JSON_DECODE_ERROR"
        return None, usage
    if not isinstance(payload, dict):
        usage["status"] = "JSON_NOT_OBJECT"
        usage["parse_error_class"] = "JSON_NOT_OBJECT"
        return None, usage
    usage["parsed_response"] = payload
    return payload, usage


def _pass1_prompt(facts: dict[str, Any]) -> str:
    formal = json.dumps(facts.get("formal_actions", []), ensure_ascii=False, default=str)
    research = json.dumps(
        facts.get("research_candidates", []), ensure_ascii=False, default=str
    )
    return (
        "PASS 1 事实抽取:从以下量化事实中抽取结构化摘要,输出严格 JSON:"
        '{"formal_count": int, "formal_symbols": [str], "research_count": int, '
        '"research_symbols": [str], "cash_and_portfolio": str, "gates": str, '
        '"research_certification": str}。\n\n'
        f"formal_actions={formal}\nresearch_candidates={research}\n"
        f"portfolio={json.dumps(facts.get('portfolio', {}), default=str)}\n"
        f"research_certification_state={facts.get('research_certification_state')}\n"
    )


def _pass2_prompt(facts: dict[str, Any]) -> str:
    return (
        "PASS 2 组合与风险批判:基于量化事实,给出批评性风险观点,输出严格 JSON:"
        '{"risk_critic": str, "concentration_risks": [str], '
        '"execution_risks": [str], "unknowns": [str]}。\n\n'
        f"facts={json.dumps(facts, ensure_ascii=False, default=str)[:6000]}\n"
    )


def _pass3_prompt(
    facts: dict[str, Any],
    market_state: dict[str, Any] | None,
    news: dict[str, Any] | None,
) -> str:
    news_rows = (news or {}).get("clusters") or (news or {}).get("items") or []
    return (
        "PASS 3 市场与新闻综合:基于以下 QUANT_FACT 市场状态与已持久化新闻,输出"
        "严格 JSON:"
        '{"market_synthesis": str, "index_view": str, "breadth_view": str, '
        '"macro_view": str, "news_events": [{"evidence_ref": str, '
        '"headline": str, "why_matters": str, "affected": str, '
        '"portfolio_link": str, "strength": str}]}。'
        "只能引用输入中存在的新闻与数字,禁止发明。\n\n"
        f"market_state={json.dumps(market_state or {}, default=str)[:5000]}\n"
        f"news={json.dumps(news_rows, default=str)[:5000]}\n"
        f"benchmarks={json.dumps(facts.get('benchmarks', []), default=str)}\n"
    )


def _pass4_prompt(
    facts: dict[str, Any],
    pass1: dict[str, Any],
    pass2: dict[str, Any],
    pass3: dict[str, Any],
) -> str:
    return (
        "PASS 4 最终叙事综合:只输出一个严格 JSON 对象，不要代码块或其它文字。"
        "不要重算或复述正式股票、动作数量、现金、总敞口、权重、成本、基准收益。"
        "这些由程序生成。只解释市场、风险、叙事、观察项与局限。结构必须恰好为:\n"
        '{"market_interpretation":"string","risk_interpretation":"string",'
        '"narrative":"string","watch_list":["string"],"limitations":["string"],'
        '"action_commentaries":[{...}],"portfolio_review":{...},'
        '"devils_advocate":[{...}]}\n'
        "action_commentaries/portfolio_review/devils_advocate 是可选字段;"
        "如果返回,必须只引用 FormalFactPacket 中的正式 ticker/action/target weight,"
        "不得改变这些数字。LLM 观点仅用于解释。\n\n"
        f"validated_pass1={json.dumps(pass1, ensure_ascii=False, default=str)[:2200]}\n"
        f"validated_pass2={json.dumps(pass2, ensure_ascii=False, default=str)[:2600]}\n"
        f"validated_pass3={json.dumps(pass3, ensure_ascii=False, default=str)[:3200]}\n"
        "fact_references="
        f"{json.dumps(facts.get('evidence_refs', []), ensure_ascii=False, default=str)[:1200]}\n"
        "formal_facts="
        f"{json.dumps(build_facts_v3(facts_v2=facts), ensure_ascii=False, default=str)[:6000]}\n"
    )


def _validate_pass1(payload: dict[str, Any]) -> tuple[bool, str]:
    expected = {
        "formal_count", "formal_symbols", "research_count", "research_symbols",
        "cash_and_portfolio", "gates", "research_certification",
    }
    if set(payload) != expected:
        return False, "PASS1 keys mismatch"
    if not isinstance(payload["formal_count"], int) or not isinstance(
        payload["research_count"], int
    ):
        return False, "PASS1 counts must be integers"
    if not all(isinstance(item, str) for item in payload["formal_symbols"]):
        return False, "PASS1 formal_symbols must be strings"
    if not all(isinstance(item, str) for item in payload["research_symbols"]):
        return False, "PASS1 research_symbols must be strings"
    return True, ""


def _validate_pass2(payload: dict[str, Any]) -> tuple[bool, str]:
    expected = {"risk_critic", "concentration_risks", "execution_risks", "unknowns"}
    if set(payload) != expected or not isinstance(payload.get("risk_critic"), str):
        return False, "PASS2 schema mismatch"
    if not all(
        isinstance(item, str)
        for key in expected - {"risk_critic"}
        for item in payload.get(key, [])
    ):
        return False, "PASS2 list fields must contain strings"
    return True, ""


def _validate_pass3(payload: dict[str, Any]) -> tuple[bool, str]:
    expected = {"market_synthesis", "index_view", "breadth_view", "macro_view", "news_events"}
    if set(payload) != expected:
        return False, "PASS3 keys mismatch"
    if not all(isinstance(payload.get(key), str) for key in expected - {"news_events"}):
        return False, "PASS3 narrative fields must be strings"
    if not isinstance(payload.get("news_events"), list):
        return False, "PASS3 news_events must be a list"
    return True, ""


def _validate_pass4_synthesis(payload: dict[str, Any]) -> tuple[bool, str]:
    expected = {
        "market_interpretation",
        "risk_interpretation",
        "narrative",
        "watch_list",
        "limitations",
    }
    optional = {"action_commentaries", "portfolio_review", "devils_advocate"}
    unknown = set(payload) - expected - optional
    if unknown:
        return False, f"PASS4 synthesis unknown keys: {sorted(unknown)}"
    missing = expected - set(payload)
    if missing:
        return False, f"PASS4 synthesis missing keys: {sorted(missing)}"
    if not all(
        isinstance(payload.get(key), str)
        for key in expected - {"watch_list", "limitations"}
    ):
        return False, "PASS4 narrative fields must be strings"
    if not all(
        isinstance(item, str)
        for key in ("watch_list", "limitations")
        for item in payload.get(key, [])
    ):
        return False, "PASS4 lists must contain strings"
    if "action_commentaries" in payload and not isinstance(
        payload["action_commentaries"], list
    ):
        return False, "PASS4 action_commentaries must be a list"
    if "portfolio_review" in payload and not isinstance(payload["portfolio_review"], dict):
        return False, "PASS4 portfolio_review must be an object"
    if "devils_advocate" in payload and not isinstance(payload["devils_advocate"], list):
        return False, "PASS4 devils_advocate must be a list"
    return True, ""


V2_SCHEMA_HINT = json.dumps(
    {
        "schema_version": SCHEMA_VERSION_V2,
        "executive_summary": "string",
        "formal_conclusions": "string",
        "market_state": "string",
        "index_analysis": "string",
        "breadth_analysis": "string",
        "factor_rotation": "string",
        "macro_context": "string",
        "important_news": [
            {
                "evidence_ref": "string",
                "headline": "string",
                "why_matters": "string",
                "affected": "string",
                "portfolio_link": "string",
                "strength": "string",
            }
        ],
        "sec_events": ["string"],
        "formal_action_explanations": [
            {
                "symbol": "string",
                "action": "string",
                "quant_alpha": "string",
                "target_weight": "string",
                "risk_contribution": "string",
                "cost": "string",
                "ai_explanation": "string",
                "evidence_refs": ["string"],
            }
        ],
        "etf_research_analysis": [
            {
                "symbol": "string",
                "sleeve": "string",
                "research_target_weight": "string",
                "metric_note": "string",
                "ai_interpretation": "string",
                "evidence_refs": ["string"],
            }
        ],
        "action_commentaries": [
            {
                "ticker": "string",
                "company_name": "string",
                "formal_action": "string",
                "formal_target_weight": "number",
                "llm_view": "SUPPORTIVE|NEUTRAL|CAUTIOUS|CONTRARIAN|INSUFFICIENT_INFORMATION",
                "support_level": "int 0-100",
                "business_summary": "string",
                "why_quant_may_like_it": "string",
                "recent_positive_catalysts": ["string"],
                "recent_negative_catalysts": ["string"],
                "key_risks": ["string"],
                "what_could_make_signal_wrong": "string",
                "valuation_or_fundamental_context_if_available": "string",
                "sector_context": "string",
                "market_context": "string",
                "earnings_or_filing_context": "string",
                "event_risk": ["string"],
                "liquidity_comment": "string",
                "portfolio_role": "string",
                "correlation_or_overlap_comment": "string",
                "llm_counterargument": "string",
                "human_review_focus": "string",
            }
        ],
        "portfolio_review": {
            "theme": "string",
            "industry_concentration": {},
            "top_sector": "string",
            "size_characteristics": "string",
            "beta_volatility": {},
            "major_risk_sources": ["string"],
            "major_alpha_sources": "string",
            "correlation_comment": "string",
            "homogeneous_stock_comment": "string",
            "most_vulnerable": "string",
            "strongest_quant_signal": "string",
            "llm_most_aligned": "string",
            "llm_most_concerned": "string",
            "common_risks": ["string"],
            "macro_sensitivity": "string",
            "event_sensitivity": "string",
            "cash_level_comment": "string",
            "next_1_5_days": ["string"],
            "opinion_status": "string"
        },
        "devils_advocate": [
            {
                "ticker": "string",
                "quant_signal_failure_modes": ["string"],
                "recent_negative_events": ["string"],
                "industry_risk": "string",
                "valuation_risk": "string",
                "liquidity_risk": "string",
                "event_risk": "string",
                "crowding_risk": "string",
                "abnormal_price_behavior": "string",
                "regime_conflict": "string",
                "conclusion": "string"
            }
        ],
        "portfolio_risk_analysis": "string",
        "overnight_risk": "string",
        "bear_case": "string",
        "bull_case": "string",
        "uncertainties": ["string"],
        "watchlist_next_sessions": ["string"],
        "data_limitations": ["string"],
        "manual_execution_notes": ["string"],
    },
    ensure_ascii=False,
)


def validate_brief_v2(
    payload: Any,
    *,
    allowed_action_symbols: frozenset[str],
    allowed_research_symbols: frozenset[str],
) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"
    extra = set(payload) - V2_TOP_LEVEL_KEYS
    if extra:
        return False, f"unknown top-level keys: {sorted(extra)}"
    if payload.get("schema_version") != SCHEMA_VERSION_V2:
        return False, "schema_version must be " + SCHEMA_VERSION_V2
    for key in (
        "executive_summary",
        "formal_conclusions",
        "market_state",
        "index_analysis",
        "breadth_analysis",
        "factor_rotation",
        "macro_context",
        "portfolio_risk_analysis",
        "overnight_risk",
        "bear_case",
        "bull_case",
    ):
        if not isinstance(payload.get(key), str):
            return False, f"{key} must be a string"
    for index, item in enumerate(payload.get("important_news", []) or []):
        if not isinstance(item, dict) or set(item) - NEWS_ENTRY_KEYS:
            return False, f"important_news[{index}] invalid"
        if not isinstance(item.get("evidence_ref"), str):
            return False, f"important_news[{index}] evidence_ref must be a string"
    for index, item in enumerate(payload.get("formal_action_explanations", []) or []):
        if not isinstance(item, dict) or set(item) - ACTION_EXPLANATION_KEYS_V2:
            return False, f"formal_action_explanations[{index}] invalid"
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or symbol not in allowed_action_symbols:
            return False, (
                f"formal_action_explanations[{index}] symbol {symbol!r} is not a "
                "formal action symbol (hallucination guard)"
            )
        if not isinstance(item.get("ai_explanation"), str):
            return False, f"formal_action_explanations[{index}] ai_explanation required"
    raw_commentaries = payload.get("action_commentaries")
    if raw_commentaries is not None:
        ok, error = validate_llm_action_commentaries(
            raw_commentaries, allowed_symbols=allowed_action_symbols
        )
        if not ok:
            return False, error
    portfolio_review = payload.get("portfolio_review")
    if portfolio_review is not None and not isinstance(portfolio_review, dict):
        return False, "portfolio_review must be an object"
    devils_advocate = payload.get("devils_advocate")
    if devils_advocate is not None and not isinstance(devils_advocate, list):
        return False, "devils_advocate must be a list"
    for index, item in enumerate(payload.get("etf_research_analysis", []) or []):
        if not isinstance(item, dict) or set(item) - ETF_RESEARCH_KEYS_V2:
            return False, f"etf_research_analysis[{index}] invalid"
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or symbol not in allowed_research_symbols:
            return False, (
                f"etf_research_analysis[{index}] symbol {symbol!r} is not a "
                "research-candidate symbol (hallucination guard)"
            )
    for key in (
        "sec_events",
        "uncertainties",
        "watchlist_next_sessions",
        "data_limitations",
        "manual_execution_notes",
    ):
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False, f"{key} must be a list of strings"
    return True, ""


def _pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "不适用"


def build_deterministic_v2(
    facts: dict[str, Any],
    *,
    market_state: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    pre_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Schema-valid deterministic DailyAIBriefV2 from facts alone."""

    formal = facts.get("formal_actions") or facts.get("actions") or []
    research = facts.get("research_candidates") or []
    portfolio = facts.get("portfolio") or {}
    benchmarks = facts.get("benchmarks") or []
    formal_names = ", ".join(str(item.get("symbol")) for item in formal) or "无"
    buy_count = sum(1 for item in formal if item.get("action") == "BUY")
    summary = (
        f"今日量化流水线完成,生成 {len(formal)} 条正式操作建议(买入 {buy_count} 条)。"
        f"正式标的:{formal_names}。研究认证状态为 "
        f"{facts.get('research_certification_state')},概率生产权重为 "
        f"{facts.get('probability_influence')},LLM 生产影响 NONE,"
        "自动执行禁用,手动执行仅限人工确认。"
    )
    benchmark_text = " ".join(
        f"{item.get('symbol')} 期间收益 {_pct(item.get('period_return'))},"
        f"年化波动 {_pct(item.get('annualized_volatility'))}"
        for item in benchmarks
    ) or "基准数据不可用。"
    market_lines: list[str] = []
    if isinstance(market_state, dict):
        breadth = market_state.get("breadth") or {}
        market_lines.append(
            "市场宽度(量化事实):站上 MA20 "
            f"{_pct(breadth.get('breadth_pct_above_ma20'))},站上 MA50 "
            f"{_pct(breadth.get('breadth_pct_above_ma50'))},站上 MA200 "
            f"{_pct(breadth.get('breadth_pct_above_ma200'))};"
            f"5 日为正 {_pct(breadth.get('breadth_pct_positive_5d'))},"
            f"20 日为正 {_pct(breadth.get('breadth_pct_positive_20d'))}。"
        )
        for item in (market_state.get("basket") or [])[:6]:
            if item.get("available"):
                returns = item.get("returns") or {}
                market_lines.append(
                    f"{item.get('symbol')}({item.get('role')}) 1D "
                    f"{_pct(returns.get('return_1d'))},20D "
                    f"{_pct(returns.get('return_20d'))},252D "
                    f"{_pct(returns.get('return_252d'))}。"
                )
    market_state_text = "\n".join(market_lines) or "市场状态数据不可用。"
    news_clusters = (news or {}).get("clusters") or []
    important_news: list[dict[str, str]] = []
    for cluster in news_clusters[:20]:
        headline = str(cluster.get("title") or cluster.get("canonical_headline") or "")
        source = str(cluster.get("source") or "")
        published_at = str(cluster.get("published_at") or "")
        event_type = str(cluster.get("event_type") or "")
        freshness = str(cluster.get("freshness_bucket") or "UNKNOWN")
        if (
            not headline
            or not source
            or not published_at
            or not event_type
            or freshness == "HISTORICAL_CONTEXT"
        ):
            continue
        source_count = cluster.get("source_count")
        source_count_text = str(source_count) if source_count is not None else "UNKNOWN"
        important_news.append(
            {
                "evidence_ref": str(cluster.get("evidence_ref") or cluster.get("event_cluster_id")),
                "headline": f"{headline} | {source} | {published_at} | {event_type}",
                "why_matters": "该条目在 decision cutoff 前且通过确定性相关性筛选。",
                "affected": (
                    ", ".join(str(item) for item in (cluster.get("symbols") or []))
                    or "未知"
                ),
                "portfolio_link": (
                    "与正式组合存在 ticker 关联。"
                    if cluster.get("relation") == "ticker"
                    else "市场/宏观关联；不改变正式组合。"
                ),
                "strength": (
                    f"source_count={source_count_text}; "
                    f"{cluster.get('evidence_strength', 'UNKNOWN')}; "
                    f"freshness={freshness}; "
                    f"decision_cutoff_relation="
                    f"{cluster.get('decision_cutoff_relation', 'PRE_DECISION')}"
                ),
            }
        )
    historical_context = (news or {}).get("historical_context") or []
    default_refs = facts.get("evidence_refs") or []
    run_refs = [
        ref for ref in default_refs
        if str(ref).startswith(("run:", "decision:", "decision-manifest:"))
    ] or (
        [f"run:{facts.get('run_id')}"]
        if facts.get("run_id")
        else []
    )
    action_explanations: list[dict[str, Any]] = []
    for item in formal:
        symbol = str(item.get("symbol"))
        action_explanations.append(
            {
                "symbol": symbol,
                "action": str(item.get("action", "")),
                "quant_alpha": _pct(item.get("expected_alpha")),
                "target_weight": _pct(item.get("target_weight")),
                "risk_contribution": _pct(item.get("risk_contribution")),
                "cost": str(item.get("estimated_cost", "不适用")),
                "ai_explanation": (
                    f"{symbol} 为正式量化买入建议:预期 Alpha "
                    f"{_pct(item.get('expected_alpha'))},目标权重 "
                    f"{_pct(item.get('target_weight'))},已通过 SIGNAL→PORTFOLIO→"
                    "RISK→DECISION→EXECUTION 正式链。最终执行由用户人工确认。"
                ),
                "evidence_refs": list(run_refs),
            }
        )
    etf_analysis: list[dict[str, Any]] = []
    for item in research:
        symbol = str(item.get("symbol"))
        momentum = item.get("momentum_252_21")
        ratio = item.get("momentum_vol_ratio")
        metric_note = (
            f"12M 累计动量 {_pct(momentum)}(DECIMAL_RETURN);动量/年化波动率比值 "
            f"{float(ratio):.3f}(RATIO,无量纲,不是 Alpha)。"
            if momentum is not None and ratio is not None
            else "指标不可用。"
        )
        etf_analysis.append(
            {
                "symbol": symbol,
                "sleeve": str(item.get("sleeve", "ETF")),
                "research_target_weight": _pct(item.get("research_target_weight")),
                "metric_note": metric_note,
                "ai_interpretation": (
                    f"{symbol} 当前为研究候选(RESEARCH_CANDIDATE),研究目标权重 "
                    f"{_pct(item.get('research_target_weight'))},交易权限 NONE,"
                    "不属于今日执行计划;它尚未进入正式交易链,不能被理解为持仓或"
                    "买卖指令。"
                ),
                "evidence_refs": list(run_refs),
            }
        )
    pre_text = "隔夜/盘前风险检查数据不可用(PRE_EXECUTION_DATA_UNAVAILABLE)。"
    if isinstance(pre_execution, dict):
        pre_text = (
            f"隔夜/盘前风险检查状态:{pre_execution.get('status')}。"
            "该层不自动取消订单、不重算昨日 Alpha,LLM 没有取消权限;"
            "人工复核要求以终端横幅为准。"
        )
    raw_dossiers = facts.get("company_dossiers")
    if isinstance(raw_dossiers, dict):
        dossier_map = {
            str(key): value
            for key, value in raw_dossiers.items()
            if isinstance(value, dict)
        }
    elif isinstance(raw_dossiers, list):
        dossier_map = {
            str(item.get("ticker")): item
            for item in raw_dossiers
            if isinstance(item, dict) and item.get("ticker")
        }
    else:
        dossier_map = {}
    action_commentaries = build_deterministic_action_commentaries(
        facts=facts,
        dossiers=dossier_map,
        news=news,
    )
    portfolio_review = build_deterministic_portfolio_review(
        facts=facts,
        dossiers=dossier_map,
    )
    devils_advocate = build_deterministic_devils_advocate(facts=facts, news=news)
    return {
        "schema_version": SCHEMA_VERSION_V2,
        "executive_summary": summary,
        "formal_conclusions": (
            f"正式操作 {len(formal)} 条,全部需人工确认后手工执行;"
            "ETF 研究候选不计入正式结论。"
        ),
        "market_state": market_state_text,
        "index_analysis": benchmark_text,
        "breadth_analysis": market_state_text,
        "factor_rotation": (
            f"因子数 {facts.get('factor_count')},候选数 {facts.get('candidate_count')};"
            "轮动解读仅基于已冻结的因子统计,不构成预测。"
        ),
        "macro_context": (
            "宏观环境仅基于 decision cutoff 前的官方宏观条目;"
            "今日新闻区不包含 HISTORICAL_CONTEXT。"
            if important_news
            else (
                f"本次今日新闻区无满足 PIT 与展示完整性条件的官方宏观条目;"
                f"历史宏观背景 {len(historical_context)} 条已移至历史背景区。"
                if historical_context
                else "本次无满足 PIT 与展示完整性条件的官方宏观条目。"
            )
        ),
        "important_news": important_news,
        "sec_events": [
            "当前没有可用于任何正式标的的 PIT 企业事件证据;ETF 不适用公司级 SEC 事件分析。"
        ],
        "formal_action_explanations": action_explanations,
        "etf_research_analysis": etf_analysis,
        "action_commentaries": action_commentaries,
        "portfolio_review": portfolio_review,
        "devils_advocate": devils_advocate,
        "company_dossiers": dossier_map,
        "portfolio_risk_analysis": (
            f"组合信息:{portfolio}。风险解释仅基于不可变运行证书;"
            "正式敞口为正式目标权重之和,研究候选权重不计入。"
        ),
        "overnight_risk": pre_text,
        "bear_case": (
            "反向视角:历史研究仍为 NOT_CERTIFIABLE,当前建议不代表可回测的历史"
            "有效性;动量因子在快速反转行情中可能表现不佳。"
        ),
        "bull_case": (
            "正向视角:所有正式建议均已通过数据、PIT、信号、组合、风险、决策与"
            "执行门禁,且在显式 Operational Policy 允许范围内。"
        ),
        "uncertainties": [
            "历史研究认证状态为 NOT_CERTIFIABLE。",
            "ETF 成分穿透(holdings look-through)当前不可用,重叠风险仅基于相关性。",
            "LLM 研判不参与任何交易决策。",
        ],
        "watchlist_next_sessions": [
            "未来 1-5 个交易日重点观察:隔夜/盘前风险检查状态与正式标的的新闻事件。"
        ],
        "data_limitations": list(facts.get("data_gaps") or ["未记录到数据缺口。"]),
        "manual_execution_notes": [
            "所有正式操作必须人工确认后经 Charles Schwab 手工执行;"
            "系统无 Broker API,无自动下单,LLM 无交易权限。"
        ],
    }


def apply_deepseek_synthesis(
    brief: dict[str, Any],
    pass4_payload: dict[str, Any],
    *,
    facts: dict[str, Any],
    allowed_action: frozenset[str],
) -> dict[str, Any]:
    """Merge LLM synthesis while protecting critical formal sections.

    Critical formal sections (executive_summary, formal_conclusions,
    portfolio_risk_analysis) remain deterministic.  The LLM may provide
    market/commentary/portfolio-review narrative; any wrong formal numbers in
    non-critical sections can be quarantined section-by-section without
    invalidating the formal facts.
    """

    brief = dict(brief)
    brief.update(
        {
            "market_state": str(pass4_payload.get("market_interpretation", "")),
            "macro_context": str(pass4_payload.get("market_interpretation", "")),
            "bear_case": str(pass4_payload.get("narrative", "")),
            "bull_case": str(pass4_payload.get("narrative", "")),
            "watchlist_next_sessions": list(pass4_payload.get("watch_list") or []),
            "data_limitations": list(pass4_payload.get("limitations") or []),
        }
    )
    llm_commentaries = pass4_payload.get("action_commentaries")
    llm_review = pass4_payload.get("portfolio_review")
    llm_devil = pass4_payload.get("devils_advocate")
    if isinstance(llm_commentaries, list):
        comments_ok, _ = validate_llm_action_commentaries(
            llm_commentaries, allowed_symbols=allowed_action
        )
        if comments_ok:
            brief["action_commentaries"] = merge_llm_action_commentaries(
                base=brief["action_commentaries"],
                llm=llm_commentaries,
                facts=facts,
            )
    if isinstance(llm_review, dict):
        review_ok, _ = validate_llm_portfolio_review(llm_review)
        if review_ok:
            brief["portfolio_review"] = merge_llm_portfolio_review(
                base=brief["portfolio_review"],
                llm=llm_review,
            )
    if isinstance(llm_devil, list):
        devil_ok, _ = validate_llm_devils_advocate(
            llm_devil, allowed_symbols=allowed_action
        )
        if devil_ok:
            brief["devils_advocate"] = merge_llm_devils_advocate(
                base=brief["devils_advocate"],
                llm=llm_devil,
            )
    return brief


@dataclass(frozen=True, slots=True)
class AiBriefV2Result:
    run_id: str
    model: str
    prompt_version: str
    llm_status: str
    ai_status: str
    source: str
    brief: dict[str, Any]
    passes: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    semantic_grounding_status: str = GROUNDING_OK
    semantic_grounding_issues: tuple[str, ...] = ()
    section_report: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    production_influence: str = PRODUCTION_INFLUENCE

    def document(self) -> dict[str, Any]:
        fallback_sections = list(self.section_report.get("quarantined_sections", []))
        deepseek_sections_used = 5 if self.source.startswith("DEEPSEEK") else 0
        return {
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "llm_status": self.llm_status,
            "ai_status": self.ai_status,
            "source": self.source,
            "brief": self.brief,
            "passes": dict(self.passes),
            "llm_calls": {
                "total_calls": self.usage.get("total_calls", 0),
                "prompt_tokens": self.usage.get("prompt_tokens", 0),
                "completion_tokens": self.usage.get("completion_tokens", 0),
                "latency_ms": self.usage.get("latency_ms", 0),
            },
            "semantic_grounding_status": self.semantic_grounding_status,
            "semantic_grounding_issues": list(self.semantic_grounding_issues),
            "section_report": dict(self.section_report),
            "deepseek_sections_used": deepseek_sections_used,
            "deepseek_sections_total": 5,
            "fallback_sections": fallback_sections,
            "generated_at": self.generated_at.isoformat(),
            "production_influence": self.production_influence,
        }


class AiBriefV2Service:
    """Multi-stage DeepSeek brief orchestration with quarantine fallback."""

    def generate(
        self,
        *,
        run_id: str,
        facts: dict[str, Any],
        model: str,
        provider_factory: Callable[[], Any] | None,
        market_state: dict[str, Any] | None = None,
        news: dict[str, Any] | None = None,
        pre_execution: dict[str, Any] | None = None,
        decision_manifest: dict[str, Any] | None = None,
    ) -> AiBriefV2Result:
        allowed_action = frozenset(facts.get("allowed_action_symbols", []))
        allowed_research = frozenset(facts.get("allowed_research_symbols", []))
        usage: dict[str, Any] = {
            "total_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0,
        }

        def run_pass(
            name: str,
            prompt: str,
            max_tokens: int,
            validator: Callable[[dict[str, Any]], tuple[bool, str]],
        ) -> dict[str, Any]:
            nonlocal usage
            payload, call_usage = _raw_call(
                provider_factory, model=model, user_prompt=prompt, max_tokens=max_tokens
            )
            usage["total_calls"] += 1
            usage["prompt_tokens"] += call_usage.get("prompt_tokens", 0)
            usage["completion_tokens"] += call_usage.get("completion_tokens", 0)
            usage["latency_ms"] += call_usage.get("latency_ms", 0)
            valid, schema_error = (
                validator(payload)
                if payload is not None
                else (False, "no JSON object")
            )
            return {
                "name": name,
                "status": (
                    "PASS"
                    if valid
                    else f"SCHEMA_INVALID: {schema_error}"
                ),
                "payload": payload or {},
                "raw_response": call_usage.get("raw_response", ""),
                "parsed_response": call_usage.get("parsed_response"),
                "schema_validation_result": "PASS" if valid else schema_error,
                "semantic_validation_result": "NOT_APPLICABLE",
                "latency_ms": call_usage.get("latency_ms", 0),
                "prompt_tokens": call_usage.get("prompt_tokens", 0),
                "completion_tokens": call_usage.get("completion_tokens", 0),
                "error_class": call_usage.get("parse_error_class"),
            }

        pass_results: dict[str, Any] = {}
        pass_results["pass1_facts"] = run_pass(
            "PASS1_FACT_INTERPRETATION", _pass1_prompt(facts), 1200, _validate_pass1
        )
        pass_results["pass2_risk"] = run_pass(
            "PASS2_RISK_CRITIC", _pass2_prompt(facts), 1200, _validate_pass2
        )
        pass_results["pass3_market"] = run_pass(
            "PASS3_MARKET_NEWS_SYNTHESIS",
            _pass3_prompt(facts, market_state, news),
            1800,
            _validate_pass3,
        )
        pass4_payload, pass4_usage = _raw_call(
            provider_factory,
            model=model,
            user_prompt=_pass4_prompt(
                facts,
                pass_results["pass1_facts"].get("payload", {}),
                pass_results["pass2_risk"].get("payload", {}),
                pass_results["pass3_market"].get("payload", {}),
            ),
            max_tokens=1800,
        )
        usage["total_calls"] += 1
        usage["prompt_tokens"] += pass4_usage.get("prompt_tokens", 0)
        usage["completion_tokens"] += pass4_usage.get("completion_tokens", 0)
        usage["latency_ms"] += pass4_usage.get("latency_ms", 0)
        pass_results["pass4_final"] = {
            "name": "PASS4_FINAL_BRIEF",
            "status": pass4_usage.get("status", "NOT_CALLED"),
            "payload": pass4_payload or {},
            "raw_response": pass4_usage.get("raw_response", ""),
            "parsed_response": pass4_usage.get("parsed_response"),
            "latency_ms": pass4_usage.get("latency_ms", 0),
            "prompt_tokens": pass4_usage.get("prompt_tokens", 0),
            "completion_tokens": pass4_usage.get("completion_tokens", 0),
            "error_class": pass4_usage.get("parse_error_class"),
        }

        brief: dict[str, Any] | None = None
        source = "RULE_BASED_DETERMINISTIC_V2"
        llm_status = "PASS_DEGRADED"
        ai_status = "UNAVAILABLE" if provider_factory is None else "PASS_DEGRADED_WHOLE_FALLBACK"
        if pass4_payload is not None:
            # Compatibility for frozen ROUND25 artifacts and deterministic
            # fixture providers.  Live DeepSeek uses the smaller V3 synthesis
            # contract below, avoiding a 19-section all-or-nothing schema.
            legacy_ok, legacy_error = validate_brief_v2(
                pass4_payload,
                allowed_action_symbols=allowed_action,
                allowed_research_symbols=allowed_research,
            )
            synthesis_ok, synthesis_error = _validate_pass4_synthesis(pass4_payload)
            if legacy_ok:
                brief = pass4_payload
                source = "DEEPSEEK_MULTIPASS_JSON"
                llm_status = "PASS"
                ai_status = "PASS"
                pass_results["pass4_final"]["schema_validation_result"] = "PASS_LEGACY_V2"
            elif synthesis_ok:
                brief = build_deterministic_v2(
                    facts, market_state=market_state, news=news, pre_execution=pre_execution
                )
                brief = apply_deepseek_synthesis(
                    brief,
                    pass4_payload,
                    facts=facts,
                    allowed_action=allowed_action,
                )
                source = "DEEPSEEK_STRUCTURED_V3"
                llm_status = "PASS"
                ai_status = "PASS"
                pass_results["pass4_final"]["schema_validation_result"] = "PASS"
            else:
                pass_results["pass4_final"]["status"] = (
                    f"SCHEMA_INVALID: {synthesis_error}; legacy={legacy_error}"
                )
                pass_results["pass4_final"]["schema_validation_result"] = synthesis_error
        if brief is None:
            brief = build_deterministic_v2(
                facts, market_state=market_state, news=news, pre_execution=pre_execution
            )
        grounding_ok, grounding_issues = validate_semantic_grounding(brief, facts)
        facts_v3 = build_facts_v3(
            facts_v2=facts,
            market_state=market_state,
            news=news,
            pre_execution=pre_execution,
            decision_manifest=decision_manifest,
        )
        fallback_brief = build_deterministic_v2(
            facts, market_state=market_state, news=news, pre_execution=pre_execution
        )
        if source.startswith("DEEPSEEK") and not grounding_ok:
            brief = fallback_brief
            llm_status = "PASS_DEGRADED"
            source = GROUNDING_QUARANTINED
            ai_status = "PASS_DEGRADED_WHOLE_FALLBACK"
        elif source.startswith("DEEPSEEK"):
            # ROUND26 P0: section-level quarantine keeps healthy DeepSeek
            # sections; only conflicting sections fall back.
            brief, section_report = quarantine_sections(
                brief, fallback_brief, facts_v3=facts_v3
            )
            if section_report["status"] == SECTION_LEVEL_QUARANTINED:
                llm_status = "PASS_DEGRADED"
                ai_status = "PASS_DEGRADED_SECTION_FALLBACK"
                self._section_report = section_report
            elif section_report["critical_failure"]:
                brief = fallback_brief
                llm_status = "PASS_DEGRADED"
                source = GROUNDING_QUARANTINED
                ai_status = "PASS_DEGRADED_WHOLE_FALLBACK"
        section_report = getattr(self, "_section_report", {})
        return AiBriefV2Result(
            run_id=run_id,
            model=model,
            prompt_version=PROMPT_VERSION_V2,
            llm_status=llm_status,
            ai_status=ai_status,
            source=source,
            brief=brief,
            passes=pass_results,
            usage=usage,
            semantic_grounding_status=(
                GROUNDING_OK if grounding_ok else GROUNDING_QUARANTINED
            ),
            semantic_grounding_issues=tuple(grounding_issues),
            section_report=section_report,
        )
