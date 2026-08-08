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


class MarketRegimeRun(TimestampMixin, Base):
    """One reproducible market-regime classification run."""

    __tablename__ = "market_regime_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_market_regime_run_status",
        ),
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_regime_market"),
        CheckConstraint(
            "calibration_status IN ('calibrated', 'score_only')",
            name="valid_regime_calibration_status",
        ),
        Index("ix_market_regime_runs_end_created", "end_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    vix_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    rate_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    dollar_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    benchmark_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    calibration_status: Mapped[str] = mapped_column(
        String(16), default="score_only", nullable=False
    )
    calibration_method: Mapped[str] = mapped_column(
        String(64), default="none", nullable=False
    )
    calibration_observation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    brier_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 16), nullable=True)
    raw_score_brier: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16), nullable=True
    )
    baseline_brier: Mapped[Decimal | None] = mapped_column(Numeric(18, 16), nullable=True)
    calibration_curve: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    calibration_reasons: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    observations: Mapped[list["MarketRegimeObservation"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class MarketRegimeObservation(Base):
    """Daily features, normalized scores, and optional validated probabilities."""

    __tablename__ = "market_regime_observations"
    __table_args__ = (
        CheckConstraint(
            "regime IN ('risk_on', 'risk_off', 'neutral')",
            name="valid_market_regime",
        ),
        CheckConstraint(
            "risk_on_score >= 0 AND risk_on_score <= 1",
            name="valid_risk_on_score",
        ),
        CheckConstraint(
            "risk_off_score >= 0 AND risk_off_score <= 1",
            name="valid_risk_off_score",
        ),
        CheckConstraint(
            "neutral_score >= 0 AND neutral_score <= 1",
            name="valid_neutral_score",
        ),
        CheckConstraint(
            "(risk_on_probability IS NULL AND risk_off_probability IS NULL AND "
            "neutral_probability IS NULL) OR "
            "(risk_on_probability >= 0 AND risk_on_probability <= 1 AND "
            "risk_off_probability >= 0 AND risk_off_probability <= 1 AND "
            "neutral_probability >= 0 AND neutral_probability <= 1)",
            name="valid_optional_regime_probabilities",
        ),
        CheckConstraint(
            "breadth_constituent_count > 0",
            name="positive_regime_breadth_count",
        ),
        UniqueConstraint("run_id", "as_of_date", name="uq_market_regime_run_date"),
        Index("ix_market_regime_observations_run_date", "run_id", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("market_regime_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    regime: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_on_score: Mapped[Decimal] = mapped_column(
        Numeric(18, 16),
        nullable=False,
    )
    risk_off_score: Mapped[Decimal] = mapped_column(
        Numeric(18, 16),
        nullable=False,
    )
    neutral_score: Mapped[Decimal] = mapped_column(
        Numeric(18, 16),
        nullable=False,
    )
    risk_on_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16), nullable=True
    )
    risk_off_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16), nullable=True
    )
    neutral_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 16), nullable=True
    )
    composite_score: Mapped[Decimal] = mapped_column(Numeric(16, 10), nullable=False)
    breadth_constituent_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_values: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    feature_zscores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    feature_contributions: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
    )

    run: Mapped[MarketRegimeRun] = relationship(back_populates="observations")
