"""add backtest laboratory tables

Revision ID: d4e1c7a9b2f0
Revises: 8b31a4f2d9c0
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e1c7a9b2f0"
down_revision: str | None = "8b31a4f2d9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("rebalance_frequency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("initial_capital", sa.Numeric(24, 6), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "market IN ('A', 'HK', 'US')",
            name=op.f("ck_backtest_runs_valid_backtest_market"),
        ),
        sa.CheckConstraint(
            "rebalance_frequency IN ('daily', 'monthly', 'quarterly')",
            name=op.f("ck_backtest_runs_valid_backtest_frequency"),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name=op.f("ck_backtest_runs_valid_backtest_status"),
        ),
        sa.CheckConstraint(
            "initial_capital > 0",
            name=op.f("ck_backtest_runs_positive_backtest_capital"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    op.create_index(
        "ix_backtest_runs_market_end",
        "backtest_runs",
        ["market", "end_date", "created_at"],
        unique=False,
    )
    op.create_table(
        "backtest_daily_results",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("daily_return", sa.Numeric(18, 12), nullable=False),
        sa.Column("drawdown", sa.Numeric(18, 12), nullable=False),
        sa.Column("gross_exposure", sa.Numeric(18, 12), nullable=False),
        sa.Column("cash", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint(
            "nav > 0",
            name=op.f("ck_backtest_daily_results_positive_backtest_daily_nav"),
        ),
        sa.CheckConstraint(
            "daily_return > -1",
            name=op.f("ck_backtest_daily_results_valid_backtest_daily_return"),
        ),
        sa.CheckConstraint(
            "drawdown >= -1 AND drawdown <= 0",
            name=op.f("ck_backtest_daily_results_valid_backtest_daily_drawdown"),
        ),
        sa.CheckConstraint(
            "gross_exposure >= 0 AND gross_exposure <= 1.000000001",
            name=op.f("ck_backtest_daily_results_valid_backtest_daily_exposure"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_daily_results_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_daily_results")),
        sa.UniqueConstraint(
            "run_id",
            "trade_date",
            name="uq_backtest_daily_run_date",
        ),
    )
    op.create_index(
        "ix_backtest_daily_run_date",
        "backtest_daily_results",
        ["run_id", "trade_date"],
        unique=False,
    )
    op.create_table(
        "backtest_rebalances",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("turnover", sa.Numeric(18, 12), nullable=False),
        sa.Column("transaction_cost", sa.Numeric(24, 8), nullable=False),
        sa.Column("nav_before", sa.Numeric(24, 8), nullable=False),
        sa.Column("nav_after", sa.Numeric(24, 8), nullable=False),
        sa.Column("target_weights", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('executed', 'rejected')",
            name=op.f("ck_backtest_rebalances_valid_backtest_rebalance_status"),
        ),
        sa.CheckConstraint(
            "execution_date > signal_date",
            name=op.f("ck_backtest_rebalances_backtest_execution_after_signal"),
        ),
        sa.CheckConstraint(
            "turnover >= 0 AND transaction_cost >= 0",
            name=op.f("ck_backtest_rebalances_nonnegative_backtest_trading_values"),
        ),
        sa.CheckConstraint(
            "nav_before > 0 AND nav_after > 0",
            name=op.f("ck_backtest_rebalances_positive_backtest_rebalance_nav"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_rebalances_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_rebalances")),
        sa.UniqueConstraint(
            "run_id",
            "signal_date",
            "execution_date",
            name="uq_backtest_rebalance_run_dates",
        ),
    )
    op.create_index(
        "ix_backtest_rebalance_run_execution",
        "backtest_rebalances",
        ["run_id", "execution_date"],
        unique=False,
    )
    op.create_table(
        "backtest_summary_metrics",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("total_return", sa.Numeric(18, 12), nullable=False),
        sa.Column("annualized_return", sa.Numeric(18, 12), nullable=False),
        sa.Column("annualized_volatility", sa.Numeric(18, 12), nullable=False),
        sa.Column("sharpe_ratio", sa.Numeric(18, 10), nullable=True),
        sa.Column("sortino_ratio", sa.Numeric(18, 10), nullable=True),
        sa.Column("maximum_drawdown", sa.Numeric(18, 12), nullable=False),
        sa.Column("period_win_rate", sa.Numeric(18, 12), nullable=True),
        sa.Column("period_profit_loss_ratio", sa.Numeric(18, 10), nullable=True),
        sa.Column("total_turnover", sa.Numeric(18, 10), nullable=False),
        sa.Column("average_turnover", sa.Numeric(18, 10), nullable=False),
        sa.Column("total_transaction_cost", sa.Numeric(24, 8), nullable=False),
        sa.Column("annual_returns", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "total_return > -1",
            name=op.f("ck_backtest_summary_metrics_valid_backtest_total_return"),
        ),
        sa.CheckConstraint(
            "annualized_volatility >= 0",
            name=op.f("ck_backtest_summary_metrics_nonnegative_backtest_volatility"),
        ),
        sa.CheckConstraint(
            "maximum_drawdown >= -1 AND maximum_drawdown <= 0",
            name=op.f("ck_backtest_summary_metrics_valid_backtest_maximum_drawdown"),
        ),
        sa.CheckConstraint(
            "period_win_rate IS NULL OR (period_win_rate >= 0 AND period_win_rate <= 1)",
            name=op.f("ck_backtest_summary_metrics_valid_backtest_period_win_rate"),
        ),
        sa.CheckConstraint(
            "total_turnover >= 0 AND average_turnover >= 0 AND total_transaction_cost >= 0",
            name=op.f("ck_backtest_summary_metrics_nonnegative_backtest_summary_values"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name=op.f("fk_backtest_summary_metrics_run_id_backtest_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_summary_metrics")),
        sa.UniqueConstraint("run_id", name="uq_backtest_summary_run"),
    )


def downgrade() -> None:
    op.drop_table("backtest_summary_metrics")
    op.drop_index(
        "ix_backtest_rebalance_run_execution",
        table_name="backtest_rebalances",
    )
    op.drop_table("backtest_rebalances")
    op.drop_index(
        "ix_backtest_daily_run_date",
        table_name="backtest_daily_results",
    )
    op.drop_table("backtest_daily_results")
    op.drop_index("ix_backtest_runs_market_end", table_name="backtest_runs")
    op.drop_table("backtest_runs")
