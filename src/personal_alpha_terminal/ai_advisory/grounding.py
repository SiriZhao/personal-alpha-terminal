"""ROUND25 PHASE 3.2: AI_SEMANTIC_GROUNDING_VALIDATOR.

Deterministic post-generation checks that catch the exact semantic pollution
that appeared after ROUND24:

* a research candidate described as a holding / position,
* a research candidate described as executable (BUY/SELL language),
* a context-only asset described as a portfolio target,
* a formal target omitted from the brief,
* a stated current cash that contradicts the quant facts,
* a stated total formal gross that contradicts the formal weights,
* an action-explanation count that does not match the formal actions.

Any detected issue quarantines the brief
(``AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH``): the terminal must not display
an unmarked semantically-wrong brief.
"""

from __future__ import annotations

import re
from typing import Any

GROUNDING_OK = "AI_SEMANTIC_GROUNDING_OK"
GROUNDING_QUARANTINED = "AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH"

# Chinese verbs that make a research candidate sound like a live holding.
_HOLDING_PATTERNS = ("持有", "持仓", "已买入", "已建仓", "配置了", "组合配置", "仓位")
# Chinese verbs that make a research candidate sound like an executable order.
_EXECUTION_PATTERNS = ("买入", "卖出", "增持", "减持")
_TARGET_PATTERNS = ("目标", "目标权重")

_WINDOW = 12
_CASH_WINDOW = 60
_PCT_TOLERANCE = 0.05


def _brief_text(brief: dict[str, Any]) -> str:
    parts: list[str] = []
    narrative_keys = (
        "summary",
        "market_interpretation",
        "portfolio_interpretation",
        "contrarian_view",
        # DailyAIBriefV2 narrative fields
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
    )
    for key in narrative_keys:
        value = brief.get(key)
        if isinstance(value, str):
            parts.append(value)
    explanation_rows = brief.get("action_explanations") or brief.get(
        "formal_action_explanations"
    ) or []
    for item in explanation_rows:
        if isinstance(item, dict):
            symbol = item.get("symbol")
            if isinstance(symbol, str):
                parts.append(symbol)
            for key in (
                "ai_interpretation",
                "ai_explanation",
                "portfolio_role",
                "pit_events",
            ):
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
    for item in brief.get("etf_research_analysis", []) or []:
        if isinstance(item, dict):
            symbol = item.get("symbol")
            if isinstance(symbol, str):
                parts.append(symbol)
            for key in ("ai_interpretation", "metric_note"):
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def _symbol_near_keyword(text: str, symbol: str, keywords: tuple[str, ...]) -> bool:
    # Ticker symbols must match on word boundaries so a research candidate
    # "LQD" is never matched inside a formal symbol "LQDA".
    pattern = rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])"
    symbol_positions = [match.start() for match in re.finditer(pattern, text)]
    if not symbol_positions:
        return False
    for keyword in keywords:
        positions = [match.start() for match in re.finditer(re.escape(keyword), text)]
        for symbol_index in symbol_positions:
            for position in positions:
                distance = abs(position - symbol_index)
                if distance <= _WINDOW + max(len(symbol), len(keyword)):
                    return True
    return False


def _find_percent_near(text: str, label: str) -> list[float]:
    """Extract percentages appearing within _CASH_WINDOW of ``label``."""

    found: list[float] = []
    for match in re.finditer(re.escape(label), text):
        window = text[match.start() : match.start() + _CASH_WINDOW]
        for number in re.findall(r"(\d+(?:\.\d+)?)\s*%", window):
            found.append(float(number))
    return found


def validate_semantic_grounding(
    brief: dict[str, Any], facts: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Return (ok, issues).  ``ok`` is False when any issue was detected."""

    issues: list[str] = []
    text = _brief_text(brief)
    research_symbols = {
        str(item.get("symbol"))
        for item in (facts.get("research_candidates") or [])
        if isinstance(item, dict) and item.get("symbol")
    }
    context_symbols = {
        str(item.get("symbol"))
        for item in (facts.get("context_only") or [])
        if isinstance(item, dict) and item.get("symbol")
    }
    formal_actions = facts.get("formal_actions") or facts.get("actions") or []
    formal_symbols = {
        str(item.get("symbol"))
        for item in formal_actions
        if isinstance(item, dict) and item.get("symbol")
    }

    for symbol in research_symbols:
        if _symbol_near_keyword(text, symbol, _HOLDING_PATTERNS):
            issues.append(f"research candidate {symbol} described as a holding")
        if _symbol_near_keyword(text, symbol, _EXECUTION_PATTERNS):
            issues.append(f"research candidate {symbol} described as executable")
    for symbol in context_symbols:
        if _symbol_near_keyword(text, symbol, _TARGET_PATTERNS):
            issues.append(f"context asset {symbol} described as a portfolio target")
    for symbol in formal_symbols:
        if symbol and symbol not in text:
            issues.append(f"formal target {symbol} omitted from brief")

    explanations = (
        brief.get("action_explanations")
        or brief.get("formal_action_explanations")
        or []
    )
    if len(explanations) != len(formal_actions):
        issues.append(
            "action explanation count "
            f"({len(explanations)}) != formal action count ({len(formal_actions)})"
        )

    portfolio = facts.get("portfolio") or {}
    if isinstance(portfolio, dict):
        total_value = portfolio.get("total_value")
        cash_balance = portfolio.get("cash_balance")
        cash_weight = portfolio.get("cash_weight")
        if cash_weight is None and isinstance(total_value, (int, float)) and total_value:
            if isinstance(cash_balance, (int, float)):
                cash_weight = float(cash_balance) / float(total_value)
        if isinstance(cash_weight, (int, float)) and not isinstance(cash_weight, bool):
            stated = _find_percent_near(text, "现金")
            for value in stated:
                if abs(value / 100.0 - cash_weight) > _PCT_TOLERANCE:
                    issues.append(
                        f"stated cash {value}% contradicts facts cash_weight "
                        f"{cash_weight * 100:.2f}%"
                    )

        formal_gross = sum(
            float(item.get("target_weight") or 0.0)
            for item in formal_actions
            if isinstance(item, dict)
        )
        if formal_gross > 0:
            for label in ("总敞口", "总权重", "合计权重"):
                for value in _find_percent_near(text, label):
                    if abs(value / 100.0 - formal_gross) > _PCT_TOLERANCE:
                        issues.append(
                            f"stated {label} {value}% contradicts formal gross "
                            f"{formal_gross * 100:.2f}%"
                        )

    return (not issues, issues)
