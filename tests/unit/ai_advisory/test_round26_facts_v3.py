"""ROUND26 P0: AIBriefFactsV3 + section-level quarantine tests."""

from __future__ import annotations

from personal_alpha_terminal.ai_advisory.facts_v3 import FACTS_V3_SCHEMA, build_facts_v3
from personal_alpha_terminal.ai_advisory.grounding_v3 import (
    SECTION_LEVEL_QUARANTINED,
    quarantine_sections,
)


def _facts_v2() -> dict[str, object]:
    return {
        "run_id": "daily-r1",
        "decision_id": "decision-r1",
        "probability_influence": 0,
        "probability_mode": "PROBABILITY_FALLBACK_CLASSICAL",
        "portfolio": {"total_value": 100_000.0, "cash_balance": 100_000.0},
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0694,
                "expected_alpha": 0.045,
                "risk_contribution": 0.30,
                "estimated_cost": 3.95,
            },
            {
                "symbol": "ATEX",
                "action": "BUY",
                "target_weight": 0.0283,
                "expected_alpha": 0.041,
                "risk_contribution": 0.08,
                "estimated_cost": 1.58,
            },
        ],
        "research_candidates": [
            {"symbol": "VOO", "research_target_weight": 0.0707}
        ],
        "benchmarks": [{"symbol": "SPY", "period_return": 0.28}],
        "factor_count": 500,
        "candidate_count": 9,
        "factor_statistics": {},
        "risk": {},
        "pit_events": [],
        "data_gaps": [],
        "evidence_refs": ["run:daily-r1", "decision:decision-r1"],
    }


def test_facts_v3_computes_key_numbers_programmatically() -> None:
    v3 = build_facts_v3(facts_v2=_facts_v2())
    assert v3["schema_version"] == FACTS_V3_SCHEMA
    assert v3["RUN_IDENTITY"]["run_id"] == "daily-r1"
    portfolio = v3["PORTFOLIO_FACTS"]
    assert portfolio["cash_weight"]["value"] == 1.0
    assert portfolio["gross_weight"]["value"] == 0.0694 + 0.0283
    assert portfolio["formal_action_count"]["value"] == 2
    assert portfolio["buy_count"]["value"] == 2
    assert portfolio["formal_symbols"]["value"] == ["ATEX", "VSTS"]
    assert portfolio["total_estimated_cost"]["value"] == 3.95 + 1.58


def test_authority_block_is_machine_generated() -> None:
    v3 = build_facts_v3(facts_v2=_facts_v2())
    authority = v3["AUTHORITY_BLOCK"]
    assert authority["llm_production_influence"] == "NONE"
    assert authority["automatic_execution"] == "DISABLED"
    assert authority["manual_confirmation_required"] is True
    assert authority["machine_generated"] is True
    assert authority["probability_production_influence"] == 0


def _brief(text: str) -> dict[str, object]:
    return {
        "schema_version": "ai-brief-zh-v2",
        "executive_summary": text,
        "formal_conclusions": text,
        "market_state": text,
        "index_analysis": text,
        "breadth_analysis": text,
        "factor_rotation": text,
        "macro_context": text,
        "important_news": [],
        "sec_events": [],
        "formal_action_explanations": [
            {"symbol": "VSTS", "action": "BUY", "ai_explanation": "ok"}
        ],
        "etf_research_analysis": [],
        "portfolio_risk_analysis": text,
        "overnight_risk": text,
        "bear_case": text,
        "bull_case": text,
        "uncertainties": [],
        "watchlist_next_sessions": [],
        "data_limitations": [],
        "manual_execution_notes": [],
    }


def test_section_level_quarantine_keeps_healthy_sections() -> None:
    facts_v3 = build_facts_v3(facts_v2=_facts_v2())
    # Wrong cash in non-critical sections only.
    text = "组合现金占比 20.00%,目标敞口 9.77%。"
    brief = _brief(text)
    brief["executive_summary"] = "现金 100.00%,总敞口 9.77%。"
    brief["formal_conclusions"] = "现金 100.00%,总敞口 9.77%。"
    brief["portfolio_risk_analysis"] = "现金 100.00%,总敞口 9.77%。"
    fallback = _brief("deterministic section")
    merged, report = quarantine_sections(brief, fallback, facts_v3=facts_v3)
    # critical sections stay (they are correct); non-critical wrong sections replaced
    assert report["status"] == SECTION_LEVEL_QUARANTINED
    assert set(report["quarantined_sections"]) == {
        "market_state",
        "index_analysis",
        "breadth_analysis",
        "factor_rotation",
        "macro_context",
        "overnight_risk",
        "bear_case",
        "bull_case",
    }
    assert merged["market_state"] == "deterministic section"
    assert merged["executive_summary"] != "deterministic section"


def test_critical_section_conflict_quarantines_whole_brief() -> None:
    facts_v3 = build_facts_v3(facts_v2=_facts_v2())
    text = "现金 100.00%,总敞口 9.77%。"
    brief = _brief(text)
    # Critical section gets a wrong gross (9.77% vs facts ~9.77%? use 50%).
    brief["formal_conclusions"] = "现金 100.00%,总敞口 50.00%。"
    fallback = _brief("deterministic section")
    merged, report = quarantine_sections(brief, fallback, facts_v3=facts_v3)
    assert report["critical_failure"] is True
    assert merged["formal_conclusions"] == "deterministic section"
