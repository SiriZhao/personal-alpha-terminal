from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from personal_alpha_terminal.agents.llm.providers import LLMProviderError, MockProvider
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.intelligence.agents import (
    EarningsAgent,
    HypothesisDiscoveryAgent,
    MarketRegimeResearchAgent,
    NarrativeAgent,
    QuantResearchContext,
    RelationshipResearchAgent,
    ResearchResultAggregator,
    RiskResearchAgent,
)
from personal_alpha_terminal.intelligence.budget import (
    IntelligenceBudget,
    IntelligenceBudgetConfig,
)
from personal_alpha_terminal.intelligence.cache import InMemoryExtractionCache
from personal_alpha_terminal.intelligence.extraction import StructuredEventExtractor
from personal_alpha_terminal.intelligence.schemas import IntelligenceStatus, RawInformation


@dataclass
class StubProvider:
    content: str
    name: str = "stub"
    model: str = "stub-v1"
    calls: int = 0

    def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        return LLMResponse(self.content, self.name, self.model, False)


class CapturingProvider:
    name = "stub"
    model = "stub-v1"
    request: LLMRequest | None = None

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.request = request
        return LLMResponse(_pit_payload(), self.name, self.model, False)


class FailingProvider:
    name = "failing"
    model = "failing-v1"

    def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise LLMProviderError("provider timeout")


@dataclass
class ClassifiedFailingProvider:
    message: str
    name: str = "failing"
    model: str = "failing-v1"

    def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise LLMProviderError(self.message)


def _raw() -> RawInformation:
    published = datetime(2026, 8, 7, 20, tzinfo=UTC)
    return RawInformation(
        raw_id="raw-earnings",
        source="wire",
        source_identifier="story-earnings",
        title="Microsoft reports earnings",
        body="Earnings and revenue exceeded the supplied consensus figures.",
        published_at=published,
        observed_at=published + timedelta(seconds=5),
        ingested_at=published + timedelta(seconds=10),
        data_cutoff=published + timedelta(seconds=10),
    )


def _payload() -> str:
    return json.dumps(
        {
            "symbol": "MSFT",
            "entity": "Microsoft",
            "sector": "Technology",
            "industry": "Software",
            "event_type": "EARNINGS",
            "event_subtype": "quarterly",
            "summary": "Structured result based only on supplied figures.",
            "direction": "POSITIVE",
            "magnitude": 0.1,
            "surprise": 0.05,
            "relevance": 0.9,
            "novelty": 0.7,
            "confidence": 0.8,
            "expected_horizon": 20,
            "affected_assets": ["MSFT"],
            "affected_sectors": ["Technology"],
            "themes": ["Earnings"],
            "effective_at": "2026-08-07T20:00:00Z",
            "earnings_features": {
                "eps_surprise": 0.05,
                "revenue_surprise": 0.03,
                "guidance_change": 0.02,
                "margin_change": 0.01,
                "estimate_revision": 0.02,
                "management_tone": 0.6,
                "capex_revision": -0.01,
            },
            "macro_features": None,
        }
    )


def _pit_payload() -> str:
    return json.dumps(
        {
            "symbol": "TSLA",
            "entity": "Tesla, Inc.",
            "sector": "Consumer Discretionary",
            "industry": "Automotive",
            "event_type": "EARNINGS",
            "event_subtype": "quarterly results",
            "summary": "Structured result based only on supplied figures.",
            "direction": "UNKNOWN",
            "magnitude": None,
            "surprise": None,
            "relevance": 0.9,
            "novelty": 0.7,
            "confidence": 0.95,
            "expected_horizon": 90,
            "affected_assets": ["TSLA"],
            "affected_sectors": ["Consumer Discretionary"],
            "themes": ["earnings"],
            "effective_at": "2025-01-29T21:09:13Z",
            "earnings_features": None,
            "macro_features": None,
        }
    )


def _extractor(provider: object, cache: InMemoryExtractionCache) -> StructuredEventExtractor:
    budget = IntelligenceBudget(
        IntelligenceBudgetConfig(max_requests_per_run=4, max_tokens_per_run=50_000)
    )
    return StructuredEventExtractor(
        provider,  # type: ignore[arg-type]
        cache,
        budget,
        clock=lambda: datetime(2026, 8, 7, 20, 1, tzinfo=UTC),
    )


def test_structured_extraction_is_cached_and_strict() -> None:
    provider = StubProvider(_payload())
    cache = InMemoryExtractionCache()
    extractor = _extractor(provider, cache)
    first = extractor.extract(_raw())
    second = extractor.extract(_raw())
    assert first.status is IntelligenceStatus.READY
    assert second.cache_hit
    assert provider.calls == 1
    assert first.event is not None and first.event.symbol == "MSFT"
    assert first.event.structured_features["earnings"]["eps_surprise"] == 0.05


def test_structured_extraction_uses_historical_available_at_as_pit_cutoff() -> None:
    available = datetime(2025, 1, 29, 21, 9, 13, tzinfo=UTC)
    ingested = datetime(2026, 8, 12, 5, 41, tzinfo=UTC)
    raw = RawInformation(
        raw_id="sec-tsla-8k",
        source="sec-edgar",
        source_identifier="0001628280-25-002993",
        title="Tesla, Inc. 8-K",
        body="Tesla reported fourth quarter and full year 2024 results.",
        published_at=available,
        observed_at=available,
        ingested_at=ingested,
        data_cutoff=ingested,
        available_at=available,
    )
    provider = CapturingProvider()
    extractor = StructuredEventExtractor(
        provider,
        InMemoryExtractionCache(),
        IntelligenceBudget(
            IntelligenceBudgetConfig(
                max_requests_per_run=2,
                max_tokens_per_run=50_000,
            )
        ),
        clock=lambda: datetime(2026, 8, 12, 5, 45, tzinfo=UTC),
    )
    outcome = extractor.extract(raw)
    assert outcome.status is IntelligenceStatus.READY
    assert outcome.event is not None
    assert provider.request is not None
    assert provider.request.as_of == available
    assert outcome.event.data_cutoff == available
    assert "2026-08-12" not in provider.request.user_prompt
    assert "2025-01-29T21:09:13Z" in provider.request.user_prompt


