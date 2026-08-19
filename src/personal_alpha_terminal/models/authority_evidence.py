"""Append-only ROUND80 authority evidence ledgers.

These tables store provenance and immutable research identities only.  They do
not participate in the operational price-refresh or terminal-start path.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base


class AuthorityRawFetchEvidence(Base):
    __tablename__ = "authority_raw_fetch_evidence"
    __table_args__ = (
        CheckConstraint("received_at >= requested_at", name="valid_authority_fetch_timestamps"),
        UniqueConstraint("fetch_id", name="uq_authority_raw_fetch_id"),
        UniqueConstraint("immutable_identity", name="uq_authority_raw_fetch_identity"),
        Index("ix_authority_raw_fetch_domain_received", "domain", "received_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    fetch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snapshot_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    immutable_identity: Mapped[str] = mapped_column(String(64), nullable=False)


class AuthorityDatasetSnapshotRecord(Base):
    __tablename__ = "authority_dataset_snapshots"
    __table_args__ = (
        CheckConstraint("data_cutoff <= created_at", name="valid_authority_snapshot_cutoff"),
        UniqueConstraint("snapshot_id", name="uq_authority_dataset_snapshot_id"),
        UniqueConstraint("manifest_hash", name="uq_authority_dataset_manifest_hash"),
        Index("ix_authority_dataset_snapshot_cutoff", "data_cutoff"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    raw_hashes: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    normalized_dataset_hashes: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    security_master_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    corporate_action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    benchmark_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fundamental_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    universe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class HistoricalIndexConstituentEvidence(Base):
    __tablename__ = "historical_index_constituent_evidence"
    __table_args__ = (
        CheckConstraint("index_id IN ('SP500', 'NASDAQ100')", name="valid_historical_index_id"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="valid_historical_index_period",
        ),
        CheckConstraint(
            "announcement_time IS NULL OR announcement_time <= known_at",
            name="valid_historical_index_announcement",
        ),
        UniqueConstraint(
            "index_id", "security_id", "effective_from", "source", "source_record_id",
            name="uq_historical_index_constituent_source",
        ),
        Index(
            "ix_historical_index_constituent_pit",
            "index_id",
            "effective_from",
            "effective_to",
            "known_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    index_id: Mapped[str] = mapped_column(String(16), nullable=False)
    security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    announcement_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(512), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AuthorityProviderConflictRecord(Base):
    __tablename__ = "authority_provider_conflicts"
    __table_args__ = (
        UniqueConstraint("conflict_id", name="uq_authority_provider_conflict_id"),
        Index("ix_authority_provider_conflict_domain_status", "domain", "quality_status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    conflict_id: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_a: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_b: Mapped[str] = mapped_column(String(128), nullable=False)
    value_a: Mapped[str] = mapped_column(Text, nullable=False)
    value_b: Mapped[str] = mapped_column(Text, nullable=False)
    tolerance: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(64), nullable=False)
