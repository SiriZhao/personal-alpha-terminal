"""add market data quality system

Revision ID: a72d4e9c1f30
Revises: c91b7e4a2d60
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a72d4e9c1f30"
down_revision: str | None = "c91b7e4a2d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prices",
        sa.Column("forward_adjusted_close", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "prices",
        sa.Column("backward_adjusted_close", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "prices",
        sa.Column(
            "provider",
            sa.String(128),
            server_default="legacy_unknown",
            nullable=False,
        ),
    )

    op.create_table(
        "market_universe_snapshots",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "market IN ('A', 'HK', 'US')",
            name="ck_market_universe_snapshots_valid_universe_market",
        ),
        sa.UniqueConstraint(
            "market",
            "as_of_date",
            "source",
            "provider",
            name="uq_universe_snapshot_lineage",
        ),
    )
    op.create_index(
        "ix_universe_snapshot_market_date",
        "market_universe_snapshots",
        ["market", "as_of_date"],
    )

    op.create_table(
        "market_universe_members",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "snapshot_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("market_universe_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment", sa.String(32), nullable=False),
        sa.Column("size_bucket", sa.String(16), nullable=False),
        sa.Column("listing_age_bucket", sa.String(16), nullable=False),
        sa.Column("market_cap", sa.Numeric(24, 4), nullable=True),
        sa.UniqueConstraint(
            "snapshot_id",
            "stock_id",
            name="uq_universe_member_stock",
        ),
    )
    op.create_index(
        "ix_universe_member_segment",
        "market_universe_members",
        ["snapshot_id", "segment"],
    )

    op.create_table(
        "exchange_sessions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "exchange",
            "session_date",
            "source",
            "provider",
            name="uq_exchange_session_lineage",
        ),
    )
    op.create_index(
        "ix_exchange_sessions_date",
        "exchange_sessions",
        ["exchange", "session_date"],
    )

    op.create_table(
        "corporate_actions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("split_ratio", sa.Numeric(20, 10), nullable=True),
        sa.Column("cash_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('cash_dividend', 'split', 'rights', 'delisting', 'symbol_change')",
            name="ck_corporate_actions_valid_corporate_action_type",
        ),
        sa.UniqueConstraint(
            "stock_id",
            "action_type",
            "effective_date",
            "source",
            "provider",
            name="uq_corporate_action_lineage",
        ),
    )
    op.create_index(
        "ix_corporate_actions_stock_date",
        "corporate_actions",
        ["stock_id", "effective_date"],
    )
    op.create_index(
        "ix_corporate_actions_available",
        "corporate_actions",
        ["stock_id", "available_time"],
    )

    op.create_table(
        "market_data_quality_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("history_start", sa.Date(), nullable=False),
        sa.Column("history_end", sa.Date(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("aggregate_metrics", sa.JSON(), nullable=False),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'blocked')",
            name="ck_market_data_quality_runs_valid_market_data_quality_status",
        ),
    )
    op.create_index(
        "ix_market_data_quality_runs_created",
        "market_data_quality_runs",
        ["created_at"],
    )

    op.create_table(
        "market_data_quality_results",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("market_data_quality_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stock_id",
            sa.Integer(),
            sa.ForeignKey("stocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment", sa.String(32), nullable=False),
        sa.Column("expected_sessions", sa.Integer(), nullable=False),
        sa.Column("observed_sessions", sa.Integer(), nullable=False),
        sa.Column("missing_sessions", sa.Integer(), nullable=False),
        sa.Column("missing_rate", sa.Numeric(12, 10), nullable=False),
        sa.Column("anomalous_observations", sa.Integer(), nullable=False),
        sa.Column("anomaly_rate", sa.Numeric(12, 10), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "stock_id", name="uq_market_quality_run_stock"),
    )
    op.create_index(
        "ix_market_quality_results_status",
        "market_data_quality_results",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_quality_results_status",
        table_name="market_data_quality_results",
    )
    op.drop_table("market_data_quality_results")
    op.drop_index(
        "ix_market_data_quality_runs_created",
        table_name="market_data_quality_runs",
    )
    op.drop_table("market_data_quality_runs")
    op.drop_index("ix_corporate_actions_available", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_stock_date", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_exchange_sessions_date", table_name="exchange_sessions")
    op.drop_table("exchange_sessions")
    op.drop_index("ix_universe_member_segment", table_name="market_universe_members")
    op.drop_table("market_universe_members")
    op.drop_index(
        "ix_universe_snapshot_market_date",
        table_name="market_universe_snapshots",
    )
    op.drop_table("market_universe_snapshots")
    op.drop_column("prices", "provider")
    op.drop_column("prices", "backward_adjusted_close")
    op.drop_column("prices", "forward_adjusted_close")
