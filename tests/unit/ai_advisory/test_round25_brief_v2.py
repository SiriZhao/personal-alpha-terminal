"""ROUND25 PHASE 3/6/17: DailyAIBriefV2 multi-pass + truthfulness tests."""

from __future__ import annotations

import json

from personal_alpha_terminal.agents.llm.schemas import LLMResponse
from personal_alpha_terminal.ai_advisory.brief_v2 import (
    SCHEMA_VERSION_V2,
    AiBriefV2Service,
    build_deterministic_v2,
    validate_brief_v2,
)
from personal_alpha_terminal.ai_advisory.grounding import GROUNDING_QUARANTINED


def _facts() -> dict[str, object]:
    return {
        "run_id": "r1",
        "analysis_date": "2026-08-13",
        "trade_date": "2026-08-14",
        "factor_count": 500,
        "candidate_count": 9,
        "research_certification_state": "NOT_CERTIFIABLE",
        "probability_influence": 0.0,
        "llm_mode": "SHADOW",
        "benchmarks": [
            {"symbol": "SPY", "period_return": 0.2861, "annualized_volatility": 0.178},
        ],
        "portfolio": {"total_value": 100_000.0, "cash_balance": 100_000.0},
        "formal_actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0694,
                "current_weight": 0.0,
                "expected_alpha": 0.045,
                "risk_contribution": 0.30,
                "estimated_cost": 3.95,
            }
        ],
        "actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "target_weight": 0.0694,
                "current_weight": 0.0,
                "expected_alpha": 0.045,
                "risk_contribution": 0.30,
                "estimated_cost": 3.95,
            }
        ],
        "research_candidates": [
            {
                "symbol": "VOO",
                "sleeve": "ETF_CORE",
                "research_target_weight": 0.0707,
                "momentum_252_21": 0.52,
                "momentum_vol_ratio": 1.25,
            }
        ],
        "allowed_action_symbols": ["VSTS"],
        "allowed_research_symbols": ["VOO"],
        "evidence_refs": ["run-certificate:r1"],
        "data_gaps": ["ETF look-through unavailable"],
        "warnings": [],
    }


def test_deterministic_v2_is_schema_valid() -> None:
    brief = build_deterministic_v2(_facts())
    ok, error = validate_brief_v2(
        brief,
        allowed_action_symbols=frozenset({"VSTS"}),
        allowed_research_symbols=frozenset({"VOO"}),
    )
    assert ok, error
    assert brief["schema_version"] == SCHEMA_VERSION_V2


def test_deterministic_v2_research_etf_never_sounds_executable() -> None:
    brief = build_deterministic_v2(_facts())
    etf_text = json.dumps(brief["etf_research_analysis"], ensure_ascii=False)
    assert "研究候选" in etf_text
    assert "交易权限 NONE" in etf_text
    assert "不属于今日执行计划" in etf_text


def test_v2_validation_rejects_hallucinated_formal_symbol() -> None:
    brief = build_deterministic_v2(_facts())
    brief["formal_action_explanations"][0]["symbol"] = "FAKE"
    ok, error = validate_brief_v2(
        brief,
        allowed_action_symbols=frozenset({"VSTS"}),
        allowed_research_symbols=frozenset({"VOO"}),
    )
    assert not ok
    assert "hallucination guard" in error


def test_v2_validation_rejects_etf_symbol_in_formal_explanations() -> None:
    brief = build_deterministic_v2(_facts())
    brief["formal_action_explanations"][0]["symbol"] = "VOO"
    ok, error = validate_brief_v2(
        brief,
        allowed_action_symbols=frozenset({"VSTS"}),
        allowed_research_symbols=frozenset({"VOO"}),
    )
    assert not ok


class _V2GoodProvider:
    def generate(self, request):
        return LLMResponse(
            content=json.dumps(build_deterministic_v2(_facts()), ensure_ascii=False),
            provider="deepseek",
            model="deepseek-v4-flash",
            is_mock=True,
            prompt_tokens=100,
            completion_tokens=200,
            latency_ms=50,
        )


