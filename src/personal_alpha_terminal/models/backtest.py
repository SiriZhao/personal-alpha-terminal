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


class BacktestRun(TimestampMixin, Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_backtest_market"),
        CheckConstraint(
            "rebalance_frequency IN ('daily', 'monthly', 'quarterly')",
            name="valid_backtest_frequency",
        ),
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="valid_backtest_status",
        ),
        CheckConstraint("initial_capital > 0", name="positive_backtest_capital"),
        Index("ix_backtest_runs_market_end", "market", "end_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    rebalance_frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validation_issues: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    daily_results: Mapped[list["BacktestDailyResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    rebalances: Mapped[list["BacktestRebalance"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    summary: Mapped["BacktestSummaryMetric | None"] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class BacktestDailyResult(Base):
    __tablename__ = "backtest_daily_results"
    __table_args__ = (
        CheckConstraint("nav > 0", name="positive_backtest_daily_nav"),
        CheckConstraint("daily_return > -1", name="valid_backtest_daily_return"),
        CheckConstraint(
            "drawdown >= -1 AND drawdown <= 0",
            name="valid_backtest_daily_drawdown",
        ),
        CheckConstraint(
            "gross_exposure >= 0 AND gross_exposure <= 1.000000001",
            name="valid_backtest_daily_exposure",
        ),
        UniqueConstraint("run_id", "trade_date", name="uq_backtest_daily_run_date"),
        Index("ix_backtest_daily_run_date", "run_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    nav: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    daily_return: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    gross_exposure: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)

    run: Mapped[BacktestRun] = relationship(back_populates="daily_results")


class BacktestRebalance(Base):
    __tablename__ = "backtest_rebalances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('executed', 'rejected')",
            name="valid_backtest_rebalance_status",
        ),
        CheckConstraint(
            "execution_date > signal_date",
            name="backtest_execution_after_signal",
        ),
        CheckConstraint(
            "turnover >= 0 AND transaction_cost >= 0",
            name="nonnegative_backtest_trading_values",
        ),
        CheckConstraint(
            "nav_before > 0 AND nav_after > 0",
            name="positive_backtest_rebalance_nav",
        ),
        UniqueConstraint(
            "run_id",
            "signal_date",
            "execution_date",
            name="uq_backtest_rebalance_run_dates",
        ),
        Index("ix_backtest_rebalance_run_execution", "run_id", "execution_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    turnover: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    transaction_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    nav_before: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    nav_after: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    target_weights: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[BacktestRun] = relationship(back_populates="rebalances")


class BacktestSummaryMetric(Base):
    __tablename__ = "backtest_summary_metrics"
    __table_args__ = (
        CheckConstraint("total_return > -1", name="valid_backtest_total_return"),
        CheckConstraint(
            "annualized_volatility >= 0",
            name="nonnegative_backtest_volatility",
        ),
        CheckConstraint(
            "maximum_drawdown >= -1 AND maximum_drawdown <= 0",
            name="valid_backtest_maximum_drawdown",
        ),
        CheckConstraint(
            "period_win_rate IS NULL OR (period_win_rate >= 0 AND period_win_rate <= 1)",
            name="valid_backtest_period_win_rate",
        ),
        CheckConstraint(
            "total_turnover >= 0 AND average_turnover >= 0 AND total_transaction_cost >= 0",
            name="nonnegative_backtest_summary_values",
        ),
        UniqueConstraint("run_id", name="uq_backtest_summary_run"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_return: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    annualized_return: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    annualized_volatility: Mapped[Decimal] = mapped_column(
        Numeric(18, 12),
        nullable=False,
    )
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10),
        nullable=True,
    )
    sortino_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10),
        nullable=True,
    )
    maximum_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    period_win_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    period_profit_loss_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10),
        nullable=True,
    )
    total_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    average_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    total_transaction_cost: Mapped[Decimal] = mapped_column(
        Numeric(24, 8),
        nullable=False,
    )
    annual_returns: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)

    run: Mapped[BacktestRun] = relationship(back_populates="summary")
