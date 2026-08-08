"""add daily quant pipeline audit tables

Revision ID: f3c8a1d7e5b2
Revises: b60d1a8e92c4
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a1d7e5b2"
down_revision: str | None = "b60d1a8e92c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_pipeline_runs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("report_path", sa.String(length=1024), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name=op.f("ck_daily_pipeline_runs_valid_daily_pipeline_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_pipeline_runs")),
    )
    op.create_index(
        "ix_daily_pipeline_runs_date_started",
        "daily_pipeline_runs",
        ["run_date", "start_time"],
        unique=False,
    )
    op.create_index(
        "ix_daily_pipeline_runs_status_started",
        "daily_pipeline_runs",
        ["status", "start_time"],
        unique=False,
    )
    op.create_table(
        "daily_task_runs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column(
            "pipeline_run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("task_name", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_daily_task_runs_nonnegative_daily_task_attempts"),
        ),
        sa.CheckConstraint(
            "max_attempts >= 1",
            name=op.f("ck_daily_task_runs_positive_daily_task_max_attempts"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name=op.f("ck_daily_task_runs_valid_daily_task_status"),
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["daily_pipeline_runs.id"],
            name=op.f("fk_daily_task_runs_pipeline_run_id_daily_pipeline_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_task_runs")),
        sa.UniqueConstraint(
            "pipeline_run_id",
            "task_name",
            name="uq_daily_task_runs_pipeline_task",
        ),
    )
    op.create_index(
        op.f("ix_daily_task_runs_pipeline_run_id"),
        "daily_task_runs",
        ["pipeline_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_task_runs_status_started",
        "daily_task_runs",
        ["status", "start_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_task_runs_status_started", table_name="daily_task_runs")
    op.drop_index(op.f("ix_daily_task_runs_pipeline_run_id"), table_name="daily_task_runs")
    op.drop_table("daily_task_runs")
    op.drop_index("ix_daily_pipeline_runs_status_started", table_name="daily_pipeline_runs")
    op.drop_index("ix_daily_pipeline_runs_date_started", table_name="daily_pipeline_runs")
    op.drop_table("daily_pipeline_runs")
