from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMResponse
from personal_alpha_terminal.application.agentic_shadow_service import (
    AgenticShadowEvidence,
    ShadowCompanyEvidence,
    build_agentic_shadow_document,
)
from personal_alpha_terminal.intelligence.agentic_engine import (
    CompanyThesisAnalyzer,
    EventAnalysis,
    EventLedger,
    PITViolation,
    build_company_thesis_prompt,
)
from personal_alpha_terminal.intelligence.agentic_models import (
    EventIntelligenceFeatures,
    EventRecord,
    EventType,
    LLMInferenceRecord,
    OutboundQuantEvidence,
    QuantThesis,
    SecurityIdentity,
)

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def security(symbol: str = "AAA") -> SecurityIdentity:
    return SecurityIdentity(
        permanent_security_id=f"PERM:{symbol}",
        company_id=f"company-{symbol.casefold()}",
        symbol=symbol,
        symbol_as_of_time=NOW - timedelta(days=30),
    )


def event(
    event_id: str = "event-1",
    *,
    symbol: str = "AAA",
    available_at: datetime = NOW - timedelta(hours=1),
    content_hash: str | None = None,
    revision: bool = False,
    parent: str | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        symbol=symbol,
        company_id=f"company-{symbol.casefold()}",
        security=security(symbol),
        event_type=EventType.EARNINGS,
        source_id=f"public-{event_id}",
        source_name="public-news",
        source_type="NEWS",
        source_reliability_class="TIER1",
        title=f"{symbol} public update",
        summary="Point-in-time public company evidence.",
        published_at=available_at - timedelta(minutes=5),
        first_seen_at=available_at,
        ingested_at=available_at + timedelta(minutes=1),
        available_at=available_at,
        decision_cutoff=NOW if available_at <= NOW else None,
        content_hash=content_hash or f"content-{event_id}",
        source_hash=f"source-{event_id}",
        is_revision=revision,
        parent_event_id=parent,
    )


def quant() -> QuantThesis:
    return QuantThesis(
        symbol="AAA",
        security=security(),
        quant_rank=1.0,
        expected_alpha=0.02,
        factor_contributions={"momentum": 0.8},
        probability_evidence=0.6,
        uncertainty=0.1,
    )


class ScenarioProvider:
    name = "fixture-external"
    model = "fixture-v1"

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0

    def generate(self, request) -> LLMResponse:
        self.calls += 1
        if self.mode in {"timeout", "provider_failure"}:
            category = "TIMEOUT" if self.mode == "timeout" else "PROVIDER_UNAVAILABLE"
            raise LLMProviderError(self.mode, category=category)
        user_data = json.loads(request.user_prompt)["USER_DATA"]
        identity = dict(user_data["security"])
        event_id = user_data["events"][0]["event_id"]
        payload: dict[str, object] = {
            "symbol": identity["symbol"],
            "security": identity,
            "stance": "BULLISH",
            "confidence": 0.9,
            "event_direction": 1.0,
            "event_magnitude": 1.0,
            "market_surprise": 1.0,
            "novelty": 1.0,
            "company_relevance": 1.0,
            "expected_horizon_sessions": 5,
            "bull_case": "The supplied event supports upside.",
            "bear_case": "The supplied event may not persist.",
            "key_catalysts": ["PUBLIC_EVENT"],
            "invalidation_conditions": ["EVENT_REVERSED"],
            "risk_flags": [],
            "evidence_event_ids": [event_id],
            "concise_rationale": "Only the supplied event was used.",
            "unsupported_claims": [],
            "source_conflict": self.mode == "conflict",
        }
        if self.mode == "refusal":
            payload = {"refusal": "cannot comply"}
        elif self.mode == "partial":
            payload.pop("security")
        elif self.mode == "hallucinated_ticker":
            payload["symbol"] = "ZZZZ"
        elif self.mode == "wrong_company":
            payload["security"] = security("BBB").model_dump(mode="json")
        elif self.mode == "wrong_event":
            payload["evidence_event_ids"] = ["unknown-event"]
        elif self.mode == "nan":
            payload["confidence"] = float("nan")
        elif self.mode == "positive_infinity":
            payload["event_magnitude"] = float("inf")
        elif self.mode == "negative_infinity":
            payload["event_direction"] = float("-inf")
        elif self.mode == "extra_field":
            payload["max_position_weight"] = 1.0
        elif self.mode == "extreme_bearish":
            payload["stance"] = "BEARISH"
            payload["event_direction"] = -1.0
        content = "{" if self.mode == "malformed" else json.dumps(payload)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id=f"request-{self.mode}",
        )


