from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
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


class ConditionalProbabilityRun(TimestampMixin, Base):
    """A probability inference layer over one persisted event-study sample."""

    __tablename__ = "conditional_probability_runs"
    __table_args__ = (
        CheckConstraint(
            "outcome_direction IN ('up', 'down')",
            name="valid_conditional_direction",
        ),
        CheckConstraint("outcome_threshold >= 0", name="nonnegative_outcome_threshold"),
        CheckConstraint("minimum_sample_size >= 2", name="valid_minimum_sample_size"),
        CheckConstraint(
            "confidence_level > 0 AND confidence_level < 1",
            name="valid_confidence_level",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_conditional_status",
        ),
        UniqueConstraint(
            "event_study_run_id",
            "outcome_direction",
            "outcome_threshold",
            "minimum_sample_size",
            "confidence_level",
            name="uq_conditional_probability_run_specification",
        ),
        Index("ix_conditional_probability_runs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    event_study_run_id: Mapped[int] = mapped_column(
        ForeignKey("event_study_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    outcome_direction: Mapped[str] = mapped_column(String(8), nullable=False)
    outcome_threshold: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_level: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list["ConditionalProbabilityResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ConditionalProbabilityResult(Base):
    """Conditional probability output for one target and trading-day horizon."""

    __tablename__ = "conditional_probability_results"
    __table_args__ = (
        CheckConstraint("horizon_days > 0", name="positive_conditional_horizon"),
        CheckConstraint("sample_size >= 0", name="nonnegative_conditional_sample"),
        CheckConstraint("success_count >= 0", name="nonnegative_success_count"),
        CheckConstraint(
            "success_count <= sample_size",
            name="success_count_not_above_sample",
        ),
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name="valid_conditional_probability",
        ),
        CheckConstraint(
            "raw_probability IS NULL OR (raw_probability >= 0 AND raw_probability <= 1)",
            name="valid_raw_conditional_probability",
        ),
        CheckConstraint(
            "confidence_lower IS NULL OR (confidence_lower >= 0 AND confidence_lower <= 1)",
            name="valid_confidence_lower",
        ),
        CheckConstraint(
            "confidence_upper IS NULL OR (confidence_upper >= 0 AND confidence_upper <= 1)",
            name="valid_confidence_upper",
        ),
        UniqueConstraint(
            "run_id",
            "target_stock_id",
            "horizon_days",
            name="uq_conditional_results_run_target_horizon",
        ),
        Index(
            "ix_conditional_results_run_horizon",
            "run_id",
            "horizon_days",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("conditional_probability_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"),
        index=True,
        nullable=False,
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    meets_minimum: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_probability: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    confidence_lower: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    confidence_upper: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    average_return: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)

    run: Mapped[ConditionalProbabilityRun] = relationship(back_populates="results")
