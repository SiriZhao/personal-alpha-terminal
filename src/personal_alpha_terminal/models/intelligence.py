from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin

_ID = BigInteger().with_variant(Integer, "sqlite")


class IntelligenceRawInformation(TimestampMixin, Base):
    __tablename__ = "intelligence_raw_information"
    __table_args__ = (
        UniqueConstraint("raw_id", name="uq_intelligence_raw_id"),
        UniqueConstraint("source_hash", name="uq_intelligence_raw_source_hash"),
        Index("ix_intelligence_raw_observed", "observed_at"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    raw_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceEvent(TimestampMixin, Base):
    __tablename__ = "intelligence_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_intelligence_event_id"),
        Index("ix_intelligence_event_visible", "observed_at", "data_cutoff"),
        Index("ix_intelligence_event_symbol_type", "symbol", "event_type"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_cluster_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str | None] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    backtest_safety: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceEventEvidence(TimestampMixin, Base):
    __tablename__ = "intelligence_event_evidence"
    __table_args__ = (
        UniqueConstraint("event_id", "source_hash", name="uq_intelligence_event_evidence"),
        Index("ix_intelligence_evidence_event", "event_id"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_events.event_id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)


class IntelligenceFeature(TimestampMixin, Base):
    __tablename__ = "intelligence_features"
    __table_args__ = (
        UniqueConstraint("feature_id", name="uq_intelligence_feature_id"),
        Index("ix_intelligence_feature_event", "event_id"),
        Index("ix_intelligence_feature_cutoff", "data_cutoff"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_events.event_id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceResearchResult(TimestampMixin, Base):
    __tablename__ = "intelligence_research_results"
    __table_args__ = (
        UniqueConstraint("result_id", name="uq_intelligence_result_id"),
        Index("ix_intelligence_result_cutoff", "data_cutoff"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceExtractionCache(TimestampMixin, Base):
    __tablename__ = "intelligence_extraction_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class IntelligenceHypothesis(TimestampMixin, Base):
    __tablename__ = "intelligence_hypotheses"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_version_id", name="uq_intelligence_hypothesis_version_id"
        ),
        Index(
            "ix_intelligence_hypothesis_id_status_cutoff",
            "hypothesis_id",
            "status",
            "data_cutoff",
        ),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hypothesis_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_status: Mapped[str] = mapped_column(String(48), nullable=False)
    creator: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceRelationship(TimestampMixin, Base):
    __tablename__ = "intelligence_relationships"
    __table_args__ = (
        UniqueConstraint("edge_id", name="uq_intelligence_relationship_edge_id"),
        Index(
            "ix_intelligence_relationship_pair_cutoff",
            "source_node",
            "target_node",
            "data_cutoff",
        ),
        Index("ix_intelligence_relationship_use", "relationship_use"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    edge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_node: Mapped[str] = mapped_column(String(128), nullable=False)
    target_node: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(48), nullable=False)
    relationship_use: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    data_version: Mapped[str] = mapped_column(String(128), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceNarrative(TimestampMixin, Base):
    __tablename__ = "intelligence_narratives"
    __table_args__ = (
        UniqueConstraint("narrative_id", name="uq_intelligence_narrative_id"),
        Index("ix_intelligence_narrative_name_cutoff", "name", "data_cutoff"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    narrative_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceNarrativeExposure(TimestampMixin, Base):
    __tablename__ = "intelligence_narrative_exposures"
    __table_args__ = (
        UniqueConstraint("exposure_id", name="uq_intelligence_narrative_exposure_id"),
        Index("ix_intelligence_narrative_exposure_symbol", "symbol", "data_cutoff"),
        Index("ix_intelligence_narrative_exposure_narrative", "narrative_id"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    exposure_id: Mapped[str] = mapped_column(String(64), nullable=False)
    narrative_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_narratives.narrative_id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class IntelligenceDecisionLineage(TimestampMixin, Base):
    __tablename__ = "intelligence_decision_lineage"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_intelligence_decision_lineage_id"),
        Index("ix_intelligence_decision_symbol_cutoff", "symbol", "data_cutoff"),
        Index("ix_intelligence_decision_scan_result", "scan_result_id"),
    )

    id: Mapped[int] = mapped_column(_ID, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_result_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_research_results.result_id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