@pytest.mark.parametrize(
    "mode",
    (
        "timeout",
        "provider_failure",
        "refusal",
        "malformed",
        "partial",
        "hallucinated_ticker",
        "wrong_company",
        "wrong_event",
        "nan",
        "positive_infinity",
        "negative_infinity",
        "extra_field",
    ),
)
def test_structured_thesis_red_team_matrix_fails_closed(mode: str) -> None:
    provider = ScenarioProvider(mode)
    result = CompanyThesisAnalyzer(provider).analyze(
        quant=quant(),
        events=(event(),),
        decision_time=NOW,
        now=NOW,
    )
    assert provider.calls == 1
    assert result.status == "DEGRADED"
    assert result.thesis is None
    assert result.inference.status == "FALLBACK"
    assert result.inference.output_hash is None


def test_future_wrong_identity_and_nonfinite_outbound_data_never_reach_provider() -> None:
    provider = ScenarioProvider("valid")
    with pytest.raises(PITViolation):
        build_company_thesis_prompt(
            quant=quant(),
            events=(event("future", available_at=NOW + timedelta(seconds=1)),),
            decision_time=NOW,
        )
    assert provider.calls == 0

    with pytest.raises(ValueError, match="wrong-company"):
        build_company_thesis_prompt(
            quant=quant(),
            events=(event("wrong-company", symbol="BBB"),),
            decision_time=NOW,
        )
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            OutboundQuantEvidence(
                quant_rank=1.0,
                expected_alpha_value=value,
                uncertainty=0.1,
            )


def test_external_payload_is_a_strict_minimized_allowlist() -> None:
    request = build_company_thesis_prompt(
        quant=quant(),
        events=(event(),),
        decision_time=NOW,
    )
    outbound = json.loads(request.user_prompt)["USER_DATA"]
    assert set(outbound) == {
        "security",
        "decision_timestamp",
        "information_cutoff",
        "quant_evidence",
        "events",
    }
    assert set(outbound["security"]) == {
        "permanent_security_id",
        "company_id",
        "symbol",
        "symbol_as_of_time",
    }
    assert set(outbound["quant_evidence"]) == {
        "quant_rank",
        "expected_alpha_value",
        "expected_alpha_semantics",
        "factor_contributions",
        "probability_evidence",
        "uncertainty",
        "risk_flags",
    }
    assert set(outbound["events"][0]) == {
        "event_id",
        "event_type",
        "title",
        "summary",
        "published_at",
        "available_at",
        "source_id",
        "source_name",
        "content_hash",
    }
    serialized = json.dumps(outbound, sort_keys=True).casefold()
    for forbidden in (
        "api_key",
        "token",
        "password",
        "cookie",
        ".env",
        "account_id",
        "cash_balance",
        "total_account_value",
        "holding_quantity",
        "cost_basis",
        "order_history",
        "broker",
        "github",
        "private_key",
    ):
        assert forbidden not in serialized


def analysis(
    *,
    time_decay: float,
    direction: float = 1.0,
    event_id: str = "event-1",
) -> EventAnalysis:
    features = EventIntelligenceFeatures(
        direction=direction,
        magnitude=1.0,
        novelty=1.0,
        company_relevance=1.0,
        market_surprise=1.0,
        confidence=1.0,
        source_quality=1.0,
        time_decay=time_decay,
        expected_horizon_sessions=5,
        evidence_event_ids=(event_id,),
    )
    inference = LLMInferenceRecord(
        inference_id=f"stored-{event_id}-{time_decay}",
        provider="stored",
        model="stored-v1",
        prompt_version="stored-v1",
        schema_version_used="event-features-v1",
        request_timestamp=NOW - timedelta(hours=1),
        response_timestamp=NOW - timedelta(minutes=59),
        input_hash="input-hash",
        output_hash="output-hash",
        temperature=0.0,
        latency_ms=1,
        status="STORED_VALIDATED_OUTPUT",
        event_ids=(event_id,),
        parsed_output=features.model_dump(mode="json"),
    )
    return EventAnalysis(features=features, inference=inference, status="AVAILABLE")


def workflow() -> SimpleNamespace:
    return SimpleNamespace(
        factors=(
            SimpleNamespace(
                symbol="AAA",
                rank=1,
                composite=1.0,
                expected_alpha=0.02,
                components={"momentum": 0.8},
                evidence_coverage=0.9,
            ),
        ),
        target=SimpleNamespace(target_weights={"AAA": 0.05}),
        current_weights={"AAA": 0.02},
        probability_counterfactual={"AAA": {"conditional_probability": 0.6}},
        decision_time=NOW,
        data_cutoff=NOW,
        risk_regime="QUANT_NEUTRAL",
        data_freshness="CURRENT",
        risk=None,
        data_hash="data-v1",
        model_hash="model-v1",
        config_hash="config-v1",
        universe_snapshot_id="universe-v1",
        benchmark_symbol="SPY",
        shadow_context=None,
    )


