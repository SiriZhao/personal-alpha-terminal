from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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


class EventDefinition(TimestampMixin, Base):
    """A reusable, versioned, point-in-time event rule."""

    __tablename__ = "event_definitions"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('price_return', 'volume_spike', 'new_high')",
            name="valid_event_rule_type",
        ),
        UniqueConstraint("name", "version", name="uq_event_definitions_name_version"),
        Index("ix_event_definitions_active_type", "is_active", "rule_type"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    runs: Mapped[list["EventStudyRun"]] = relationship(back_populates="definition")


class EventStudyRun(TimestampMixin, Base):
    """An auditable execution of one event definition against one trigger asset."""

    __tablename__ = "event_study_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_event_study_status",
        ),
        Index(
            "ix_event_study_runs_definition_created",
            "definition_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("event_definitions.id"),
        nullable=False,
    )
    trigger_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"),
        index=True,
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    horizons: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    definition: Mapped[EventDefinition] = relationship(back_populates="runs")
    occurrences: Mapped[list["EventOccurrence"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    statistics: Mapped[list["EventStudyStatistic"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EventOccurrence(Base):
    """One historical date where a rule matched the trigger asset."""

    __tablename__ = "event_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "event_date",
            name="uq_event_occurrences_run_date",
        ),
        Index("ix_event_occurrences_stock_date", "trigger_stock_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("event_study_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"),
        nullable=False,
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    available_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ingested_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(UTC),
    )
    trigger_value: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    reference_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    run: Mapped[EventStudyRun] = relationship(back_populates="occurrences")
    observations: Mapped[list["EventStudyObservation"]] = relationship(
        back_populates="occurrence",
        cascade="all, delete-orphan",
    )


class EventStudyObservation(Base):
    """Forward outcome for one event, target asset, and trading-day horizon."""

    __tablename__ = "event_study_observations"
    __table_args__ = (
        CheckConstraint("horizon_days > 0", name="positive_event_horizon"),
        CheckConstraint("forward_return > -1", name="valid_forward_return"),
        CheckConstraint("max_upside >= 0", name="nonnegative_max_upside"),
        CheckConstraint(
            "max_drawdown >= -1 AND max_drawdown <= 0",
            name="valid_event_max_drawdown",
        ),
        UniqueConstraint(
            "occurrence_id",
            "target_stock_id",
            "horizon_days",
            name="uq_event_observations_occurrence_target_horizon",
        ),
        Index(
            "ix_event_observations_target_horizon",
            "target_stock_id",
            "horizon_days",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    occurrence_id: Mapped[int] = mapped_column(
        ForeignKey("event_occurrences.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"),
        nullable=False,
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_date: Mapped[date] = mapped_column(Date, nullable=False)
    forward_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    max_upside: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    is_win: Mapped[bool] = mapped_column(Boolean, nullable=False)

    occurrence: Mapped[EventOccurrence] = relationship(back_populates="observations")


class EventStudyStatistic(Base):
    """Aggregated distribution statistics for one target and horizon."""

    __tablename__ = "event_study_statistics"
    __table_args__ = (
        CheckConstraint("horizon_days > 0", name="positive_statistic_horizon"),
        CheckConstraint("sample_size > 0", name="positive_event_sample_size"),
        CheckConstraint(
            "positive_probability >= 0 AND positive_probability <= 1",
            name="valid_positive_probability",
        ),
        CheckConstraint(
            "win_rate >= 0 AND win_rate <= 1",
            name="valid_event_win_rate",
        ),
        CheckConstraint(
            "confidence_level > 0 AND confidence_level < 1",
            name="valid_event_statistic_confidence",
        ),
        UniqueConstraint(
            "run_id",
            "target_stock_id",
            "horizon_days",
            name="uq_event_statistics_run_target_horizon",
        ),
        Index(
            "ix_event_statistics_run_horizon",
            "run_id",
            "horizon_days",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("event_study_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"),
        index=True,
        nullable=False,
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_probability: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    win_rate: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    average_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    median_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    return_stddev: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    best_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    worst_return: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    average_max_upside: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    best_max_upside: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    average_max_drawdown: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    worst_max_drawdown: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    meets_minimum: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence_level: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0.95"), nullable=False
    )
    positive_probability_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 10), nullable=True
    )
    positive_probability_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 10), nullable=True
    )
    win_rate_lower: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    win_rate_upper: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    average_return_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )
    average_return_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )

    run: Mapped[EventStudyRun] = relationship(back_populates="statistics")
