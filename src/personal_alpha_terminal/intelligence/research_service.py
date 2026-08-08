from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

import pandas as pd

from personal_alpha_terminal.intelligence.cross_asset import (
    CrossAssetContext,
    CrossAssetContextEngine,
)
from personal_alpha_terminal.intelligence.fusion import (
    ResearchFeatureType,
    ValidatedResearchFeature,
)
from personal_alpha_terminal.intelligence.narrative import (
    NarrativeDetectionEngine,
    NarrativeResult,
)
from personal_alpha_terminal.intelligence.relationship import (
    MarketRelationshipGraphEngine,
    RelationshipGraphSnapshot,
    RelationshipNode,
    RelationshipType,
)
from personal_alpha_terminal.intelligence.research import (
    HypothesisDefinition,
    HypothesisObservation,
    HypothesisValidation,
    HypothesisValidationEngine,
    PromotionStatus,
    ResearchPromotionGate,
)
from personal_alpha_terminal.intelligence.schemas import BacktestSafety, UnifiedEvent, _aware
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository


@dataclass(frozen=True, slots=True)
class PhaseBResearchInput:
    events: tuple[UnifiedEvent, ...]
    returns: pd.DataFrame
    relationship_nodes: tuple[RelationshipNode, ...]
    cross_asset_prices: dict[str, pd.Series]
    hypothesis_definitions: tuple[HypothesisDefinition, ...]
    hypothesis_observations: dict[str, tuple[HypothesisObservation, ...]]
    data_cutoff: datetime
    data_version: str
    regime: str
    real_data_validated: bool = False


@dataclass(frozen=True, slots=True)
class PhaseBResearchOutput:
    narratives: NarrativeResult
    relationships: RelationshipGraphSnapshot
    hypotheses: tuple[HypothesisValidation, ...]
    cross_asset: CrossAssetContext
    research_features_by_symbol: dict[str, tuple[ValidatedResearchFeature, ...]]
    lineage_by_symbol: dict[str, dict[str, object]]
    status: str
    blockers: tuple[str, ...]


