"""ROUND26 P0: AIBriefFactsV3 -- the only fact source for the AI brief.

Every quantitative fact is computed by the program, carries a stable
``fact_id``, and is placed in a typed section.  The LLM receives this
structure and may only interpret it; it can never recompute key numbers and
its quantitative claims must bind to these fact ids.

The AUTHORITY_BLOCK is machine-generated and the LLM has no authority to
change it.
"""

from __future__ import annotations

from typing import Any

FACTS_V3_SCHEMA = "ai-brief-facts-v3"


def _fact(section: str, name: str, value: Any, *, unit: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"fact_id": f"{section}.{name}", "value": value}
    if unit is not None:
        payload["unit"] = unit
    return payload


def build_facts_v3(
    *,
    facts_v2: dict[str, Any],
    market_state: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    pre_execution: dict[str, Any] | None = None,
    decision_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the typed, fact-id-anchored V3 facts contract."""

    formal = facts_v2.get("formal_actions") or facts_v2.get("actions") or []
    research = facts_v2.get("research_candidates") or []
    portfolio = facts_v2.get("portfolio") or {}
    total_value = portfolio.get("total_value")
    cash_balance = portfolio.get("cash_balance")
    cash_weight = portfolio.get("cash_weight")
    if cash_weight is None and isinstance(total_value, (int, float)) and total_value:
        if isinstance(cash_balance, (int, float)):
            cash_weight = float(cash_balance) / float(total_value)
    gross = sum(
        float(item.get("target_weight") or 0.0)
        for item in formal
        if isinstance(item, dict)
    )
    buy_count = sum(1 for item in formal if item.get("action") in {"BUY", "ADD", "INCREASE"})
    sell_count = sum(1 for item in formal if item.get("action") in {"SELL", "REDUCE"})
    formal_symbols = sorted(str(item.get("symbol")) for item in formal if item.get("symbol"))
    total_estimated_cost = sum(
        float(item.get("estimated_cost") or 0.0)
        for item in formal
        if isinstance(item, dict)
    )
    total_estimated_value = sum(
        float(item.get("estimated_value") or 0.0)
        for item in formal
        if isinstance(item, dict)
    )
    ranked_by_weight = sorted(
        (item for item in formal if isinstance(item, dict)),
        key=lambda item: float(item.get("target_weight") or 0.0),
        reverse=True,
    )
    top5_weight = sum(
        float(item.get("target_weight") or 0.0) for item in ranked_by_weight[:5]
    )
    ranked_by_risk = sorted(
        (item for item in formal if isinstance(item, dict)),
        key=lambda item: float(item.get("risk_contribution") or 0.0),
        reverse=True,
    )
    top5_risk_contribution = sum(
        float(item.get("risk_contribution") or 0.0)
        for item in ranked_by_risk[:5]
    )
    cost_pct_of_gross: float | None = None
    if (
        isinstance(total_value, (int, float))
        and total_value
        and isinstance(gross, (int, float))
        and gross > 0
    ):
        cost_pct_of_gross = total_estimated_cost / (float(total_value) * gross)

    run_identity = {
        "run_id": facts_v2.get("run_id"),
        "decision_id": facts_v2.get("decision_id"),
        "fact_id": "run_identity.run_id",
    }
    manifest_refs: list[str] = []
    if isinstance(decision_manifest, dict) and decision_manifest.get("semantic_hash"):
        manifest_refs.append(
            f"decision-manifest:{str(decision_manifest.get('semantic_hash'))[:16]}"
        )
    portfolio_facts = {
        "nav": _fact("portfolio", "nav", total_value, unit="USD"),
        "cash_balance": _fact("portfolio", "cash_balance", cash_balance, unit="USD"),
        "cash_weight": _fact("portfolio", "cash_weight", cash_weight, unit="PERCENT"),
        "gross_weight": _fact("portfolio", "gross_weight", gross, unit="PERCENT"),
        "formal_action_count": _fact("portfolio", "formal_action_count", len(formal)),
        "buy_count": _fact("portfolio", "buy_count", buy_count),
        "sell_count": _fact("portfolio", "sell_count", sell_count),
        "formal_symbols": _fact("portfolio", "formal_symbols", formal_symbols),
        "total_estimated_cost": _fact(
            "portfolio", "total_estimated_cost", total_estimated_cost, unit="USD"
        ),
        "total_estimated_value": _fact(
            "portfolio", "total_estimated_value", total_estimated_value, unit="USD"
        ),
        "turnover": _fact("portfolio", "turnover", portfolio.get("turnover")),
        "top5_weight": _fact("portfolio", "top5_weight", top5_weight, unit="PERCENT"),
        "top5_risk_contribution": _fact(
            "portfolio", "top5_risk_contribution", top5_risk_contribution, unit="PERCENT"
        ),
        "cost_pct_of_gross": _fact(
            "portfolio", "cost_pct_of_gross", cost_pct_of_gross, unit="PERCENT"
        ),
    }
    formal_actions: list[dict[str, Any]] = []
    for item in formal:
        formal_actions.append(
            {
                "symbol": str(item.get("symbol")),
                "action": str(item.get("action")),
                "target_weight": _fact(
                    "formal_action", f"{item.get('symbol')}.target_weight",
                    item.get("target_weight"), unit="PERCENT",
                ),
                "expected_alpha": _fact(
                    "formal_action", f"{item.get('symbol')}.expected_alpha",
                    item.get("expected_alpha"), unit="DECIMAL_RETURN",
                ),
                "risk_contribution": _fact(
                    "formal_action", f"{item.get('symbol')}.risk_contribution",
                    item.get("risk_contribution"), unit="PERCENT",
                ),
                "estimated_cost": _fact(
                    "formal_action", f"{item.get('symbol')}.estimated_cost",
                    item.get("estimated_cost"), unit="USD",
                ),
                "estimated_value": _fact(
                    "formal_action", f"{item.get('symbol')}.estimated_value",
                    item.get("estimated_value"), unit="USD",
                ),
                "estimated_quantity": _fact(
                    "formal_action", f"{item.get('symbol')}.estimated_quantity",
                    item.get("estimated_quantity"),
                ),
            }
        )

    authority_block = {
        "llm_production_influence": "NONE",
        "llm_trade_authority": "NONE",
        "llm_target_weight_authority": "NONE",
        "probability_production_influence": facts_v2.get("probability_influence", 0),
        "automatic_execution": "DISABLED",
        "manual_confirmation_required": True,
        "machine_generated": True,
    }

    return {
        "schema_version": FACTS_V3_SCHEMA,
        "RUN_IDENTITY": run_identity,
        "DECISION_MANIFEST": {
            "references": manifest_refs,
            "fact_id": "decision_manifest.semantic_hash",
        },
        "PORTFOLIO_FACTS": portfolio_facts,
        "FORMAL_ACTIONS": formal_actions,
        "MARKET_STATE": market_state or {},
        "BENCHMARK_FACTS": facts_v2.get("benchmarks") or [],
        "BREADTH_FACTS": (market_state or {}).get("breadth") or {},
        "FACTOR_FACTS": {
            "factor_count": facts_v2.get("factor_count"),
            "candidate_count": facts_v2.get("candidate_count"),
            "factor_statistics": facts_v2.get("factor_statistics"),
        },
        "RISK_FACTS": facts_v2.get("risk") or {},
        "SIZE_EXPOSURE_FACTS": facts_v2.get("size_exposure") or {},
        "SECTOR_EXPOSURE_FACTS": facts_v2.get("sector_exposure") or {},
        "PROBABILITY_FACTS": {
            "probability_mode": facts_v2.get("probability_mode"),
            "probability_influence": facts_v2.get("probability_influence"),
            "production_influence": authority_block["probability_production_influence"],
        },
        "ETF_RESEARCH_FACTS": research,
        "SEC_EVENT_FACTS": facts_v2.get("pit_events") or [],
        "MACRO_NEWS_FACTS": (news or {}).get("macro_news") or [],
        "MARKET_NEWS_FACTS": (news or {}).get("clusters") or [],
        "PRE_EXECUTION_FACTS": pre_execution or {},
        "LIMITATIONS": list(facts_v2.get("data_gaps") or []),
        "EVIDENCE_REFERENCES": list(facts_v2.get("evidence_refs") or []),
        "AUTHORITY_BLOCK": authority_block,
        "FORMAL_FACT_PACKET": {
            "packet_type": "FORMAL_FACT_PACKET",
            "immutable": True,
            "llm_mutable": False,
            "source": "DETERMINISTIC_QUANT_RUNTIME",
        },
        "COMPANY_DOSSIERS": facts_v2.get("company_dossiers") or {},
        "AI_ACTION_COMMENTARIES": facts_v2.get("action_commentaries") or [],
        "AI_PORTFOLIO_REVIEW": facts_v2.get("portfolio_review") or {},
        "AI_DEVILS_ADVOCATE": facts_v2.get("devils_advocate") or [],
    }