@pytest.mark.parametrize(
    ("mode", "time_decay", "expected_reason"),
    (
        ("valid", 0.0, "STALE_EVENT_EVIDENCE"),
        ("conflict", 1.0, "CONFLICTING_EVENT_EVIDENCE"),
    ),
)
def test_stale_and_conflicting_evidence_cannot_create_semantic_alpha(
    mode: str,
    time_decay: float,
    expected_reason: str,
) -> None:
    provider = ScenarioProvider(mode)
    document = build_agentic_shadow_document(
        workflow=workflow(),
        llm_stage=None,
        evidence=AgenticShadowEvidence(
            companies={
                "AAA": ShadowCompanyEvidence(
                    security=security(),
                    company_name="AAA Corporation",
                    business_summary="Public company profile.",
                    events=(event(),),
                    analyses=(analysis(time_decay=time_decay),),
                )
            }
        ),
        provider=provider,
    )
    assert document["degradation"]["by_symbol"]["AAA"] == [expected_reason]
    assert document["securities"][0]["applied_llm_adjustment"] == 0.0
    assert document["actions"][0]["quant_only_target"] == 0.05
    assert document["actions"][0]["hybrid_target"] == 0.05
    assert document["invariants"]["production_lambda"] == 0.0
    assert document["status"]["formal_economic_influence"] == 0.0


def test_empty_event_set_never_calls_provider_or_changes_quant_target() -> None:
    provider = ScenarioProvider("valid")
    document = build_agentic_shadow_document(
        workflow=workflow(),
        llm_stage=None,
        evidence=AgenticShadowEvidence(
            companies={
                "AAA": ShadowCompanyEvidence(
                    security=security(),
                    company_name="AAA Corporation",
                    business_summary="Public company profile.",
                    events=(),
                    analyses=(),
                )
            }
        ),
        provider=provider,
    )
    assert provider.calls == 0
    assert document["degradation"]["by_symbol"]["AAA"] == ["NO_PIT_EVENTS"]
    assert document["actions"][0]["quant_only_target"] == 0.05
    assert document["actions"][0]["hybrid_target"] == 0.05
    assert document["invariants"]["production_lambda"] == 0.0


def test_deterministic_conflicting_sources_block_semantic_alpha_even_if_llm_misses_it() -> None:
    provider = ScenarioProvider("valid")
    document = build_agentic_shadow_document(
        workflow=workflow(),
        llm_stage=None,
        evidence=AgenticShadowEvidence(
            companies={
                "AAA": ShadowCompanyEvidence(
                    security=security(),
                    company_name="AAA Corporation",
                    business_summary="Public company profile.",
                    events=(
                        event("event-1"),
                        event("event-2"),
                    ),
                    analyses=(
                        analysis(
                            time_decay=1.0,
                            direction=1.0,
                            event_id="event-1",
                        ),
                        analysis(
                            time_decay=1.0,
                            direction=-1.0,
                            event_id="event-2",
                        ),
                    ),
                )
            }
        ),
        provider=provider,
    )
    assert provider.calls == 1
    assert document["degradation"]["by_symbol"]["AAA"] == [
        "CONFLICTING_EVENT_EVIDENCE"
    ]
    assert document["securities"][0]["applied_llm_adjustment"] == 0.0
    assert document["debates"]["AAA"]["reason_codes"][-1] == "SOURCE_CONFLICT"
    assert document["actions"][0]["hybrid_target"] == 0.05


@pytest.mark.parametrize("mode", ("valid", "extreme_bearish"))
def test_extreme_semantic_scores_are_bounded_shadow_only(mode: str) -> None:
    document = build_agentic_shadow_document(
        workflow=workflow(),
        llm_stage=None,
        evidence=AgenticShadowEvidence(
            companies={
                "AAA": ShadowCompanyEvidence(
                    security=security(),
                    company_name="AAA Corporation",
                    business_summary="Public company profile.",
                    events=(event(),),
                    analyses=(analysis(time_decay=1.0),),
                )
            }
        ),
        provider=ScenarioProvider(mode),
    )
    row = document["securities"][0]
    assert abs(row["semantic_event_alpha"]) <= 0.005
    assert abs(row["applied_llm_adjustment"]) <= 0.001
    assert row["production_influence"] == 0.0
    assert document["invariants"]["production_targets_unchanged"] is True


def test_duplicate_and_amended_events_preserve_point_in_time_history() -> None:
    ledger = EventLedger()
    original = event("event-1", content_hash="same-content")
    duplicate = event("event-duplicate", content_hash="same-content")
    revision = event(
        "event-revision",
        available_at=NOW - timedelta(minutes=30),
        revision=True,
        parent="event-1",
    )
    assert ledger.append(original).event_id == "event-1"
    assert ledger.append(duplicate).event_id == "event-1"
    ledger.append(revision)
    assert [item.event_id for item in ledger.visible(NOW)] == [
        "event-1",
        "event-revision",
    ]
