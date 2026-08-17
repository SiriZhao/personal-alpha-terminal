from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.application.agentic_shadow_service import (
    AgenticShadowEvidence,
    ShadowCompanyEvidence,
)
from personal_alpha_terminal.application.daily_result import (
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.application.hybrid_intelligence_service import (
    build_shadow_hybrid_document,
)
from personal_alpha_terminal.intelligence.agentic_models import (
    EventRecord,
    EventType,
    SecurityIdentity,
)


def test_shadow_hybrid_document_retains_all_eligible_securities() -> None:
    factors = (
        SimpleNamespace(
            symbol="AAA",
            rank=1,
            expected_alpha=0.03,
            components={"momentum": 0.2},
            evidence_coverage=0.9,
        ),
        SimpleNamespace(
            symbol="BBB",
            rank=2,
            expected_alpha=0.02,
            components={"quality": 0.1},
            evidence_coverage=0.8,
        ),
    )
    workflow = SimpleNamespace(
        factors=factors,
        target=SimpleNamespace(target_weights={"AAA": 0.05, "BBB": 0.04}),
        current_weights={"AAA": 0.02},
        recommendations=(
            SimpleNamespace(symbol="AAA", action="BUY"),
            SimpleNamespace(symbol="BBB", action="BUY"),
        ),
        probability_counterfactual={},
        decision_time=datetime(2026, 8, 17, 12, tzinfo=UTC),
        risk_regime="QUANT_NEUTRAL",
        data_freshness="CURRENT",
    )
    document = build_shadow_hybrid_document(
        workflow=workflow,
        llm_stage=StageResult(
            name="LLM_INTELLIGENCE",
            status=StageStatus.PASS_DEGRADED,
            duration_seconds=0.0,
            message="fixture",
            metadata={
                "provider": "fixture",
                "model": "fixture-v1",
                "connectivity": "AVAILABLE",
                "accepted_events": 0,
            },
        ),
    )
    securities = document["securities"]
    assert isinstance(securities, list)
    assert {item["symbol"] for item in securities} == {"AAA", "BBB"}
    assert all(item["applied_llm_adjustment"] == 0.0 for item in securities)
    status = document["status"]
    assert isinstance(status, dict)
    assert status["formal_economic_influence"] == 0.0
    invariants = document["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["pre_optimizer_top_n"] is None
    assert invariants["fixed_holdings_cap"] is None
    assert invariants["all_eligible_securities_retained"] is True


def test_shadow_hybrid_provider_failure_is_degraded_without_production_influence() -> None:
    class FailingProvider:
        name = "fixture"
        model = "fixture-timeout"

        def __init__(self) -> None:
            self.called = False

        def generate(self, request: object) -> object:
            del request
            self.called = True
            raise LLMProviderError("timeout", category="TIMEOUT")

    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    identity = SecurityIdentity(
        permanent_security_id="PERM:AAA",
        company_id="company-aaa",
        symbol="AAA",
        symbol_as_of_time=datetime(2026, 8, 17, 11, tzinfo=UTC),
    )
    pit_event = EventRecord(
        event_id="event-aaa",
        symbol="AAA",
        company_id="company-aaa",
        security=identity,
        event_type=EventType.EARNINGS,
        source_id="public-source",
        source_name="public-source",
        source_type="NEWS",
        source_reliability_class="TIER1",
        title="AAA quarterly update",
        summary="Public point-in-time event summary.",
        published_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
        first_seen_at=datetime(2026, 8, 17, 10, 5, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 17, 10, 6, tzinfo=UTC),
        available_at=datetime(2026, 8, 17, 10, 5, tzinfo=UTC),
        decision_cutoff=now,
        content_hash="content-event-aaa",
        source_hash="source-event-aaa",
    )
    workflow = SimpleNamespace(
        factors=(
            SimpleNamespace(
                symbol="AAA",
                rank=1,
                expected_alpha=0.03,
                components={"momentum": 0.2},
                evidence_coverage=0.9,
            ),
        ),
        target=SimpleNamespace(target_weights={"AAA": 0.05}),
        current_weights={"AAA": 0.02},
        probability_counterfactual={},
        decision_time=now,
        risk_regime="QUANT_NEUTRAL",
        data_freshness="CURRENT",
        shadow_context=None,
    )
    provider = FailingProvider()
    document = build_shadow_hybrid_document(
        workflow=workflow,
        llm_stage=None,
        evidence=AgenticShadowEvidence(
            companies={
                "AAA": ShadowCompanyEvidence(
                    security=identity,
                    company_name="AAA Corporation",
                    business_summary="Public issuer profile.",
                    events=(pit_event,),
                    analyses=(),
                )
            }
        ),
        provider=provider,
    )
    assert provider.called is True
    assert document["status"]["formal_economic_influence"] == 0.0
    assert document["counts"]["real_structured_theses"] == 0
    assert document["counts"]["real_shadow_llm_decisions"] == 0
    assert document["invariants"]["production_lambda"] == 0.0
    assert document["invariants"]["production_targets_unchanged"] is True
    assert document["degradation"]["by_symbol"]["AAA"] == ["TIMEOUT"]
