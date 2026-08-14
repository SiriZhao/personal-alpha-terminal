"""ROUND24 AI Chinese advisory brief tests (B2-B9, N)."""
from __future__ import annotations

from datetime import UTC, datetime

from personal_alpha_terminal.agents.llm.schemas import LLMResponse
from personal_alpha_terminal.ai_advisory import (
    PRODUCTION_INFLUENCE,
    SCHEMA_VERSION,
    AiBriefService,
    BriefCacheKey,
    build_quant_facts,
    validate_brief,
)
from personal_alpha_terminal.ai_advisory.deterministic import (
    build_deterministic_brief,
)
from personal_alpha_terminal.ai_advisory.renderer import (
    render_brief_compact,
    render_brief_full,
)

AS_OF = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": "今日量化结论。",
        "market_interpretation": "市场环境解释。",
        "portfolio_interpretation": "组合结构解读。",
        "action_explanations": [
            {
                "symbol": "VSTS",
                "quant_alpha": "4.5%",
                "trend": "上升",
                "volatility": "中等",
                "risk_target": "0.3",
                "liquidity": "VALID",
                "portfolio_role": "EQUITY_ALPHA",
                "pit_events": "当前没有可用于该证券的 PIT 企业事件证据。",
                "ai_interpretation": "量化解释。",
                "evidence_refs": ["run-certificate:r1"],
            }
        ],
        "event_risks": [],
        "portfolio_risks": ["风险一"],
        "contrarian_view": "反向视角。",
        "uncertainties": ["不确定一"],
        "data_gaps": ["缺口一"],
    }


def _base_facts() -> dict[str, object]:
    return {
        "allowed_action_symbols": ["VSTS", "VOO"],
        "analysis_date": "2026-08-13",
        "trade_date": "2026-08-14",
        "factor_count": 500,
        "candidate_count": 100,
        "benchmarks": [{"symbol": "SPY", "period_return": 0.01, "annualized_volatility": 0.15}],
        "portfolio": {"cash": 0.1},
        "pit_events": [],
        "actions": [
            {
                "symbol": "VSTS",
                "action": "BUY",
                "instrument_type": "COMMON_STOCK",
                "expected_alpha": 0.045,
                "target_weight": 0.07,
                "current_weight": 0.0,
                "risk_contribution": 0.3,
                "sleeve": "EQUITY_ALPHA",
                "data_quality": "VALID",
            }
        ],
        "warnings": [],
        "data_gaps": [],
        "llm_mode": "SHADOW",
        "probability_influence": 0.0,
        "research_certification_state": "NOT_CERTIFIABLE",
        "etf": {"universe": {}, "targets": [], "composition": {}},
        "_run_id": "r1",
    }


def test_schema_validation_accepts_valid_payload() -> None:
    ok, error = validate_brief(_valid_payload(), allowed_symbols=frozenset({"VSTS"}))
    assert ok, error


def test_schema_rejects_unknown_top_level_keys() -> None:
    payload = _valid_payload()
    payload["invented_field"] = "x"
    ok, error = validate_brief(payload, allowed_symbols=frozenset({"VSTS"}))
    assert not ok
    assert "unknown top-level keys" in error


def test_schema_rejects_hallucinated_symbol() -> None:
    payload = _valid_payload()
    payload["action_explanations"][0]["symbol"] = "FAKE"
    ok, error = validate_brief(payload, allowed_symbols=frozenset({"VSTS"}))
    assert not ok
    assert "hallucination guard" in error


def test_llm_malformed_json_degrades_to_deterministic() -> None:
    class MalformedProvider:
        def generate(self, request):
            return LLMResponse(
                content="not json at all",
                provider="deepseek",
                model="deepseek-v4-flash",
                is_mock=True,
            )

    service = AiBriefService()
    key = BriefCacheKey("r1", "d", "f", "p", "k", "i", "deepseek-v4-flash", "v1")
    result = service.generate(
        cache_key=key,
        facts=_base_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: MalformedProvider(),
    )
    assert result.llm_status == "PASS_DEGRADED"
    assert result.source == "RULE_BASED_DETERMINISTIC"
    assert result.llm_call_outcome is not None
    assert result.llm_call_outcome.status == "SCHEMA_INVALID"
    assert result.brief["summary"]
    assert result.production_influence == PRODUCTION_INFLUENCE


