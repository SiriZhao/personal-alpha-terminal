"""ROUND24 AI Chinese advisory brief schemas (B2, B4, B6).

The LLM must emit strictly this JSON schema before the terminal renderer turns
it into Chinese UI.  Schema violations quarantine the payload
(``AI_BRIEF_QUARANTINED``) and never pollute the production run.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "ai-brief-zh-v1"
PROMPT_VERSION = "ai-brief-zh-prompt-v1"
PRODUCTION_INFLUENCE = "NONE"
LLM_TRADE_AUTHORITY = "NONE"
LLM_TARGET_WEIGHT_AUTHORITY = "NONE"
LLM_BUY_SELL_AUTHORITY = "NONE"
QUARANTINE_STATUS = "AI_BRIEF_QUARANTINED"

TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "summary",
        "market_interpretation",
        "portfolio_interpretation",
        "action_explanations",
        "event_risks",
        "portfolio_risks",
        "contrarian_view",
        "uncertainties",
        "data_gaps",
    }
)

ACTION_KEYS = frozenset(
    {
        "symbol",
        "quant_alpha",
        "trend",
        "volatility",
        "risk_target",
        "liquidity",
        "portfolio_role",
        "pit_events",
        "ai_interpretation",
        "evidence_refs",
    }
)


def validate_brief(payload: Any, *, allowed_symbols: frozenset[str]) -> tuple[bool, str]:
    """Validate a candidate brief payload against the strict schema.

    Returns ``(ok, error)``.  Extra top-level keys, wrong types, and
    explanations of symbols that were never present in the quant facts are
    all rejected (anti-hallucination guard).
    """

    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"
    extra = set(payload) - TOP_LEVEL_KEYS
    if extra:
        return False, f"unknown top-level keys: {sorted(extra)}"
    if payload.get("schema_version") != SCHEMA_VERSION:
        return False, "schema_version must be " + SCHEMA_VERSION
    for key in (
        "summary",
        "market_interpretation",
        "portfolio_interpretation",
        "contrarian_view",
    ):
        if not isinstance(payload.get(key), str):
            return False, f"{key} must be a string"
    if not isinstance(payload.get("action_explanations"), list):
        return False, "action_explanations must be a list"
    for index, item in enumerate(payload["action_explanations"]):
        if not isinstance(item, dict):
            return False, f"action_explanations[{index}] is not an object"
        extra_action = set(item) - ACTION_KEYS
        if extra_action:
            return False, (
                f"action_explanations[{index}] has unknown keys: {sorted(extra_action)}"
            )
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            return False, f"action_explanations[{index}] symbol must be non-empty"
        if symbol not in allowed_symbols:
            return False, (
                f"action_explanations[{index}] symbol {symbol!r} is not part of "
                "the quant facts (hallucination guard)"
            )
        if not isinstance(item.get("ai_interpretation"), str):
            return False, f"action_explanations[{index}] ai_interpretation must be a string"
        if not isinstance(item.get("evidence_refs", []), list):
            return False, f"action_explanations[{index}] evidence_refs must be a list"
    for key in ("event_risks", "portfolio_risks", "uncertainties", "data_gaps"):
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False, f"{key} must be a list of strings"
    return True, ""
