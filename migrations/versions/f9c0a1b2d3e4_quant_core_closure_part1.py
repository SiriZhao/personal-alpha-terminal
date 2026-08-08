"""Quant core closure part 1 contracts.

Revision ID: f9c0a1b2d3e4
Revises: b8a2d6f4c901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from personal_alpha_terminal.models.quant_core_closure import (
    DelistingHistory,
    ListingHistory,
    ModelApprovalRecord,
    PITTotalReturnPointRecord,
    SymbolAlias,
    TradingStatus,
    UniverseDefinition,
    UniverseMembership,
)

revision: str = "f9c0a1b2d3e4"
down_revision: str | None = "b8a2d6f4c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    SymbolAlias.__table__,
    ListingHistory.__table__,
    DelistingHistory.__table__,
    UniverseDefinition.__table__,
    UniverseMembership.__table__,
    TradingStatus.__table__,
    PITTotalReturnPointRecord.__table__,
    ModelApprovalRecord.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in NEW_TABLES:
        table.create(bind=bind, checkfirst=True)

    with op.batch_alter_table("security_master") as batch:
        batch.drop_constraint("uq_stocks_exchange_symbol", type_="unique")
        batch.create_index("ix_security_master_exchange_symbol", ["exchange", "symbol"])

    with op.batch_alter_table("provider_capabilities") as batch:
        batch.add_column(sa.Column("fields", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("earliest_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("latest_date", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "adjustment_semantics",
                sa.String(64),
                nullable=False,
                server_default="unadjusted_raw",
            )
        )
        batch.add_column(
            sa.Column(
                "availability_status",
                sa.String(24),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("market_universe_snapshots") as batch:
        batch.add_column(sa.Column("definition_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("version_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("data_version", sa.String(64), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column(
                "certification_status",
                sa.String(32),
                nullable=False,
                server_default="NOT_VALIDATED",
            )
        )
        batch.create_foreign_key(
            "fk_market_universe_snapshot_definition",
            "universe_definitions",
            ["definition_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("corporate_actions") as batch:
        batch.drop_constraint("valid_corporate_action_type", type_="check")
        batch.add_column(
            sa.Column("action_id", sa.String(128), nullable=False, server_default="legacy")
        )
        batch.add_column(
            sa.Column("revision_id", sa.String(128), nullable=False, server_default="legacy-v1")
        )
        batch.add_column(sa.Column("details", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_check_constraint(
            "valid_corporate_action_type",
            "action_type IN ('cash_dividend','stock_dividend','split','reverse_split',"
            "'merger_cash','merger_stock','spin_off','rights','delisting','symbol_change',"
            "'adr_ratio_change')",
        )
        batch.create_unique_constraint(
            "uq_corporate_action_revision", ["action_id", "revision_id", "provider"]
        )
    op.execute(
        "UPDATE corporate_actions SET action_id = 'legacy-' || id "
        "WHERE action_id = 'legacy'"
    )

    with op.batch_alter_table("pit_total_return_versions") as batch:
        batch.add_column(sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "adjustment_policy",
                sa.String(64),
                nullable=False,
                server_default="point_in_time_total_return_v1",
            )
        )
        batch.add_column(
            sa.Column("corporate_action_ledger_hash", sa.String(64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "certification_status",
                sa.String(32),
                nullable=False,
                server_default="NOT_VALIDATED",
            )
        )
    with op.batch_alter_table("quant_decision_runs") as batch:
        batch.alter_column(
            "model_version",
            existing_type=sa.String(32),
            type_=sa.String(128),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("quant_decision_runs") as batch:
        batch.alter_column(
            "model_version",
            existing_type=sa.String(128),
            type_=sa.String(32),
            existing_nullable=False,
        )
    with op.batch_alter_table("pit_total_return_versions") as batch:
        batch.drop_column("certification_status")
        batch.drop_column("corporate_action_ledger_hash")
        batch.drop_column("adjustment_policy")
        batch.drop_column("data_cutoff")
    with op.batch_alter_table("corporate_actions") as batch:
        batch.drop_constraint("uq_corporate_action_revision", type_="unique")
        batch.drop_constraint("valid_corporate_action_type", type_="check")
        batch.create_check_constraint(
            "valid_corporate_action_type",
            "action_type IN ('cash_dividend','split','reverse_split','rights','delisting',"
            "'symbol_change')",
        )
        batch.drop_column("details")
        batch.drop_column("revision_id")
        batch.drop_column("action_id")
    with op.batch_alter_table("market_universe_snapshots") as batch:
        batch.drop_constraint("fk_market_universe_snapshot_definition", type_="foreignkey")
        for name in (
            "certification_status",
            "content_hash",
            "data_version",
            "version_id",
            "definition_id",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("provider_capabilities") as batch:
        for name in (
            "verified_at",
            "availability_status",
            "adjustment_semantics",
            "latest_date",
            "earliest_date",
            "fields",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("security_master") as batch:
        batch.drop_index("ix_security_master_exchange_symbol")
        batch.create_unique_constraint("uq_stocks_exchange_symbol", ["exchange", "symbol"])
    for table in reversed(NEW_TABLES):
        table.drop(bind=op.get_bind(), checkfirst=True)
