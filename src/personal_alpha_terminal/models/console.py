from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin


class DataSnapshotManifest(TimestampMixin, Base):
    """Immutable lineage manifest for one provider synchronization."""

    __tablename__ = "data_snapshot_manifests"
    __table_args__ = (
        CheckConstraint(
            "quality_status IN ('passed', 'partial', 'failed', 'blocked')",
            name="valid_snapshot_quality_status",
        ),
        CheckConstraint(
            "certification_result IN ('CERTIFIED', 'PARTIAL', 'BLOCKED')",
            name="valid_snapshot_certification",
        ),
        UniqueConstraint("snapshot_id", name="uq_data_snapshot_id"),
        UniqueConstraint("content_hash", name="uq_data_snapshot_content_hash"),
        Index("ix_data_snapshot_latest", "market", "completed_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_adapter: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_adjustment_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    corporate_action_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missingness_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    stale_symbol_summary: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    failed_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    application_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False)
    certification_result: Mapped[str] = mapped_column(String(16), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
