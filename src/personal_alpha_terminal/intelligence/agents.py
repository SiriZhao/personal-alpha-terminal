from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from personal_alpha_terminal.intelligence.extraction import (
    ExtractionOutcome,
    StructuredEventExtractor,
)
from personal_alpha_terminal.intelligence.schemas import (
    AgentResult,
    EventType,
    IntelligenceStatus,
    RawInformation,
)


class ResearchAgent(Protocol):
    def analyze(self, payload: object) -> AgentResult: ...


@dataclass(frozen=True, slots=True)
class QuantResearchContext:
    summary: str
    features: dict[str, object]
    evidence: tuple[str, ...]
    observed_at: datetime
    data_cutoff: datetime
    model_version: str


class NewsEventAgent:
    def __init__(self, extractor: StructuredEventExtractor) -> None:
        self.extractor = extractor

    def extract(self, information: RawInformation) -> ExtractionOutcome:
        return self.extractor.extract(information)

    def analyze(self, payload: object) -> AgentResult:
        if not isinstance(payload, RawInformation):
            raise TypeError("news event agent requires RawInformation")
        outcome = self.extract(payload)
        event = outcome.event
        return AgentResult(
            agent_type=type(self).__name__.upper(),
            result=(event.summary if event is not None else outcome.error or outcome.status.value),
            structured_features=(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "symbol": event.symbol,
                    **event.structured_features,
                }
                if event is not None
                else {}
            ),
            confidence=event.confidence if event is not None else 0.0,
            evidence=(payload.source_hash or payload.source_identifier,),
            observed_at=payload.observed_at,
            data_cutoff=payload.data_cutoff,
            model=self.extractor.provider.model,
            version="structured-event-agent-v1",
            status=outcome.status,
        )


class EarningsAgent(NewsEventAgent):
    allowed = {
        EventType.EARNINGS,
        EventType.REVENUE,
        EventType.GUIDANCE,
        EventType.MARGIN,
        EventType.CAPEX,
    }

    def extract(self, information: RawInformation) -> ExtractionOutcome:
        outcome = super().extract(information)
        if outcome.event is not None and outcome.event.event_type not in self.allowed:
            return ExtractionOutcome(
                IntelligenceStatus.AI_PARSE_FAILED,
                None,
                "earnings agent rejected non-earnings event type",
                outcome.cache_hit,
                outcome.provider,
            )
        return outcome


class MacroAgent(NewsEventAgent):
    allowed = {
        EventType.CPI,
        EventType.PCE,
        EventType.NFP,
        EventType.GDP,
        EventType.FED,
        EventType.YIELD,
        EventType.DOLLAR,
        EventType.OIL,
        EventType.TARIFF,
        EventType.SANCTIONS,
        EventType.GEOPOLITICS,
        EventType.LIQUIDITY,
    }

    def extract(self, information: RawInformation) -> ExtractionOutcome:
        outcome = super().extract(information)
        if outcome.event is not None and outcome.event.event_type not in self.allowed:
            return ExtractionOutcome(
                IntelligenceStatus.AI_PARSE_FAILED,
                None,
                "macro agent rejected non-macro event type",
                outcome.cache_hit,
                outcome.provider,
            )
        return outcome


class MarketRegimeResearchAgent:
    """Explains an existing deterministic regime; never changes it."""

    def analyze(self, payload: object) -> AgentResult:
        context = _require_context(payload)
        return AgentResult(
            agent_type="MARKET_REGIME_RESEARCH",
            result=context.summary,
            structured_features=context.features,
            confidence=1.0,
            evidence=context.evidence,
            observed_at=context.observed_at,
            data_cutoff=context.data_cutoff,
            model=context.model_version,
            version="regime-research-agent-v1",
            status=IntelligenceStatus.READY,
        )


class RiskResearchAgent:
    """Summarizes quantitative risk evidence; Quant Risk Engine remains authoritative."""

    def analyze(self, payload: object) -> AgentResult:
        context = _require_context(payload)
        return AgentResult(
            agent_type="RISK_RESEARCH",
            result=context.summary,
            structured_features=context.features,
            confidence=1.0,
            evidence=context.evidence,
            observed_at=context.observed_at,
            data_cutoff=context.data_cutoff,
            model=context.model_version,
            version="risk-research-agent-v1",
            status=IntelligenceStatus.READY,
        )


