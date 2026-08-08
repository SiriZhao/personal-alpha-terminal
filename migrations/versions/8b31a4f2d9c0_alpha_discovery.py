"""add alpha discovery research tables

Revision ID: 8b31a4f2d9c0
Revises: 2cf3891f064c
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b31a4f2d9c0"
down_revision: str | None = "2cf3891f064c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alpha_discovery_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("split_dates", sa.JSON(), nullable=False),
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
            name=op.f("ck_alpha_discovery_runs_valid_alpha_market"),
        ),
        sa.CheckConstraint(
            "horizon_days > 0",
            name=op.f("ck_alpha_discovery_runs_positive_alpha_horizon"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_alpha_discovery_runs_valid_alpha_run_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alpha_discovery_runs")),
    )
    op.create_index(
        "ix_alpha_runs_market_end",
        "alpha_discovery_runs",
        ["market", "end_date", "created_at"],
        unique=False,
    )
    op.create_table(
        "alpha_factor_evaluations",
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
        sa.Column("factor_name", sa.String(length=96), nullable=False),
        sa.Column("split_name", sa.String(length=16), nullable=False),
        sa.Column("evaluation_axis", sa.String(length=24), nullable=False),
        sa.Column("date_count", sa.Integer(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("raw_mean_ic", sa.Numeric(precision=18, scale=12), nullable=True),
        sa.Column(
            "directional_mean_ic",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column("median_ic", sa.Numeric(precision=18, scale=12), nullable=True),
        sa.Column(
            "ic_standard_deviation",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "information_ratio",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "positive_ratio",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column("pearson_ic", sa.Numeric(precision=18, scale=12), nullable=True),
        sa.Column("p_value", sa.Numeric(precision=18, scale=16), nullable=True),
        sa.Column(
            "adjusted_p_value",
            sa.Numeric(precision=18, scale=16),
            nullable=True,
        ),
        sa.Column("significant", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "split_name IN ('full', 'train', 'validation', 'test')",
            name=op.f("ck_alpha_factor_evaluations_valid_alpha_factor_split"),
        ),
        sa.CheckConstraint(
            "evaluation_axis IN ('cross_sectional', 'time_series')",
            name=op.f("ck_alpha_factor_evaluations_valid_alpha_evaluation_axis"),
        ),
        sa.CheckConstraint(
            "date_count >= 0",
            name=op.f("ck_alpha_factor_evaluations_nonnegative_alpha_factor_dates"),
        ),
        sa.CheckConstraint(
            "observation_count >= 0",
            name=op.f("ck_alpha_factor_evaluations_nonnegative_alpha_observations"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 80",
            name=op.f("ck_alpha_factor_evaluations_valid_alpha_factor_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["alpha_discovery_runs.id"],
            name=op.f("fk_alpha_factor_evaluations_run_id_alpha_discovery_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alpha_factor_evaluations")),
        sa.UniqueConstraint(
            "run_id",
            "factor_name",
            "split_name",
            name="uq_alpha_factor_run_name_split",
        ),
    )
    op.create_index(
        "ix_alpha_factor_run_split_ic",
        "alpha_factor_evaluations",
        ["run_id", "split_name", "directional_mean_ic"],
        unique=False,
    )
    op.create_table(
        "alpha_combination_results",
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
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("train_ic", sa.Numeric(precision=18, scale=12), nullable=False),
        sa.Column("validation_ic", sa.Numeric(precision=18, scale=12), nullable=False),
        sa.Column("test_ic", sa.Numeric(precision=18, scale=12), nullable=True),
        sa.Column(
            "train_adjusted_p",
            sa.Numeric(precision=18, scale=16),
            nullable=True,
        ),
        sa.Column(
            "validation_adjusted_p",
            sa.Numeric(precision=18, scale=16),
            nullable=True,
        ),
        sa.Column(
            "test_adjusted_p",
            sa.Numeric(precision=18, scale=16),
            nullable=True,
        ),
        sa.Column(
            "train_long_short_return",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "validation_long_short_return",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "test_long_short_return",
            sa.Numeric(precision=18, scale=12),
            nullable=True,
        ),
        sa.Column(
            "maximum_pairwise_correlation",
            sa.Numeric(precision=18, scale=12),
            nullable=False,
        ),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("selection_reasons", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "rank > 0",
            name=op.f("ck_alpha_combination_results_positive_alpha_combination_rank"),
        ),
        sa.CheckConstraint(
            "status IN ('test_confirmed', 'test_not_confirmed')",
            name=op.f("ck_alpha_combination_results_valid_alpha_combination_status"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 80",
            name=op.f("ck_alpha_combination_results_valid_alpha_combo_confidence"),
        ),
        sa.CheckConstraint(
            "maximum_pairwise_correlation >= 0 AND maximum_pairwise_correlation <= 1",
            name=op.f("ck_alpha_combination_results_valid_alpha_combo_correlation"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["alpha_discovery_runs.id"],
            name=op.f("fk_alpha_combination_results_run_id_alpha_discovery_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alpha_combination_results")),
        sa.UniqueConstraint(
            "run_id",
            "rank",
            name="uq_alpha_combination_run_rank",
        ),
    )
    op.create_index(
        "ix_alpha_combination_run_status",
        "alpha_combination_results",
        ["run_id", "status", "confidence_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alpha_combination_run_status",
        table_name="alpha_combination_results",
    )
    op.drop_table("alpha_combination_results")
    op.drop_index(
        "ix_alpha_factor_run_split_ic",
        table_name="alpha_factor_evaluations",
    )
    op.drop_table("alpha_factor_evaluations")
    op.drop_index("ix_alpha_runs_market_end", table_name="alpha_discovery_runs")
    op.drop_table("alpha_discovery_runs")
