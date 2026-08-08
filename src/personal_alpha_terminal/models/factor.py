from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from personal_alpha_terminal.models.market import Financial


class FinancialPerShareMetric(Base):
    """Point-in-time per-share fields extending one existing financial record."""

    __tablename__ = "financial_per_share_metrics"
    __table_args__ = (
        CheckConstraint(
            "shares_outstanding IS NULL OR shares_outstanding > 0",
            name="positive_factor_shares_outstanding",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    financial_id: Mapped[int] = mapped_column(
        ForeignKey("financials.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    eps: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    diluted_eps: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    shares_outstanding: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 4),
        nullable=True,
    )

    financial: Mapped["Financial"] = relationship(back_populates="per_share_metric")


class FactorResearchRun(TimestampMixin, Base):
    """A current factor snapshot or point-in-time historical backtest."""

    __tablename__ = "factor_research_runs"
    __table_args__ = (
        CheckConstraint(
            "analysis_type IN ('snapshot', 'backtest')",
            name="valid_factor_analysis_type",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_factor_run_status",
        ),
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_factor_market"),
        Index("ix_factor_runs_type_created", "analysis_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    analysis_type: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scores: Mapped[list["FactorScore"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    periods: Mapped[list["FactorBacktestPeriod"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    summary: Mapped["FactorBacktestSummary | None"] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class FactorScore(Base):
    """Raw values, directional percentiles, category scores, and composite score."""

    __tablename__ = "factor_scores"
    __table_args__ = (
        CheckConstraint(
            "factor_score >= 0 AND factor_score <= 100",
            name="valid_composite_factor_score",
        ),
        CheckConstraint(
            "category_coverage >= 1 AND category_coverage <= 5",
            name="valid_factor_category_coverage",
        ),
        UniqueConstraint(
            "run_id",
            "as_of_date",
            "stock_id",
            name="uq_factor_scores_run_date_stock",
        ),
        Index("ix_factor_scores_run_date_score", "run_id", "as_of_date", "factor_score"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("factor_research_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    raw_factors: Mapped[dict[str, float | None]] = mapped_column(JSON, nullable=False)
    normalized_factors: Mapped[dict[str, float | None]] = mapped_column(
        JSON,
        nullable=False,
    )
    category_scores: Mapped[dict[str, float | None]] = mapped_column(
        JSON,
        nullable=False,
    )
    factor_score: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    category_coverage: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[FactorResearchRun] = relationship(back_populates="scores")


class FactorBacktestPeriod(Base):
    """One non-overlapping rebalance period and its selected portfolio return."""

    __tablename__ = "factor_backtest_periods"
    __table_args__ = (
        CheckConstraint("selected_count > 0", name="positive_factor_selected_count"),
        UniqueConstraint(
            "run_id",
            "rebalance_date",
            name="uq_factor_backtest_run_rebalance",
        ),
        Index("ix_factor_backtest_period_run_date", "run_id", "rebalance_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("factor_research_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rebalance_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    selected_stock_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    selected_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    portfolio_return: Mapped[Decimal] = mapped_column(Numeric(16, 10), nullable=False)
    benchmark_return: Mapped[Decimal] = mapped_column(Numeric(16, 10), nullable=False)
    excess_return: Mapped[Decimal] = mapped_column(Numeric(16, 10), nullable=False)

    run: Mapped[FactorResearchRun] = relationship(back_populates="periods")


class FactorBacktestSummary(Base):
    """Aggregate performance and risk for one factor backtest."""

    __tablename__ = "factor_backtest_summaries"
    __table_args__ = (CheckConstraint("period_count > 0", name="positive_factor_period_count"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("factor_research_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    period_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    benchmark_cumulative_return: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    annualized_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    annualized_volatility: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    excess_hit_rate: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)

    run: Mapped[FactorResearchRun] = relationship(back_populates="summary")