class PhaseBResearchEngine:
    """One PIT orchestration path for P1 research features and persistence."""

    def __init__(
        self,
        repository: IntelligenceRepository,
        *,
        narrative_engine: NarrativeDetectionEngine | None = None,
        relationship_engine: MarketRelationshipGraphEngine | None = None,
        hypothesis_engine: HypothesisValidationEngine | None = None,
        cross_asset_engine: CrossAssetContextEngine | None = None,
    ) -> None:
        self.repository = repository
        self.narrative_engine = narrative_engine or NarrativeDetectionEngine()
        self.relationship_engine = relationship_engine or MarketRelationshipGraphEngine()
        self.hypothesis_engine = hypothesis_engine or HypothesisValidationEngine()
        self.cross_asset_engine = cross_asset_engine or CrossAssetContextEngine()
        self.promotion_gate = ResearchPromotionGate()

    def run(self, inputs: PhaseBResearchInput) -> PhaseBResearchOutput:
        _aware(inputs.data_cutoff, "data_cutoff")
        visible_events = tuple(
            event
            for item in inputs.events
            if (event := item.at_cutoff(inputs.data_cutoff)) is not None
        )
        narratives = self.narrative_engine.detect(
            visible_events,
            data_cutoff=inputs.data_cutoff,
        )
        self.repository.add_narrative_result(narratives)
        relationships = self.relationship_engine.build(
            inputs.returns,
            nodes=inputs.relationship_nodes,
            data_cutoff=inputs.data_cutoff,
            data_version=inputs.data_version,
            regime=inputs.regime,
        )
        node_id_by_symbol = {
            node.symbol.upper(): node.node_id for node in inputs.relationship_nodes
        }
        narrative_exposures: dict[str, set[str]] = {}
        for exposure in narratives.exposures:
            node_id = node_id_by_symbol.get(exposure.symbol.upper())
            if node_id is not None:
                narrative_exposures.setdefault(node_id, set()).add(
                    exposure.narrative_id
                )
        coexposure = self.relationship_engine.coexposure_edges(
            nodes=inputs.relationship_nodes,
            exposures=narrative_exposures,
            relationship_type=RelationshipType.NARRATIVE_CO_EXPOSURE,
            data_cutoff=inputs.data_cutoff,
            data_version=inputs.data_version,
            backtest_safe=all(
                item.backtest_safety is BacktestSafety.BACKTEST_SAFE
                for item in narratives.narratives
            ),
        )
        relationships = relationships.model_copy(
            update={
                "snapshot_id": sha256(
                    (
                        relationships.snapshot_id
                        + "|"
                        + "|".join(item.edge_id for item in coexposure)
                    ).encode()
                ).hexdigest(),
                "edges": tuple(
                    sorted(
                        (*relationships.edges, *coexposure),
                        key=lambda item: item.edge_id,
                    )
                ),
            }
        )
        self.repository.add_relationship_graph(relationships)
        validations = self.hypothesis_engine.validate_many(
            inputs.hypothesis_definitions,
            inputs.hypothesis_observations,
            evaluation_cutoff=inputs.data_cutoff,
            real_data_validated=inputs.real_data_validated,
        )
        validation_map = {item.hypothesis_id: item for item in validations}
        for definition in inputs.hypothesis_definitions:
            self.repository.add_hypothesis(definition, validation_map[definition.hypothesis_id])
        cross_asset = self.cross_asset_engine.evaluate(
            inputs.cross_asset_prices,
            data_cutoff=inputs.data_cutoff,
        )
        features, lineage = self._features(
            narratives,
            relationships,
            inputs.hypothesis_definitions,
            validations,
            inputs,
        )
        blockers: list[str] = []
        if not inputs.real_data_validated:
            blockers.append("real point-in-time intelligence data is not certified")
        if narratives.unavailable_reason:
            blockers.append(narratives.unavailable_reason)
        if not relationships.edges:
            blockers.append("relationship graph has no validated statistical edges")
        status = "RESEARCH_ONLY" if blockers else "VALIDATED_RESEARCH"
        return PhaseBResearchOutput(
            narratives,
            relationships,
            validations,
            cross_asset,
            features,
            lineage,
            status,
            tuple(blockers),
        )

    def _features(
        self,
        narratives: NarrativeResult,
        relationships: RelationshipGraphSnapshot,
        definitions: tuple[HypothesisDefinition, ...],
        validations: tuple[HypothesisValidation, ...],
        inputs: PhaseBResearchInput,
    ) -> tuple[
        dict[str, tuple[ValidatedResearchFeature, ...]],
        dict[str, dict[str, object]],
    ]:
        grouped: dict[str, list[ValidatedResearchFeature]] = {}
        lineage: dict[str, dict[str, object]] = {}
        narrative_by_id = {item.narrative_id: item for item in narratives.narratives}
        for exposure in narratives.exposures:
            narrative = narrative_by_id[exposure.narrative_id]
            grouped.setdefault(exposure.symbol, []).append(
                ValidatedResearchFeature(
                    feature_id=exposure.exposure_id,
                    symbol=exposure.symbol,
                    feature_type=ResearchFeatureType.NARRATIVE,
                    expected_return_lift=0.0,
                    confidence=exposure.confidence,
                    promotion_status=PromotionStatus.RESEARCH_ONLY,
                    backtest_safety=exposure.backtest_safety,
                    data_cutoff=inputs.data_cutoff,
                    valid_until=inputs.data_cutoff + timedelta(days=7),
                    source_ids=(narrative.narrative_id, *narrative.event_ids),
                    model_version=narrative.model_version,
                    data_version=inputs.data_version,
                    real_data_validated=inputs.real_data_validated,
                )
            )
            _append_lineage(
                lineage,
                exposure.symbol,
                "narrative_ids",
                narrative.narrative_id,
            )
            for event_id in narrative.event_ids:
                _append_lineage(lineage, exposure.symbol, "event_ids", event_id)
            for reference in narrative.evidence_references:
                _append_lineage(lineage, exposure.symbol, "raw_evidence", reference)
        node_by_id = {item.node_id: item for item in relationships.nodes}
        for edge in relationships.edges:
            for node_id in (edge.source_node, edge.target_node):
                node = node_by_id[node_id]
                grouped.setdefault(node.symbol, []).append(
                    ValidatedResearchFeature(
                        feature_id=edge.edge_id,
                        symbol=node.symbol,
                        feature_type=ResearchFeatureType.RELATIONSHIP,
                        expected_return_lift=0.0,
                        confidence=edge.stability_score,
                        promotion_status=PromotionStatus.RESEARCH_ONLY,
                        backtest_safety=edge.backtest_safety,
                        data_cutoff=inputs.data_cutoff,
                        valid_until=inputs.data_cutoff + timedelta(days=5),
                        source_ids=(edge.edge_id,),
                        model_version=edge.model_version,
                        data_version=edge.data_version,
                        real_data_validated=inputs.real_data_validated,
                    )
                )
                _append_lineage(lineage, node.symbol, "relationship_ids", edge.edge_id)
        definition_map = {item.hypothesis_id: item for item in definitions}
        for validation in validations:
            definition = definition_map[validation.hypothesis_id]
            promotion = self.promotion_gate.evaluate(validation)
            grouped.setdefault(definition.target, []).append(
                ValidatedResearchFeature(
                    feature_id=validation.hypothesis_id,
                    symbol=definition.target,
                    feature_type=ResearchFeatureType.HYPOTHESIS,
                    expected_return_lift=validation.after_cost_effect_size,
                    confidence=validation.oos_stability,
                    promotion_status=promotion.status,
                    backtest_safety=definition.backtest_safety,
                    data_cutoff=inputs.data_cutoff,
                    valid_until=inputs.data_cutoff + timedelta(days=definition.horizon),
                    source_ids=(validation.hypothesis_id,),
                    model_version=validation.model_version,
                    data_version=inputs.data_version,
                    real_data_validated=inputs.real_data_validated,
                )
            )
            _append_lineage(
                lineage,
                definition.target,
                "hypothesis_ids",
                validation.hypothesis_id,
            )
        for symbol in grouped:
            unavailable: list[str] = []
            if not narratives.narratives:
                unavailable.append("NARRATIVE")
            if not relationships.edges:
                unavailable.append("RELATIONSHIP")
            if not validations:
                unavailable.append("HYPOTHESIS")
            lineage.setdefault(symbol, {})["unavailable_layers"] = tuple(unavailable)
        return (
            {key: tuple(value) for key, value in grouped.items()},
            {key: _freeze_lineage(value) for key, value in lineage.items()},
        )


def _append_lineage(
    lineage: dict[str, dict[str, object]],
    symbol: str,
    key: str,
    value: str,
) -> None:
    record = lineage.setdefault(symbol, {})
    values = record.setdefault(key, [])
    if not isinstance(values, list):
        raise TypeError("lineage collection is not mutable during assembly")
    if value not in values:
        values.append(value)


def _freeze_lineage(value: dict[str, object]) -> dict[str, object]:
    return {
        key: tuple(sorted(item)) if isinstance(item, list) else item
        for key, item in value.items()
    }
