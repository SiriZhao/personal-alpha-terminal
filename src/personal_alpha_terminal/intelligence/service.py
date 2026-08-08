from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy.orm import Session

from personal_alpha_terminal.intelligence.cross_asset import CrossAssetContextEngine
from personal_alpha_terminal.intelligence.dedup import CanonicalEventDeduplicator
from personal_alpha_terminal.intelligence.event_study import EventStudyStatistic
from personal_alpha_terminal.intelligence.extraction import StructuredEventExtractor
from personal_alpha_terminal.intelligence.fusion import ValidatedResearchFeature
from personal_alpha_terminal.intelligence.narrative import (
    NarrativeDetectionEngine,
    NarrativeResult,
)
from personal_alpha_terminal.intelligence.relationship import (
    MarketRelationshipGraphEngine,
    RelationshipGraphSnapshot,
)
from personal_alpha_terminal.intelligence.research import (
    HypothesisDefinition,
    HypothesisValidation,
    HypothesisValidationEngine,
)
from personal_alpha_terminal.intelligence.research_service import (
    PhaseBResearchEngine,
    PhaseBResearchInput,
    PhaseBResearchOutput,
)
from personal_alpha_terminal.intelligence.scanner import (
    DailyOpportunityScanner,
    OpportunityCandidate,
    ScannerMode,
)
from personal_alpha_terminal.intelligence.schemas import (
    IntelligenceStatus,
    RawInformation,
    UnifiedEvent,
)
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.portfolio.trades import TradeProposal
from personal_alpha_terminal.quant_engine.probability import ConditionalProbability2
from personal_alpha_terminal.research.data_gate import ResearchDataAuthorization


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    status: IntelligenceStatus
    accepted_events: tuple[UnifiedEvent, ...]
    failed_raw_ids: tuple[str, ...]
    cached_count: int


