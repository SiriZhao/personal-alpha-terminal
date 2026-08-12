from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.llm.foundation import LLMUsageRecord
from personal_alpha_terminal.intelligence.narrative import NarrativeResult, NarrativeSnapshot
from personal_alpha_terminal.intelligence.relationship import (
    RelationshipEdge,
    RelationshipGraphSnapshot,
)
from personal_alpha_terminal.intelligence.research import (
    HypothesisDefinition,
    HypothesisValidation,
)
from personal_alpha_terminal.intelligence.schemas import RawInformation, UnifiedEvent
from personal_alpha_terminal.models.intelligence import (
    IntelligenceDecisionLineage,
    IntelligenceEvent,
    IntelligenceEventEvidence,
    IntelligenceExtractionCache,
    IntelligenceHypothesis,
    IntelligenceNarrative,
    IntelligenceNarrativeExposure,
    IntelligenceRawInformation,
    IntelligenceRelationship,
    IntelligenceResearchResult,
)


class DatabaseExtractionCache:
    def __init__(self, session: Session, *, model_version: str, prompt_version: str) -> None:
        self.session = session
        self.model_version = model_version
        self.prompt_version = prompt_version

    def get(self, key: str) -> str | None:
        record = self.session.get(IntelligenceExtractionCache, key)
        return record.payload if record is not None else None

    def put(self, key: str, payload: str) -> None:
        if self.session.get(IntelligenceExtractionCache, key) is None:
            self.session.add(
                IntelligenceExtractionCache(
                    cache_key=key,
                    model_version=self.model_version,
                    prompt_version=self.prompt_version,
                    payload=payload,
                )
            )


class DatabaseLLMUsageLedger:
    """Immutable metadata-only LLM call ledger using the research result store."""

    def __init__(self, session: Session) -> None:
        self.repository = IntelligenceRepository(session)

    def append(self, record: LLMUsageRecord) -> None:
        payload = asdict(record)
        payload["generated_at"] = record.generated_at.isoformat()
        payload["as_of"] = record.as_of.isoformat() if record.as_of else None
        payload["validation_status"] = record.validation_status.value
        identity = sha256(
            f"{record.request_hash}|{record.generated_at.isoformat()}|{record.validation_status}".encode()
        ).hexdigest()
        self.repository.add_result(
            result_id=identity,
            result_type="LLM_USAGE",
            schema_version="llm-usage-v1",
            model_version=record.model,
            prompt_version=record.prompt_version,
            data_cutoff=record.as_of or record.generated_at,
            status=record.validation_status.value,
            payload=payload,
        )


class IntelligenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_raw(self, raw: RawInformation) -> None:
        exists = self.session.scalar(
            select(IntelligenceRawInformation.id).where(
                IntelligenceRawInformation.raw_id == raw.raw_id
            )
        )
        if exists is None:
            self.session.add(
                IntelligenceRawInformation(
                    raw_id=raw.raw_id,
                    source=raw.source,
                    source_identifier=raw.source_identifier,
                    source_hash=raw.source_hash or "",
                    published_at=raw.published_at,
                    observed_at=raw.observed_at,
                    ingested_at=raw.ingested_at,
                    data_cutoff=raw.data_cutoff,
                    payload=raw.model_dump(mode="json"),
                )
            )

    def upsert_event(self, event: UnifiedEvent) -> None:
        record = self.session.scalar(
            select(IntelligenceEvent).where(IntelligenceEvent.event_id == event.event_id)
        )
        payload = event.model_dump(mode="json")
        if record is None:
            record = IntelligenceEvent(
                event_id=event.event_id,
                canonical_cluster_id=event.canonical_cluster_id,
                symbol=event.symbol,
                event_type=event.event_type.value,
                observed_at=event.observed_at,
                effective_at=event.effective_at,
                data_cutoff=event.data_cutoff,
                schema_version=event.schema_version,
                model_version=event.model_version,
                prompt_version=event.prompt_version,
                backtest_safety=event.backtest_safety.value,
                payload=payload,
            )
            self.session.add(record)
            self.session.flush()
        elif record.payload != payload:
            # Event identity is immutable. Canonical revisions require a new event
            # id instead of overwriting historical evidence.
            raise ValueError(f"event_id collision with different payload: {event.event_id}")
        existing_hashes = set(
            self.session.scalars(
                select(IntelligenceEventEvidence.source_hash).where(
                    IntelligenceEventEvidence.event_id == event.event_id
                )
            )
        )
        for evidence in event.evidence:
            if evidence.source_hash not in existing_hashes:
                self.session.add(
                    IntelligenceEventEvidence(
                        event_id=event.event_id,
                        evidence_id=evidence.evidence_id,
                        source=evidence.source,
                        source_identifier=evidence.source_identifier,
                        source_hash=evidence.source_hash,
                        observed_at=evidence.observed_at,
                        reference=evidence.reference,
                    )
                )

    def visible_events(self, cutoff: datetime) -> tuple[UnifiedEvent, ...]:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("event replay cutoff must be timezone-aware")
        records = self.session.scalars(
            select(IntelligenceEvent)
            .where(
                IntelligenceEvent.observed_at <= cutoff,
            )
            .order_by(IntelligenceEvent.observed_at, IntelligenceEvent.event_id)
        )
        visible_by_cluster: dict[str, UnifiedEvent] = {}
        for record in records:
            materialized = UnifiedEvent.model_validate(record.payload).at_cutoff(cutoff)
            if materialized is not None:
                cluster = materialized.canonical_cluster_id or materialized.event_id
                current = visible_by_cluster.get(cluster)
                if current is None or (
                    len(materialized.evidence),
                    materialized.data_cutoff,
                    materialized.event_id,
                ) > (len(current.evidence), current.data_cutoff, current.event_id):
                    visible_by_cluster[cluster] = materialized
        return tuple(
            sorted(
                visible_by_cluster.values(),
                key=lambda item: (item.observed_at, item.event_id),
            )
        )

    def add_result(
        self,
        *,
        result_id: str,
        result_type: str,
        schema_version: str,
        model_version: str,
        prompt_version: str,
        data_cutoff: datetime,
        status: str,
        payload: dict[str, object],
    ) -> None:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        result_hash = sha256(serialized.encode()).hexdigest()
        existing = self.session.scalar(
            select(IntelligenceResearchResult).where(
                IntelligenceResearchResult.result_id == result_id
            )
        )
        if existing is not None:
            if existing.result_hash != result_hash:
                raise ValueError("research result identity is immutable")
            return
        self.session.add(
            IntelligenceResearchResult(
                result_id=result_id,
                result_type=result_type,
                schema_version=schema_version,
                model_version=model_version,
                prompt_version=prompt_version,
                data_cutoff=data_cutoff,
                status=status,
                result_hash=result_hash,
                payload=payload,
            )
        )

    def add_hypothesis(
        self,
        definition: HypothesisDefinition,
        validation: HypothesisValidation,
    ) -> str:
        if definition.hypothesis_id != validation.hypothesis_id:
            raise ValueError("hypothesis definition and validation identity differ")
        payload: dict[str, object] = {
            "definition": definition.model_dump(mode="json"),
            "validation": _dataclass_payload(validation),
        }
        result_hash = _payload_hash(payload)
        version_id = sha256(
            f"{definition.fingerprint}|{validation.data_cutoff.isoformat()}|{result_hash}".encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(IntelligenceHypothesis).where(
                IntelligenceHypothesis.hypothesis_version_id == version_id
            )
        )
        if existing is None:
            self.session.add(
                IntelligenceHypothesis(
                    hypothesis_id=definition.hypothesis_id,
                    hypothesis_version_id=version_id,
                    status=validation.status.value,
                    feature_status=validation.feature_status.value,
                    creator=definition.creator,
                    model_version=validation.model_version,
                    schema_version=definition.definition_version,
                    data_cutoff=validation.data_cutoff,
                    result_hash=result_hash,
                    payload=payload,
                )
            )
        return version_id

    def visible_hypotheses(self, cutoff: datetime) -> tuple[dict[str, object], ...]:
        _require_aware_cutoff(cutoff)
        records = self.session.scalars(
            select(IntelligenceHypothesis)
            .where(IntelligenceHypothesis.data_cutoff <= cutoff)
            .order_by(
                IntelligenceHypothesis.hypothesis_id,
                IntelligenceHypothesis.data_cutoff.desc(),
                IntelligenceHypothesis.hypothesis_version_id.desc(),
            )
        )
        latest: dict[str, dict[str, object]] = {}
        for record in records:
            latest.setdefault(record.hypothesis_id, dict(record.payload))
        return tuple(latest[key] for key in sorted(latest))

    def add_relationship_graph(self, snapshot: RelationshipGraphSnapshot) -> None:
        for edge in snapshot.edges:
            payload = edge.model_dump(mode="json")
            result_hash = _payload_hash(payload)
            existing = self.session.scalar(
                select(IntelligenceRelationship).where(
                    IntelligenceRelationship.edge_id == edge.edge_id
                )
            )
            if existing is not None:
                if existing.result_hash != result_hash:
                    raise ValueError("relationship edge identity is immutable")
                continue
            self.session.add(
                IntelligenceRelationship(
                    edge_id=edge.edge_id,
                    source_node=edge.source_node,
                    target_node=edge.target_node,
                    relationship_type=edge.relationship_type.value,
                    relationship_use=edge.relationship_use.value,
                    schema_version=edge.schema_version,
                    model_version=edge.model_version,
                    data_version=edge.data_version,
                    data_cutoff=edge.data_cutoff,
                    result_hash=result_hash,
                    payload=payload,
                )
            )

    def visible_relationships(self, cutoff: datetime) -> tuple[RelationshipEdge, ...]:
        _require_aware_cutoff(cutoff)
        records = self.session.scalars(
            select(IntelligenceRelationship)
            .where(IntelligenceRelationship.data_cutoff <= cutoff)
            .order_by(IntelligenceRelationship.data_cutoff.desc())
        )
        latest: dict[tuple[str, str, str, int], RelationshipEdge] = {}
        for record in records:
            edge = RelationshipEdge.model_validate(record.payload)
            key = (
                edge.source_node,
                edge.target_node,
                edge.relationship_type.value,
                edge.lag,
            )
            latest.setdefault(key, edge)
        return tuple(sorted(latest.values(), key=lambda item: item.edge_id))

    def add_narrative_result(self, result: NarrativeResult) -> None:
        for narrative in result.narratives:
            payload = narrative.model_dump(mode="json")
            result_hash = _payload_hash(payload)
            existing_narrative = self.session.scalar(
                select(IntelligenceNarrative).where(
                    IntelligenceNarrative.narrative_id == narrative.narrative_id
                )
            )
            if existing_narrative is not None:
                if existing_narrative.result_hash != result_hash:
                    raise ValueError("narrative identity is immutable")
            else:
                self.session.add(
                    IntelligenceNarrative(
                        narrative_id=narrative.narrative_id,
                        name=narrative.name,
                        schema_version=narrative.schema_version,
                        model_version=narrative.model_version,
                        taxonomy_version=narrative.taxonomy_version,
                        data_cutoff=narrative.data_cutoff,
                        result_hash=result_hash,
                        payload=payload,
                    )
                )
        self.session.flush()
        for exposure in result.exposures:
            payload = exposure.model_dump(mode="json")
            result_hash = _payload_hash(payload)
            existing_exposure = self.session.scalar(
                select(IntelligenceNarrativeExposure).where(
                    IntelligenceNarrativeExposure.exposure_id == exposure.exposure_id
                )
            )
            if existing_exposure is not None:
                if existing_exposure.result_hash != result_hash:
                    raise ValueError("narrative exposure identity is immutable")
                continue
            self.session.add(
                IntelligenceNarrativeExposure(
                    exposure_id=exposure.exposure_id,
                    narrative_id=exposure.narrative_id,
                    symbol=exposure.symbol,
                    data_cutoff=exposure.data_cutoff,
                    result_hash=result_hash,
                    payload=payload,
                )
            )

    def visible_narratives(self, cutoff: datetime) -> tuple[NarrativeSnapshot, ...]:
        _require_aware_cutoff(cutoff)
        records = self.session.scalars(
            select(IntelligenceNarrative)
            .where(IntelligenceNarrative.data_cutoff <= cutoff)
            .order_by(IntelligenceNarrative.data_cutoff.desc())
        )
        latest: dict[str, NarrativeSnapshot] = {}
        for record in records:
            narrative = NarrativeSnapshot.model_validate(record.payload)
            latest.setdefault(narrative.name, narrative)
        return tuple(latest[name] for name in sorted(latest))

    def add_decision_lineage(
        self,
        *,
        decision_id: str,
        scan_result_id: str,
        symbol: str,
        data_cutoff: datetime,
        payload: dict[str, object],
    ) -> None:
        lineage_hash = _payload_hash(payload)
        existing = self.session.scalar(
            select(IntelligenceDecisionLineage).where(
                IntelligenceDecisionLineage.decision_id == decision_id
            )
        )
        if existing is not None:
            if existing.lineage_hash != lineage_hash:
                raise ValueError("decision lineage identity is immutable")
            return
        self.session.add(
            IntelligenceDecisionLineage(
                decision_id=decision_id,
                scan_result_id=scan_result_id,
                symbol=symbol,
                data_cutoff=data_cutoff,
                lineage_hash=lineage_hash,
                payload=payload,
            )
        )


def _payload_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode()).hexdigest()


def _dataclass_payload(value: object) -> dict[str, object]:
    from dataclasses import asdict, is_dataclass

    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("research validation must be a dataclass instance")
    normalized = json.loads(json.dumps(asdict(value), sort_keys=True, default=_json_default))
    if not isinstance(normalized, dict):
        raise TypeError("research validation payload must be an object")
    return normalized


def _json_default(value: object) -> str:
    from enum import Enum

    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _require_aware_cutoff(cutoff: datetime) -> None:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("intelligence replay cutoff must be timezone-aware")
