"""add US quant production data, governance, and manual rebalance records

Revision ID: 3b7e2d9f4a10
Revises: 91a4d8c2e7f0
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b7e2d9f4a10"
down_revision: str | None = "91a4d8c2e7f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.BigInteger:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "security_identifier_history",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("identifier_type", sa.String(16), nullable=False),
        sa.Column("identifier_value", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "identifier_type IN ('ticker', 'cusip', 'isin', 'figi')",
            name="valid_security_identifier_type",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from <= valid_to", name="valid_security_identifier_period"
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "stock_id",
            "identifier_type",
            "identifier_value",
            "valid_from",
            "source",
            name="uq_security_identifier_vintage",
        ),
    )
    op.create_index(
        "ix_security_identifier_lookup",
        "security_identifier_history",
        ["identifier_type", "identifier_value"],
    )

    op.create_table(
        "fundamental_vintages",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False),
        sa.Column("filing_id", sa.String(128), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("publication_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_id", sa.String(128), nullable=False),
        sa.Column("is_restatement", sa.Boolean(), nullable=False),
        sa.Column("original_values", sa.JSON(), nullable=False),
        sa.Column("restated_values", sa.JSON(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_scale", sa.BigInteger(), nullable=False),
        sa.Column("accounting_standard", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "period_type IN ('annual', 'quarterly', 'ttm')",
            name="valid_fundamental_vintage_period_type",
        ),
        sa.CheckConstraint(
            "publication_time <= available_at AND available_at <= ingested_at",
            name="valid_fundamental_vintage_timestamps",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "stock_id", "filing_id", "revision_id", "source", name="uq_fundamental_filing_revision"
        ),
    )
    op.create_index(
        "ix_fundamental_vintage_pit",
        "fundamental_vintages",
        ["stock_id", "available_at", "fiscal_period_end"],
    )

    op.create_table(
        "pit_total_return_versions",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("version_id", sa.String(64), nullable=False, unique=True),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_pit_total_return_stock_asof", "pit_total_return_versions", ["stock_id", "as_of_time"]
    )

    op.create_table(
        "research_data_certifications",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("quality_run_id", _id(), nullable=False),
        sa.Column("universe_snapshot_id", _id(), nullable=True),
        sa.Column("allow_display", sa.Boolean(), nullable=False),
        sa.Column("allow_backtest", sa.Boolean(), nullable=False),
        sa.Column("allow_portfolio_decision", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('APPROVED', 'RESEARCH_ONLY', 'DEGRADED', 'BLOCKED')",
            name="valid_research_data_certification_status",
        ),
        sa.ForeignKeyConstraint(
            ["quality_run_id"], ["market_data_quality_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["universe_snapshot_id"], ["market_universe_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "market", "asset_type", "data_version", name="uq_research_data_certification_version"
        ),
    )
    op.create_index(
        "ix_research_data_certification_latest",
        "research_data_certifications",
        ["market", "asset_type", "created_at"],
    )
    op.create_index(
        "ix_research_data_certifications_quality_run_id",
        "research_data_certifications",
        ["quality_run_id"],
    )
    op.create_index(
        "ix_research_data_certifications_universe_snapshot_id",
        "research_data_certifications",
        ["universe_snapshot_id"],
    )

    op.create_table(
        "model_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("data_requirements", sa.JSON(), nullable=False),
        sa.Column("training_period", sa.JSON(), nullable=True),
        sa.Column("validation_period", sa.JSON(), nullable=True),
        sa.Column("test_period", sa.JSON(), nullable=True),
        sa.Column("hyperparameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("approval_level", sa.String(24), nullable=False),
        sa.Column("last_validation", sa.Date(), nullable=True),
        sa.Column("drift_status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('Experimental', 'Research', 'Paper Trading', 'Shadow', "
            "'Manual Pilot', 'Suspended', 'Retired')",
            name="valid_model_registry_status",
        ),
        sa.UniqueConstraint("model_id", "version", name="uq_model_registry_version"),
    )

    op.create_table(
        "backtest_run_manifests",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("run_id", _id(), nullable=False, unique=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column("data_snapshot", sa.String(64), nullable=False),
        sa.Column("universe_snapshot", sa.String(64), nullable=False),
        sa.Column("factor_version", sa.String(64), nullable=False),
        sa.Column("execution_model", sa.String(128), nullable=False),
        sa.Column("cost_model", sa.String(128), nullable=False),
        sa.Column("benchmark", sa.String(32), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "manual_rebalance_tickets",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("ticket_id", sa.String(96), nullable=False, unique=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("signal_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("earliest_execution_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_id", sa.String(64), nullable=False),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'partially_filled', 'completed', 'cancelled')",
            name="valid_manual_rebalance_status",
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_manual_rebalance_ticket_status", "manual_rebalance_tickets", ["status", "created_at"]
    )
    op.create_index(
        "ix_manual_rebalance_tickets_portfolio_id",
        "manual_rebalance_tickets",
        ["portfolio_id"],
    )

    op.create_table(
        "manual_rebalance_fills",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("ticket_id", _id(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("actual_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("actual_shares", sa.BigInteger(), nullable=False),
        sa.Column("fees", sa.Numeric(20, 6), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["manual_rebalance_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_manual_fill_ticket_time", "manual_rebalance_fills", ["ticket_id", "timestamp"]
    )
    op.create_index(
        "ix_manual_rebalance_fills_stock_id",
        "manual_rebalance_fills",
        ["stock_id"],
    )


def downgrade() -> None:
    op.drop_table("manual_rebalance_fills")
    op.drop_table("manual_rebalance_tickets")
    op.drop_table("backtest_run_manifests")
    op.drop_table("model_registry")
    op.drop_table("research_data_certifications")
    op.drop_table("pit_total_return_versions")
    op.drop_table("fundamental_vintages")
    op.drop_table("security_identifier_history")