class NarrativeAgent:
    """Materializes structured narrative candidates without ranking securities."""

    def analyze(self, payload: object) -> AgentResult:
        context = _require_context(payload)
        candidates = context.features.get("narratives", ())
        if not isinstance(candidates, (list, tuple)):
            raise ValueError("narrative agent requires structured narrative candidates")
        return AgentResult(
            agent_type="NARRATIVE_RESEARCH",
            result=context.summary,
            structured_features={"narratives": list(candidates), "trading_decision": None},
            confidence=1.0 if candidates else 0.0,
            evidence=context.evidence,
            observed_at=context.observed_at,
            data_cutoff=context.data_cutoff,
            model=context.model_version,
            version="narrative-research-agent-v1",
            status=(IntelligenceStatus.READY if candidates else IntelligenceStatus.UNAVAILABLE),
        )


class RelationshipResearchAgent:
    """Proposes relationship candidates; statistical validation remains separate."""

    def analyze(self, payload: object) -> AgentResult:
        context = _require_context(payload)
        relationships = context.features.get("relationships", ())
        if not isinstance(relationships, (list, tuple)):
            raise ValueError("relationship agent requires structured candidates")
        return AgentResult(
            agent_type="RELATIONSHIP_RESEARCH",
            result=context.summary,
            structured_features={
                "relationships": list(relationships),
                "causal_claim": False,
                "trading_decision": None,
            },
            confidence=1.0 if relationships else 0.0,
            evidence=context.evidence,
            observed_at=context.observed_at,
            data_cutoff=context.data_cutoff,
            model=context.model_version,
            version="relationship-research-agent-v1",
            status=(
                IntelligenceStatus.READY
                if relationships
                else IntelligenceStatus.UNAVAILABLE
            ),
        )


class HypothesisDiscoveryAgent:
    """Emits proposed definitions only; it cannot validate or promote them."""

    def analyze(self, payload: object) -> AgentResult:
        context = _require_context(payload)
        hypotheses = context.features.get("hypotheses", ())
        if not isinstance(hypotheses, (list, tuple)):
            raise ValueError("hypothesis agent requires structured proposals")
        return AgentResult(
            agent_type="HYPOTHESIS_DISCOVERY",
            result=context.summary,
            structured_features={
                "hypotheses": list(hypotheses),
                "automatic_promotion": False,
                "trading_decision": None,
            },
            confidence=1.0 if hypotheses else 0.0,
            evidence=context.evidence,
            observed_at=context.observed_at,
            data_cutoff=context.data_cutoff,
            model=context.model_version,
            version="hypothesis-discovery-agent-v1",
            status=(IntelligenceStatus.READY if hypotheses else IntelligenceStatus.UNAVAILABLE),
        )


class ResearchResultAggregator:
    """Combines evidence records without voting, trading, or modifying quant fields."""

    def aggregate(self, results: tuple[AgentResult, ...]) -> dict[str, object]:
        ordered = tuple(sorted(results, key=lambda item: (item.agent_type, item.version)))
        return {
            "status": (
                IntelligenceStatus.READY.value
                if all(item.status is IntelligenceStatus.READY for item in ordered)
                else IntelligenceStatus.DEGRADED.value
            ),
            "results": [item.model_dump(mode="json") for item in ordered],
            "evidence": sorted({evidence for item in ordered for evidence in item.evidence}),
            "trading_decision": None,
        }


def _require_context(payload: object) -> QuantResearchContext:
    if not isinstance(payload, QuantResearchContext):
        raise TypeError("agent requires structured QuantResearchContext")
    if payload.observed_at.tzinfo is None or payload.data_cutoff.tzinfo is None:
        raise ValueError("agent context timestamps must be timezone-aware")
    if payload.data_cutoff < payload.observed_at:
        raise ValueError("agent context cutoff precedes observation")
    if not payload.evidence:
        raise ValueError("agent context requires quantitative evidence references")
    return payload
