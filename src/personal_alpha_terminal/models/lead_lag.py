from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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


class LeadLagAnalysisRun(TimestampMixin, Base):
    """One reproducible lead-lag search over a selected asset universe."""

    __tablename__ = "lead_lag_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_lead_lag_status",
        ),
        CheckConstraint("maximum_lag_days > 0", name="positive_lead_lag_max_lag"),
        CheckConstraint(
            "minimum_observations >= 10",
            name="valid_lead_lag_minimum_observations",
        ),
        CheckConstraint("fdr_alpha > 0 AND fdr_alpha < 1", name="valid_lead_lag_fdr"),
        CheckConstraint(
            "minimum_abs_correlation >= 0 AND minimum_abs_correlation <= 1",
            name="valid_lead_lag_correlation_threshold",
        ),
        Index("ix_lead_lag_runs_end_created", "end_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    maximum_lag_days: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    fdr_alpha: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    minimum_abs_correlation: Mapped[Decimal] = mapped_column(
        Numeric(8, 6),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    pair_results: Mapped[list["LeadLagPairResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class LeadLagPairResult(Base):
    """The selected response lag and corrected evidence for one directed pair."""

    __tablename__ = "lead_lag_pair_results"
    __table_args__ = (
        CheckConstraint("best_lag_days > 0", name="positive_lead_lag_best_lag"),
        CheckConstraint(
            "cross_correlation >= -1 AND cross_correlation <= 1",
            name="valid_lead_lag_cross_correlation",
        ),
        CheckConstraint(
            "raw_p_value >= 0 AND raw_p_value <= 1",
            name="valid_lead_lag_raw_p",
        ),
        CheckConstraint(
            "lag_adjusted_p_value >= 0 AND lag_adjusted_p_value <= 1",
            name="valid_lead_lag_adjusted_p",
        ),
        CheckConstraint("q_value >= 0 AND q_value <= 1", name="valid_lead_lag_q"),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="valid_lead_lag_confidence",
        ),
        CheckConstraint("sample_size >= 10", name="valid_lead_lag_pair_sample"),
        UniqueConstraint(
            "run_id",
            "source_stock_id",
            "target_stock_id",
            name="uq_lead_lag_pair_run_direction",
        ),
        Index(
            "ix_lead_lag_pair_run_significant_confidence",
            "run_id",
            "is_significant",
            "confidence_score",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("lead_lag_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    target_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    best_lag_days: Mapped[int] = mapped_column(Integer, nullable=False)
    cross_correlation: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    granger_f_statistic: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    raw_p_value: Mapped[Decimal] = mapped_column(Numeric(18, 16), nullable=False)
    lag_adjusted_p_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 16),
        nullable=False,
    )
    q_value: Mapped[Decimal] = mapped_column(Numeric(18, 16), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(18, 16), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_significant: Mapped[bool] = mapped_column(Boolean, nullable=False)

    run: Mapped[LeadLagAnalysisRun] = relationship(back_populates="pair_results")
    metrics: Mapped[list["LeadLagMetric"]] = relationship(
        back_populates="pair_result",
        cascade="all, delete-orphan",
    )


class LeadLagMetric(Base):
    """Raw cross-correlation and Granger F-test evidence for one candidate lag."""

    __tablename__ = "lead_lag_metrics"
    __table_args__ = (
        CheckConstraint("lag_days > 0", name="positive_lead_lag_metric_lag"),
        CheckConstraint(
            "cross_correlation >= -1 AND cross_correlation <= 1",
            name="valid_lead_lag_metric_correlation",
        ),
        CheckConstraint(
            "granger_p_value >= 0 AND granger_p_value <= 1",
            name="valid_lead_lag_metric_p",
        ),
        CheckConstraint("sample_size >= 2", name="valid_lead_lag_metric_sample"),
        UniqueConstraint(
            "pair_result_id",
            "lag_days",
            name="uq_lead_lag_metric_pair_lag",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    pair_result_id: Mapped[int] = mapped_column(
        ForeignKey("lead_lag_pair_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False)
    cross_correlation: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    granger_f_statistic: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    granger_p_value: Mapped[Decimal] = mapped_column(Numeric(18, 16), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    pair_result: Mapped[LeadLagPairResult] = relationship(back_populates="metrics")
