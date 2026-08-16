"""ROUND28 P0: semantic validator regression for real production phrasing."""

from __future__ import annotations

from personal_alpha_terminal.ai_advisory.facts_v3 import build_facts_v3
from personal_alpha_terminal.ai_advisory.grounding import (
    GROUNDING_OK,
    validate_semantic_grounding,
)
from personal_alpha_terminal.ai_advisory.grounding_v3 import (
    GROUNDING_QUARANTINED,
    quarantine_sections,
)


def _facts_v2() -> dict[str, object]:
    return {
        "run_id": "daily-r1",
        "decision_id": "decision-r1",
        "probability_influence": 0,
        "probability_mode": "PROBABILITY_FALLBACK_CLASSICAL",
        "portfolio": {"total_value": 100_000.0, "cash_balance": 72_772.0},
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0691,
                "expected_alpha": 0.0455,
                "risk_contribution": 0.3295,
                "estimated_cost": 3.93,
            },
            {
                "symbol": "RVMD",
                "action": "BUY",
                "target_weight": 0.0419,
                "expected_alpha": 0.0450,
                "risk_contribution": 0.1857,
                "estimated_cost": 2.32,
            },
            {
                "symbol": "ATEX",
                "action": "BUY",
                "target_weight": 0.0278,
                "expected_alpha": 0.0410,
                "risk_contribution": 0.0834,
                "estimated_cost": 1.55,
            },
            {
                "symbol": "TVTX",
                "action": "BUY",
                "target_weight": 0.0295,
                "expected_alpha": 0.0430,
                "risk_contribution": 0.1106,
                "estimated_cost": 1.64,
            },
            {
                "symbol": "RLAY",
                "action": "BUY",
                "target_weight": 0.0242,
                "expected_alpha": 0.0435,
                "risk_contribution": 0.0936,
                "estimated_cost": 1.35,
            },
        ],
        "research_candidates": [],
        "benchmarks": [],
        "factor_count": 5,
        "candidate_count": 5,
        "factor_statistics": {},
        "risk": {},
        "pit_events": [],
        "data_gaps": [],
        "evidence_refs": ["run:daily-r1"],
    }


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
        "formal_action_explanations": [],
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


def test_top5_weight_and_risk_contribution_not_quarantined() -> None:
    facts_v2 = _facts_v2()
    facts_v3 = build_facts_v3(facts_v2=facts_v2)
    text = (
        "前五大持仓合计权重约19.25%，风险贡献合计约80.28%，"
        "组合总权重约19.25%，现金占比72.77%。"
        "VSTS风险贡献32.95%，RVMD风险贡献18.57%。"
    )
    brief = _brief(text)
    brief["formal_action_explanations"] = [
        {"symbol": item["symbol"], "ai_explanation": "目标权重由量化组合链确定。"}
        for item in facts_v2["formal_actions"]
    ]
    merged, report = quarantine_sections(brief, _brief("fallback"), facts_v3=facts_v3)
    assert report["status"] == GROUNDING_OK
    assert merged == brief
    ok, issues = validate_semantic_grounding(brief, facts_v2)
    assert ok, issues


def test_production_wrong_top5_numbers_are_quarantined() -> None:
    facts_v2 = _facts_v2()
    facts_v3 = build_facts_v3(facts_v2=facts_v2)
    # This is the real production daily-run phrasing that caused
    # AI_BRIEF_QUARANTINED_SEMANTIC_MISMATCH. It must stay quarantined because
    # the claimed top-5/gross/risk numbers contradict the formal facts.
    text = (
        "前五大持仓合计权重约19.17%，风险贡献合计约80.25%，"
        "组合总权重约27.23%，现金占比72.77%。"
        "VSTS风险贡献32.95%，RVMD风险贡献18.57%。"
    )
    brief = _brief(text)
    merged, report = quarantine_sections(brief, _brief("fallback"), facts_v3=facts_v3)
    assert report["status"] == GROUNDING_QUARANTINED
    assert report["critical_failure"] is True
    assert merged["formal_conclusions"] == "fallback"


def test_wrong_cost_share_still_quarantined() -> None:
    facts_v2 = _facts_v2()
    facts_v3 = build_facts_v3(facts_v2=facts_v2)
    # True cost share is ~0.0558%; the LLM claimed 5.58%.
    text = "估计成本合计约15.19，占总权重约5.58%。"
    brief = _brief(text)
    merged, report = quarantine_sections(brief, _brief("fallback"), facts_v3=facts_v3)
    assert report["status"] == GROUNDING_QUARANTINED
    assert report["critical_failure"] is True
    assert merged["formal_conclusions"] == "fallback"


def test_wrong_symbol_risk_contribution_quarantined() -> None:
    facts_v2 = _facts_v2()
    facts_v3 = build_facts_v3(facts_v2=facts_v2)
    text = "VSTS风险贡献50.00%。"
    brief = _brief(text)
    merged, report = quarantine_sections(brief, _brief("fallback"), facts_v3=facts_v3)
    assert report["status"] == GROUNDING_QUARANTINED
    assert report["critical_failure"] is True
