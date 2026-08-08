from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin


class RelationshipAnalysisRun(TimestampMixin, Base):
    """An auditable execution of a market relationship analysis."""

    __tablename__ = "relationship_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "universe_type IN ('stock', 'etf', 'industry')",
            name="valid_universe_type",
        ),
        CheckConstraint(
            "method IN ('pearson', 'spearman')",
            name="valid_relationship_method",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_relationship_status",
        ),
        Index(
            "ix_relationship_runs_universe_method_created",
            "universe_type",
            "method",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    universe_type: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    correlations: Mapped[list["RelationshipCorrelation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    anomalies: Mapped[list["RelationshipAnomaly"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RelationshipCorrelation(Base):
    """A full-period or rolling pairwise correlation observation."""

    __tablename__ = "relationship_correlations"
    __table_args__ = (
        CheckConstraint(
            "left_entity_type IN ('stock', 'etf', 'industry')",
            name="valid_left_entity_type",
        ),
        CheckConstraint(
            "right_entity_type IN ('stock', 'etf', 'industry')",
            name="valid_right_entity_type",
        ),
        CheckConstraint(
            "correlation >= -1 AND correlation <= 1",
            name="valid_correlation",
        ),
        CheckConstraint("sample_size >= 2", name="valid_sample_size"),
        UniqueConstraint(
            "run_id",
            "left_entity_key",
            "right_entity_key",
            "window_days",
            "as_of_date",
            name="uq_relationship_correlation_observation",
        ),
        Index(
            "ix_relationship_correlations_pair_date",
            "left_entity_key",
            "right_entity_key",
            "as_of_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    left_entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    left_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    left_entity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    left_entity_label: Mapped[str] = mapped_column(String(256), nullable=False)
    right_entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    right_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    right_entity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    right_entity_label: Mapped[str] = mapped_column(String(256), nullable=False)
    window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    correlation: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[RelationshipAnalysisRun] = relationship(back_populates="correlations")


class RelationshipAnomaly(Base):
    """A material change between a non-overlapping baseline and current window."""

    __tablename__ = "relationship_anomalies"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('strengthened', 'weakened', 'sign_flip')",
            name="valid_relationship_direction",
        ),
        CheckConstraint("absolute_change >= 0", name="nonnegative_absolute_change"),
        Index("ix_relationship_anomalies_run_change", "run_id", "absolute_change"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    left_entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    left_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    left_entity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    left_entity_label: Mapped[str] = mapped_column(String(256), nullable=False)
    right_entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    right_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    right_entity_key: Mapped[str] = mapped_column(String(96), nullable=False)
    right_entity_label: Mapped[str] = mapped_column(String(256), nullable=False)
    detected_on: Mapped[date] = mapped_column(Date, nullable=False)
    baseline_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    current_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_correlation: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    current_correlation: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    absolute_change: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    baseline_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    current_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[RelationshipAnalysisRun] = relationship(back_populates="anomalies")
