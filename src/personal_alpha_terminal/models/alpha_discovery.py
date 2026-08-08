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


class AlphaDiscoveryRun(TimestampMixin, Base):
    __tablename__ = "alpha_discovery_runs"
    __table_args__ = (
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_alpha_market"),
        CheckConstraint("horizon_days > 0", name="positive_alpha_horizon"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_alpha_run_status",
        ),
        Index("ix_alpha_runs_market_end", "market", "end_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    split_dates: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    evaluations: Mapped[list["AlphaFactorEvaluation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    combinations: Mapped[list["AlphaCombinationResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class AlphaFactorEvaluation(Base):
    __tablename__ = "alpha_factor_evaluations"
    __table_args__ = (
        CheckConstraint(
            "split_name IN ('full', 'train', 'validation', 'test')",
            name="valid_alpha_factor_split",
        ),
        CheckConstraint(
            "evaluation_axis IN ('cross_sectional', 'time_series')",
            name="valid_alpha_evaluation_axis",
        ),
        CheckConstraint("date_count >= 0", name="nonnegative_alpha_factor_dates"),
        CheckConstraint(
            "observation_count >= 0",
            name="nonnegative_alpha_observations",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 80",
            name="valid_alpha_factor_confidence",
        ),
        UniqueConstraint(
            "run_id",
            "factor_name",
            "split_name",
            name="uq_alpha_factor_run_name_split",
        ),
        Index(
            "ix_alpha_factor_run_split_ic",
            "run_id",
            "split_name",
            "directional_mean_ic",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("alpha_discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    factor_name: Mapped[str] = mapped_column(String(96), nullable=False)
    split_name: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluation_axis: Mapped[str] = mapped_column(String(24), nullable=False)
    date_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_mean_ic: Mapped[Decimal | None] = mapped_column(Numeric(18, 12), nullable=True)
    directional_mean_ic: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    median_ic: Mapped[Decimal | None] = mapped_column(Numeric(18, 12), nullable=True)
    ic_standard_deviation: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    information_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    positive_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    pearson_ic: Mapped[Decimal | None] = mapped_column(Numeric(18, 12), nullable=True)
    p_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 16), nullable=True)
    adjusted_p_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16),
        nullable=True,
    )
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[AlphaDiscoveryRun] = relationship(back_populates="evaluations")


class AlphaCombinationResult(Base):
    __tablename__ = "alpha_combination_results"
    __table_args__ = (
        CheckConstraint("rank > 0", name="positive_alpha_combination_rank"),
        CheckConstraint(
            "status IN ('test_confirmed', 'test_not_confirmed')",
            name="valid_alpha_combination_status",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 80",
            name="valid_alpha_combo_confidence",
        ),
        CheckConstraint(
            "maximum_pairwise_correlation >= 0 AND maximum_pairwise_correlation <= 1",
            name="valid_alpha_combo_correlation",
        ),
        UniqueConstraint(
            "run_id",
            "rank",
            name="uq_alpha_combination_run_rank",
        ),
        Index(
            "ix_alpha_combination_run_status",
            "run_id",
            "status",
            "confidence_score",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("alpha_discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    weights: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    train_ic: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    validation_ic: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    test_ic: Mapped[Decimal | None] = mapped_column(Numeric(18, 12), nullable=True)
    train_adjusted_p: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16),
        nullable=True,
    )
    validation_adjusted_p: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16),
        nullable=True,
    )
    test_adjusted_p: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16),
        nullable=True,
    )
    train_long_short_return: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    validation_long_short_return: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    test_long_short_return: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    maximum_pairwise_correlation: Mapped[Decimal] = mapped_column(
        Numeric(18, 12),
        nullable=False,
    )
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    selection_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    run: Mapped[AlphaDiscoveryRun] = relationship(back_populates="combinations")