def test_llm_timeout_degrades_classical_pipeline_untouched() -> None:
    class TimeoutProvider:
        def generate(self, request):
            raise TimeoutError("timeout")

    service = AiBriefService()
    key = BriefCacheKey("r2", "d", "f", "p", "k", "i", "deepseek-v4-flash", "v1")
    result = service.generate(
        cache_key=key,
        facts=_base_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: TimeoutProvider(),
    )
    assert result.llm_status == "PASS_DEGRADED"
    assert result.llm_call_outcome.status == "TIMEOUT"
    ok, error = validate_brief(
        result.brief, allowed_symbols=frozenset({"VSTS", "VOO"})
    )
    assert ok, error


def test_llm_success_is_cached_and_reused(tmp_path) -> None:
    calls: list[int] = []

    class GoodProvider:
        def generate(self, request):
            calls.append(1)
            import json

            return LLMResponse(
                content=json.dumps(_valid_payload(), ensure_ascii=False),
                provider="deepseek",
                model="deepseek-v4-flash",
                is_mock=True,
                prompt_tokens=100,
                completion_tokens=200,
                latency_ms=50,
            )

    from personal_alpha_terminal.ai_advisory import BriefCache

    service = AiBriefService(BriefCache(tmp_path / "brief-cache"))
    key = BriefCacheKey("r3", "d", "f", "p", "k", "i", "deepseek-v4-flash", "v1")
    first = service.generate(
        cache_key=key,
        facts=_base_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: GoodProvider(),
    )
    second = service.generate(
        cache_key=key,
        facts=_base_facts(),
        model="deepseek-v4-flash",
        provider_factory=lambda: GoodProvider(),
    )
    assert first.llm_status == "PASS"
    assert first.source == "DEEPSEEK_JSON"
    assert second.cache_hit is True
    assert second.brief["summary"] == first.brief["summary"]
    assert len(calls) == 1


def test_brief_has_no_weight_authority() -> None:
    result = AiBriefService().generate(
        cache_key=BriefCacheKey("r4", "d", "f", "p", "k", "i", "m", "v"),
        facts=_base_facts(),
        model="m",
        provider_factory=None,
    )
    assert result.production_influence == "NONE"
    rendered = render_brief_compact(result.document())
    assert "交易权限:NONE" in rendered
    assert "目标权重权限:NONE" in rendered
    assert "买卖权限:NONE" in rendered


def test_chinese_renderer_separates_facts_from_interpretation() -> None:
    payload = _valid_payload()
    document = {
        "model": "deepseek-v4-flash",
        "llm_status": "PASS",
        "source": "DEEPSEEK_JSON",
        "production_influence": "NONE",
        "brief": payload,
    }
    full = render_brief_full(document, _base_facts())
    assert "【量化事实】" in full
    assert "【AI 解读】" in full
    assert "ETF:不适用公司级 SEC 事件分析。" in full or "PIT 事件" in full
    compact = render_brief_compact(document)
    assert "【AI 中文研判 · DeepSeek】" in compact


def test_deterministic_brief_marks_missing_sec_evidence() -> None:
    brief = build_deterministic_brief(_base_facts())
    explanation = brief["action_explanations"][0]
    assert "当前没有可用于该证券的 PIT 企业事件证据。" in explanation["pit_events"]
    assert "ETF:不适用公司级 SEC 事件分析。" in (
        build_deterministic_brief(
            {
                **_base_facts(),
                "actions": [
                    {
                        "symbol": "VOO",
                        "action": "BUY",
                        "instrument_type": "ETF",
                        "expected_alpha": 0.02,
                        "target_weight": 0.05,
                        "current_weight": 0.0,
                        "risk_contribution": 0.1,
                        "sleeve": "ETF_CORE",
                        "data_quality": "VALID",
                    }
                ],
            }
        )["action_explanations"][0]["pit_events"]
    )


def test_quant_facts_drop_future_timestamps() -> None:
    certificate = {
        "run_id": "r9",
        "analysis_date": "2026-08-13",
        "trade_date": "2026-08-14",
        "market_session": "REGULAR",
        "data": [{"dataset": "CERTIFIED_US_UNIVERSE", "member_count": 2133}],
        "decision_recommendations": [
            {"symbol": "VSTS", "action": "BUY", "target_weight": 0.07}
        ],
        "benchmarks": [],
        "portfolio": {},
        "risk": {},
        "warnings": ["2026-08-15T10:00:00+00:00"],
        "llm_mode": "SHADOW",
        "probability_influence": 0.0,
        "operational_authorization": "ALLOW_PROVISIONAL",
        "research_certification_state": "NOT_CERTIFIABLE",
    }
    facts, _gaps = build_quant_facts(
        run_certificate=certificate,
        pit_events=(),
        etf_evidence=None,
        decision_as_of=AS_OF,
    )
    assert facts["warnings"] == ["FUTURE_DATA_DROPPED"]
