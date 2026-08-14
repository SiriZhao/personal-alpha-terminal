"""ROUND25 PHASE 3.2 / 17: AI_SEMANTIC_GROUNDING_VALIDATOR adversarial tests."""

from __future__ import annotations

from personal_alpha_terminal.ai_advisory.grounding import (
    validate_semantic_grounding,
)


def _facts(
    *,
    research: tuple[dict[str, object], ...] = (),
    context: tuple[dict[str, object], ...] = (),
    cash_balance: float | None = None,
    total_value: float | None = None,
) -> dict[str, object]:
    return {
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0694,
                "current_weight": 0.0,
            }
        ],
        "research_candidates": list(research),
        "context_only": list(context),
        "portfolio": (
            {"total_value": total_value, "cash_balance": cash_balance}
            if total_value is not None
            else {}
        ),
    }


def _brief(text: str, explanations: int = 1) -> dict[str, object]:
    return {
        "summary": text,
        "market_interpretation": "",
        "portfolio_interpretation": "",
        "contrarian_view": "",
        "action_explanations": [
            {"symbol": "VSTS", "ai_interpretation": "正式买入解释。", "evidence_refs": []}
        ][:explanations],
    }


def test_clean_brief_passes() -> None:
    brief = _brief(
        "今日量化结论:VSTS 为正式买入建议,经 SIGNAL 到 EXECUTION 全链校验。"
        "ETF 研究候选 VOO 尚未进入正式交易链,不属于今日执行计划。"
    )
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(research=({"symbol": "VOO", "target_weight": 0.0707},)),
    )
    assert ok, issues


def test_research_candidate_described_as_holding_is_quarantined() -> None:
    brief = _brief("当前组合配置 VOO 7.07%,VSTS 为正式买入建议。")
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(research=({"symbol": "VOO", "target_weight": 0.0707},)),
    )
    assert not ok
    assert any("described as a holding" in issue for issue in issues)


def test_research_candidate_described_as_executable_is_quarantined() -> None:
    brief = _brief("建议买入 VOO 以完成 ETF 核心配置;VSTS 为正式买入建议。")
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(research=({"symbol": "VOO", "target_weight": 0.0707},)),
    )
    assert not ok
    assert any("described as executable" in issue for issue in issues)


def test_context_asset_described_as_target_is_quarantined() -> None:
    brief = _brief("组合目标 SPY 权重 30%;VSTS 为正式买入建议。")
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(context=({"symbol": "SPY", "period_return": 0.28},)),
    )
    assert not ok
    assert any("described as a portfolio target" in issue for issue in issues)


def test_formal_target_omitted_is_flagged() -> None:
    facts = _facts()
    facts["formal_actions"] = [
        {
            "symbol": "VSTS",
            "action": "BUY",
            "target_weight": 0.0694,
            "current_weight": 0.0,
        },
        {
            "symbol": "ATEX",
            "action": "BUY",
            "target_weight": 0.0283,
            "current_weight": 0.0,
        },
    ]
    brief = _brief("VSTS 为正式买入建议。", explanations=1)
    ok, issues = validate_semantic_grounding(brief, facts)
    assert not ok
    assert any("formal target ATEX omitted" in issue for issue in issues)


def test_wrong_action_count_is_flagged() -> None:
    brief = _brief("VSTS 为正式买入建议。", explanations=0)
    ok, issues = validate_semantic_grounding(brief, _facts())
    assert not ok
    assert any("action explanation count" in issue for issue in issues)


def test_wrong_current_cash_is_flagged() -> None:
    # Facts: 100% cash.  Brief claims 37.32% cash (the ROUND24 pollution).
    brief = _brief("组合总价值 100,000 美元,现金占比 37.32%,VSTS 为正式买入建议。")
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(cash_balance=100_000.0, total_value=100_000.0),
    )
    assert not ok
    assert any("cash" in issue for issue in issues)


def test_correct_cash_passes() -> None:
    brief = _brief("组合总价值 100,000 美元,现金占比 100.00%,VSTS 为正式买入建议。")
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(cash_balance=100_000.0, total_value=100_000.0),
    )
    assert ok, issues


def test_research_target_50pct_adversarial_case() -> None:
    """PHASE 17: research ETF target = 50%, formal ETF target = 0%."""

    brief = _brief(
        "VOO 研究候选目标权重 50%,尚未进入正式交易链,今日不可执行。"
        "正式组合中 ETF 权重为 0%。VSTS 为正式买入建议。"
    )
    ok, issues = validate_semantic_grounding(
        brief,
        _facts(research=({"symbol": "VOO", "target_weight": 0.50},)),
    )
    assert ok, issues