def test_earnings_agent_returns_structured_features_not_a_trade() -> None:
    agent = EarningsAgent(_extractor(StubProvider(_payload()), InMemoryExtractionCache()))
    result = agent.analyze(_raw())
    assert result.status is IntelligenceStatus.READY
    assert result.structured_features["event_type"] == "EARNINGS"
    assert result.structured_features["earnings"]["capex_revision"] == -0.01
    assert "trade" not in result.structured_features


def test_ai_failures_and_mock_are_isolated() -> None:
    failed = _extractor(FailingProvider(), InMemoryExtractionCache()).extract(_raw())
    mocked = _extractor(MockProvider(), InMemoryExtractionCache()).extract(_raw())
    malformed = _extractor(StubProvider("not-json"), InMemoryExtractionCache()).extract(_raw())
    assert failed.status is IntelligenceStatus.UNAVAILABLE
    assert mocked.status is IntelligenceStatus.DEGRADED
    assert malformed.status is IntelligenceStatus.AI_PARSE_FAILED
    assert all(item.event is None for item in (failed, mocked, malformed))


@pytest.mark.parametrize(
    "failure",
    (
        "HTTP 401 unauthorized",
        "HTTP 429 rate limited",
        "unavailable model",
        "context overflow",
        "request timeout",
    ),
)
def test_provider_failure_classes_degrade_without_affecting_quant(failure: str) -> None:
    outcome = _extractor(
        ClassifiedFailingProvider(failure), InMemoryExtractionCache()
    ).extract(_raw())
    assert outcome.status is IntelligenceStatus.UNAVAILABLE
    assert outcome.event is None


def test_empty_ai_response_is_rejected() -> None:
    outcome = _extractor(StubProvider(""), InMemoryExtractionCache()).extract(_raw())
    assert outcome.status is IntelligenceStatus.AI_PARSE_FAILED
    assert outcome.event is None


def test_ai_budget_exhaustion_is_explicit() -> None:
    provider = StubProvider(_payload())
    extractor = StructuredEventExtractor(
        provider,
        InMemoryExtractionCache(),
        IntelligenceBudget(
            IntelligenceBudgetConfig(
                max_requests_per_run=1,
                max_tokens_per_run=100,
                max_cost_per_run=10,
            )
        ),
        clock=lambda: datetime(2026, 8, 7, 20, 1, tzinfo=UTC),
    )
    outcome = extractor.extract(_raw())
    assert outcome.status is IntelligenceStatus.AI_BUDGET_EXCEEDED
    assert provider.calls == 0


def test_agent_aggregator_never_produces_a_trade_vote() -> None:
    context = QuantResearchContext(
        summary="Quant regime is neutral.",
        features={"regime": "NEUTRAL"},
        evidence=("regime-run-1",),
        observed_at=datetime(2026, 8, 7, 20, tzinfo=UTC),
        data_cutoff=datetime(2026, 8, 7, 20, tzinfo=UTC),
        model_version="regime-v1",
    )
    result = MarketRegimeResearchAgent().analyze(context)
    aggregated = ResearchResultAggregator().aggregate((result,))
    assert aggregated["status"] == "READY"
    assert aggregated["trading_decision"] is None
    risk_result = RiskResearchAgent().analyze(context)
    degraded = risk_result.model_copy(update={"status": IntelligenceStatus.DEGRADED})
    assert ResearchResultAggregator().aggregate((result, degraded))["status"] == "DEGRADED"


def test_phase_b_agents_emit_research_context_without_trade_or_causal_claim() -> None:
    context = QuantResearchContext(
        summary="Structured research candidates.",
        features={
            "narratives": [{"name": "ai infrastructure"}],
            "relationships": [{"source": "NVDA", "target": "AVGO"}],
            "hypotheses": [{"target": "AVGO", "horizon": 10}],
        },
        evidence=("event-store-v1", "relationship-snapshot-v1"),
        observed_at=datetime(2026, 8, 7, 20, tzinfo=UTC),
        data_cutoff=datetime(2026, 8, 7, 20, tzinfo=UTC),
        model_version="frozen-research-v1",
    )
    narrative = NarrativeAgent().analyze(context)
    relationship = RelationshipResearchAgent().analyze(context)
    hypothesis = HypothesisDiscoveryAgent().analyze(context)

    assert narrative.structured_features["trading_decision"] is None
    assert relationship.structured_features["causal_claim"] is False
    assert relationship.structured_features["trading_decision"] is None
    assert hypothesis.structured_features["automatic_promotion"] is False
    assert hypothesis.structured_features["trading_decision"] is None


def test_agents_reject_unstructured_or_untraceable_input() -> None:
    agent = EarningsAgent(_extractor(StubProvider(_payload()), InMemoryExtractionCache()))
    with pytest.raises(TypeError, match="RawInformation"):
        agent.analyze({"headline": "not a typed source"})
    invalid_context = QuantResearchContext(
        summary="Missing evidence",
        features={},
        evidence=(),
        observed_at=datetime(2026, 8, 7, 20, tzinfo=UTC),
        data_cutoff=datetime(2026, 8, 7, 20, tzinfo=UTC),
        model_version="risk-v1",
    )
    with pytest.raises(ValueError, match="evidence"):
        RiskResearchAgent().analyze(invalid_context)