def test_multipass_service_with_provider_produces_valid_v2() -> None:
    result = AiBriefV2Service().generate(
        run_id="r1",
        facts=_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: _V2GoodProvider(),
    )
    assert result.source == "DEEPSEEK_MULTIPASS_JSON"
    assert result.llm_status == "PASS"
    assert result.usage["total_calls"] == 4
    assert result.semantic_grounding_status == "AI_SEMANTIC_GROUNDING_OK"


class _PollutedProvider:
    def generate(self, request):
        brief = build_deterministic_v2(_facts())
        brief["portfolio_risk_analysis"] = "当前组合配置 VOO 7.07%,为正式持仓。"
        return LLMResponse(
            content=json.dumps(brief, ensure_ascii=False),
            provider="deepseek",
            model="deepseek-v4-flash",
            is_mock=True,
        )


def test_polluted_v2_is_quarantined_and_falls_back() -> None:
    result = AiBriefV2Service().generate(
        run_id="r1",
        facts=_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: _PollutedProvider(),
    )
    assert result.source == GROUNDING_QUARANTINED
    assert result.semantic_grounding_status == GROUNDING_QUARANTINED
    assert result.llm_status == "PASS_DEGRADED"
    assert "组合配置 VOO" not in json.dumps(result.brief, ensure_ascii=False)


def test_no_provider_falls_back_to_deterministic_v2() -> None:
    result = AiBriefV2Service().generate(
        run_id="r1",
        facts=_facts(),
        model="deepseek-v4-flash",
        provider_factory=None,
    )
    assert result.source == "RULE_BASED_DETERMINISTIC_V2"
    assert result.brief["formal_action_explanations"]


class _V3StructuredProvider:
    def generate(self, request):
        if "PASS 1" in request.user_prompt:
            payload = {
                "formal_count": 1, "formal_symbols": ["VSTS"], "research_count": 1,
                "research_symbols": ["VOO"], "cash_and_portfolio": "由程序提供",
                "gates": "已验证", "research_certification": "NOT_CERTIFIABLE",
            }
        elif "PASS 2" in request.user_prompt:
            payload = {
                "risk_critic": "风险可见", "concentration_risks": [],
                "execution_risks": [], "unknowns": [],
            }
        elif "PASS 3" in request.user_prompt:
            payload = {
                "market_synthesis": "市场观察", "index_view": "指数观察",
                "breadth_view": "宽度观察", "macro_view": "宏观观察", "news_events": [],
            }
        else:
            payload = {
                "market_interpretation": "市场解释", "risk_interpretation": "风险解释",
                "narrative": "叙事", "watch_list": ["观察波动"], "limitations": ["数据局限"],
            }
            return LLMResponse(
                content="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
                provider="deepseek", model="deepseek-v4-flash", is_mock=True,
            )
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False), provider="deepseek",
            model="deepseek-v4-flash", is_mock=True,
        )


def test_pass4_valid_structured_output_and_fence_normalization() -> None:
    result = AiBriefV2Service().generate(
        run_id="r1", facts=_facts(), model="deepseek-v4-flash",
        provider_factory=lambda: _V3StructuredProvider(),
    )
    assert result.source == "DEEPSEEK_STRUCTURED_V3"
    assert result.ai_status == "PASS"
    assert result.brief["market_state"] == "市场解释"
    assert result.passes["pass4_final"]["schema_validation_result"] == "PASS"


def test_semantic_errors_are_not_repaired() -> None:
    class _InvalidSynthesisProvider(_V3StructuredProvider):
        def generate(self, request):
            if "PASS 4" in request.user_prompt:
                return LLMResponse(
                    content='{"market_interpretation":"only"}',
                    provider="deepseek",
                    model="x",
                )
            return super().generate(request)

    result = AiBriefV2Service().generate(
        run_id="r1", facts=_facts(), model="deepseek-v4-flash",
        provider_factory=lambda: _InvalidSynthesisProvider(),
    )
    assert result.source == "RULE_BASED_DETERMINISTIC_V2"
    assert result.ai_status == "PASS_DEGRADED_WHOLE_FALLBACK"