class IntelligenceService:
    """Transactional application service for versioned intelligence materialization."""

    def __init__(
        self,
        session: Session,
        extractor: StructuredEventExtractor,
        *,
        deduplicator: CanonicalEventDeduplicator | None = None,
        scanner: DailyOpportunityScanner | None = None,
        narrative_engine: NarrativeDetectionEngine | None = None,
        relationship_engine: MarketRelationshipGraphEngine | None = None,
        hypothesis_engine: HypothesisValidationEngine | None = None,
        cross_asset_engine: CrossAssetContextEngine | None = None,
    ) -> None:
        self.repository = IntelligenceRepository(session)
        self.extractor = extractor
        self.deduplicator = deduplicator or CanonicalEventDeduplicator()
        self.scanner = scanner or DailyOpportunityScanner()
        self.phase_b = PhaseBResearchEngine(
            self.repository,
            narrative_engine=narrative_engine,
            relationship_engine=relationship_engine,
            hypothesis_engine=hypothesis_engine,
            cross_asset_engine=cross_asset_engine,
        )

    def materialize(self, information: tuple[RawInformation, ...]) -> MaterializationResult:
        if not information:
            return MaterializationResult(IntelligenceStatus.UNAVAILABLE, (), (), 0)
        events: list[UnifiedEvent] = []
        failed: list[str] = []
        cached = 0
        for raw in information:
            self.repository.add_raw(raw)
            outcome = self.extractor.extract(raw)
            if outcome.event is None:
                failed.append(raw.raw_id)
                continue
            events.append(outcome.event)
            cached += int(outcome.cache_hit)
        cutoff = max(item.data_cutoff for item in information)
        existing = self.repository.visible_events(cutoff)
        new_hashes = {item.source_hash for item in information}
        clustered = self.deduplicator.cluster((*existing, *events))
        canonical = tuple(
            event
            for event in clustered
            if any(item.source_hash in new_hashes for item in event.evidence)
        )
        for event in canonical:
            self.repository.upsert_event(event)
        status = (
            IntelligenceStatus.UNAVAILABLE
            if not canonical and failed
            else IntelligenceStatus.DEGRADED
            if failed
            else IntelligenceStatus.READY
        )
        return MaterializationResult(status, canonical, tuple(failed), cached)

    def replay(self, cutoff: datetime) -> tuple[UnifiedEvent, ...]:
        return self.repository.visible_events(cutoff)

    def run_phase_b_research(self, inputs: PhaseBResearchInput) -> PhaseBResearchOutput:
        return self.phase_b.run(inputs)

    def persist_narratives(self, result: NarrativeResult) -> None:
        self.repository.add_narrative_result(result)

    def persist_relationship_graph(self, snapshot: RelationshipGraphSnapshot) -> None:
        self.repository.add_relationship_graph(snapshot)

    def persist_hypotheses(
        self,
        definitions: tuple[HypothesisDefinition, ...],
        validations: tuple[HypothesisValidation, ...],
    ) -> tuple[str, ...]:
        validation_map = {item.hypothesis_id: item for item in validations}
        if len(validation_map) != len(validations):
            raise ValueError("hypothesis validations contain duplicate identities")
        return tuple(
            self.repository.add_hypothesis(definition, validation_map[definition.hypothesis_id])
            for definition in definitions
        )

    def scan(
        self,
        *,
        authorization: ResearchDataAuthorization,
        alpha_signals: tuple[AlphaSignal, ...],
        proposals: tuple[TradeProposal, ...],
        probability_by_symbol: dict[str, ConditionalProbability2],
        event_statistics_by_symbol: dict[str, EventStudyStatistic],
        current_weights: dict[str, float],
        risk_flags_by_symbol: dict[str, tuple[str, ...]],
        mode: ScannerMode,
        ai_ready: bool,
        as_of: datetime,
        research_features_by_symbol: (
            dict[str, tuple[ValidatedResearchFeature, ...]] | None
        ) = None,
        lineage_by_symbol: dict[str, dict[str, object]] | None = None,
        portfolio_constraints_by_symbol: dict[str, tuple[str, ...]] | None = None,
    ) -> tuple[OpportunityCandidate, ...]:
        candidates = self.scanner.scan(
            authorization=authorization,
            alpha_signals=alpha_signals,
            proposals=proposals,
            probability_by_symbol=probability_by_symbol,
            event_statistics_by_symbol=event_statistics_by_symbol,
            current_weights=current_weights,
            risk_flags_by_symbol=risk_flags_by_symbol,
            mode=mode,
            ai_ready=ai_ready,
            research_features_by_symbol=research_features_by_symbol,
            lineage_by_symbol=lineage_by_symbol,
            portfolio_constraints_by_symbol=portfolio_constraints_by_symbol,
            as_of=as_of,
        )
        payload: dict[str, object] = {
            "as_of": as_of.isoformat(),
            "mode": mode.value,
            "candidates": [
                {
                    "symbol": item.symbol,
                    "status": item.status.value,
                    "action_candidate": item.action_candidate,
                    "quant_score": item.quant_score,
                    "event_score": item.event_score,
                    "probability_score": item.probability_score,
                    "narrative_score": item.narrative_score,
                    "relationship_score": item.relationship_score,
                    "hypothesis_score": item.hypothesis_score,
                    "risk_score": item.risk_score,
                    "composite_score": item.composite_score,
                    "target_weight_candidate": item.target_weight_candidate,
                    "data_readiness": item.data_readiness,
                    "ai_readiness": item.ai_readiness,
                    "positive_drivers": item.positive_drivers,
                    "negative_drivers": item.negative_drivers,
                    "narrative_context": item.narrative_context,
                    "relationship_context": item.relationship_context,
                    "hypothesis_context": item.hypothesis_context,
                    "portfolio_constraints": item.portfolio_constraints,
                    "lineage": item.lineage,
                    "decision_id": item.decision_id,
                }
                for item in candidates
            ],
        }
        fingerprint = sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        self.repository.add_result(
            result_id=fingerprint,
            result_type="DAILY_OPPORTUNITY_SCAN",
            schema_version="opportunity-scan-v1",
            model_version=self.scanner.config.model_version,
            prompt_version="NONE",
            data_cutoff=as_of,
            status="READY" if candidates else "UNAVAILABLE",
            payload=payload,
        )
        self.repository.session.flush()
        for candidate in candidates:
            self.repository.add_decision_lineage(
                decision_id=candidate.decision_id,
                scan_result_id=fingerprint,
                symbol=candidate.symbol,
                data_cutoff=as_of,
                payload={
                    "decision_id": candidate.decision_id,
                    "portfolio_result": candidate.lineage.get("portfolio_result"),
                    "quant_signal": candidate.lineage.get("quant_signals", ()),
                    "probability": candidate.lineage.get("conditional_probability"),
                    "event": candidate.lineage.get("event_study"),
                    "narrative": candidate.lineage.get("narrative_ids", ()),
                    "relationship": candidate.lineage.get("relationship_ids", ()),
                    "hypothesis": candidate.lineage.get("hypothesis_ids", ()),
                    "raw_evidence": candidate.lineage.get("raw_evidence", ()),
                    "unavailable_layers": candidate.lineage.get("unavailable_layers", ()),
                },
            )
        return candidates
