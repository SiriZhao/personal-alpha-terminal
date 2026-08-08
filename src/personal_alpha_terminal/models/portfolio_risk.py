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


class FxRate(Base):
    """Daily FX conversion: one base currency unit equals `rate` quote units."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        CheckConstraint("rate > 0", name="positive_fx_rate"),
        CheckConstraint(
            "base_currency <> quote_currency",
            name="distinct_fx_currencies",
        ),
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            "source",
            name="uq_fx_rate_pair_date_source",
        ),
        Index(
            "ix_fx_rates_pair_date",
            "base_currency",
            "quote_currency",
            "rate_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)


class PortfolioRiskRun(TimestampMixin, Base):
    """One persisted portfolio risk snapshot and optional stress tests."""

    __tablename__ = "portfolio_risk_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_portfolio_risk_run_status",
        ),
        Index("ix_portfolio_risk_runs_portfolio_created", "portfolio_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    benchmark_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    metrics: Mapped["PortfolioRiskMetric | None"] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )
    stress_results: Mapped[list["PortfolioStressResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class PortfolioRiskMetric(Base):
    """Historical risk measures and current exposure snapshots."""

    __tablename__ = "portfolio_risk_metrics"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_risk_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    annualized_return: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    annualized_volatility: Mapped[Decimal] = mapped_column(
        Numeric(18, 10),
        nullable=False,
    )
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    beta: Mapped[Decimal | None] = mapped_column(Numeric(18, 10), nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    industry_exposure: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    currency_exposure: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    position_weights: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    position_risks: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    equity_curve: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    drawdown_curve: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)

    run: Mapped[PortfolioRiskRun] = relationship(back_populates="metrics")


class PortfolioStressResult(Base):
    """Static market-plus-FX scenario and contribution audit trail."""

    __tablename__ = "portfolio_stress_results"
    __table_args__ = (
        CheckConstraint(
            "uncovered_weight >= 0 AND uncovered_weight <= 1",
            name="valid_stress_uncovered_weight",
        ),
        UniqueConstraint(
            "run_id",
            "scenario_name",
            name="uq_portfolio_stress_run_scenario",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_risk_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_name: Mapped[str] = mapped_column(String(128), nullable=False)
    benchmark_shock: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    currency_shocks: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    stressed_value: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    pnl_amount: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    pnl_percent: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    uncovered_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    position_impacts: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )

    run: Mapped[PortfolioRiskRun] = relationship(back_populates="stress_results")
