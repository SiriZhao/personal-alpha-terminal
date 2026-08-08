"""add production security master and point-in-time market-data contracts

Revision ID: 7f2c1d9a6b40
Revises: 4d9e8a7c6b51
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f2c1d9a6b40"
down_revision: str | None = "4d9e8a7c6b51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_legacy_market_data_empty() -> None:
    connection = op.get_bind()
    tables = (
        "stocks",
        "market_universe_members",
        "exchange_sessions",
        "corporate_actions",
    )
    populated = [
        table
        for table in tables
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    ]
    if populated:
        raise RuntimeError(
            "production market-data migration requires empty legacy contract tables; "
            "export and re-certify them before migration: " + ", ".join(populated)
        )


def _legacy_action_type_constraint_name() -> str:
    # At this exact historical revision the table has one and only one check:
    # the action-type contract.  PostgreSQL truncates the accidentally
    # double-prefixed legacy name and appends a hash, so an exact cross-dialect
    # name is not available.  Cardinality is safer than matching normalized SQL.
    matches = [
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("corporate_actions")
        if item.get("name")
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "expected exactly one known legacy corporate action type constraint; "
            f"found {matches!r}"
        )
    return op.f(matches[0])


def upgrade() -> None:
    _assert_legacy_market_data_empty()
    # PostgreSQL normalizes an ``IN (...)`` check into ``= ANY (ARRAY[...])``
    # during reflection, so matching reflected SQL text is not portable.  A
    # historical naming-convention interaction also produced a double-prefixed
    # name in some databases; accept only those two audited legacy names.
    action_type_constraint = _legacy_action_type_constraint_name()
    op.rename_table("stocks", "security_master")
    with op.batch_alter_table("security_master") as batch_op:
        batch_op.drop_constraint(op.f("ck_stocks_valid_asset_type"), type_="check")
        batch_op.alter_column("asset_type", new_column_name="security_type")
        batch_op.alter_column("list_date", new_column_name="listing_date")
        batch_op.alter_column("delist_date", new_column_name="delisting_date")
        batch_op.add_column(sa.Column("source", sa.String(64), nullable=False))
        batch_op.add_column(sa.Column("provider", sa.String(128), nullable=False))
        batch_op.add_column(
            sa.Column("available_time", sa.DateTime(timezone=True), nullable=False)
        )
        batch_op.add_column(
            sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=False)
        )
        batch_op.create_check_constraint(
            "valid_asset_type",
            "security_type IN ('stock', 'etf', 'index', 'commodity', 'bond', "
            "'money_fund', 'gold')",
        )
        batch_op.create_check_constraint(
            "valid_security_currency",
            "length(currency) = 3 AND currency = upper(currency)",
        )
        batch_op.create_check_constraint(
            "valid_security_lifecycle",
            "listing_date IS NULL OR delisting_date IS NULL "
            "OR listing_date <= delisting_date",
        )

    with op.batch_alter_table("market_universe_members") as batch_op:
        batch_op.add_column(sa.Column("reason", sa.String(128), nullable=False))

    with op.batch_alter_table("exchange_sessions") as batch_op:
        batch_op.add_column(sa.Column("open_time", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("close_time", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("timezone", sa.String(64), nullable=False))
        batch_op.create_check_constraint(
            "valid_exchange_session_times",
            "(is_open AND open_time IS NOT NULL AND close_time IS NOT NULL) OR "
            "(NOT is_open AND open_time IS NULL AND close_time IS NULL)",
        )
        batch_op.create_check_constraint(
            "valid_exchange_session_order",
            "open_time IS NULL OR close_time IS NULL OR open_time < close_time",
        )

    with op.batch_alter_table("corporate_actions") as batch_op:
        batch_op.drop_constraint(action_type_constraint, type_="check")
        batch_op.add_column(sa.Column("announcement_date", sa.Date(), nullable=False))
        batch_op.add_column(sa.Column("available_date", sa.Date(), nullable=False))
        batch_op.create_check_constraint(
            "valid_corporate_action_type",
            "action_type IN ('cash_dividend', 'split', 'reverse_split', 'rights', "
            "'delisting', 'symbol_change')",
        )
        batch_op.create_check_constraint(
            "valid_corporate_action_availability",
            "announcement_date <= available_date",
        )


def downgrade() -> None:
    with op.batch_alter_table("corporate_actions") as batch_op:
        batch_op.drop_constraint("valid_corporate_action_availability", type_="check")
        batch_op.drop_constraint("valid_corporate_action_type", type_="check")
        batch_op.drop_column("available_date")
        batch_op.drop_column("announcement_date")
        batch_op.create_check_constraint(
            "valid_corporate_action_type",
            "action_type IN ('cash_dividend', 'split', 'rights', 'delisting', "
            "'symbol_change')",
        )

    with op.batch_alter_table("exchange_sessions") as batch_op:
        batch_op.drop_constraint("valid_exchange_session_order", type_="check")
        batch_op.drop_constraint("valid_exchange_session_times", type_="check")
        batch_op.drop_column("timezone")
        batch_op.drop_column("close_time")
        batch_op.drop_column("open_time")

    with op.batch_alter_table("market_universe_members") as batch_op:
        batch_op.drop_column("reason")

    with op.batch_alter_table("security_master") as batch_op:
        batch_op.drop_constraint("valid_asset_type", type_="check")
        batch_op.drop_constraint("valid_security_lifecycle", type_="check")
        batch_op.drop_constraint("valid_security_currency", type_="check")
        batch_op.drop_column("ingested_time")
        batch_op.drop_column("available_time")
        batch_op.drop_column("provider")
        batch_op.drop_column("source")
        batch_op.alter_column("delisting_date", new_column_name="delist_date")
        batch_op.alter_column("listing_date", new_column_name="list_date")
        batch_op.alter_column("security_type", new_column_name="asset_type")
        batch_op.create_check_constraint(
            op.f("ck_stocks_valid_asset_type"),
            "asset_type IN ('stock', 'etf', 'index', 'commodity', 'bond', "
            "'money_fund', 'gold')",
        )
    op.rename_table("security_master", "stocks")
