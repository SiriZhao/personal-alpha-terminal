"""add production portfolio management ledger

Revision ID: 0a7c9e4d2b61
Revises: f3c8a1d7e5b2
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a7c9e4d2b61"
down_revision: str | None = "f3c8a1d7e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ASSET_CHECK = "asset_type IN ('stock', 'etf', 'index', 'commodity')"
NEW_ASSET_CHECK = (
    "asset_type IN ('stock', 'etf', 'index', 'commodity', 'bond', 'money_fund', 'gold')"
)


def _replace_asset_check(expression: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("stocks", recreate="always") as batch_op:
            batch_op.drop_constraint("valid_asset_type", type_="check")
            batch_op.create_check_constraint("valid_asset_type", expression)
        return
    # The name was already expanded by the metadata naming convention in the
    # initial migration.  Mark it as formatted so Alembic does not apply the
    # convention a second time on PostgreSQL (which would produce
    # ``ck_stocks_ck_stocks_valid_asset_type``).
    op.drop_constraint(op.f("ck_stocks_valid_asset_type"), "stocks", type_="check")
    op.create_check_constraint("valid_asset_type", "stocks", expression)


def upgrade() -> None:
    _replace_asset_check(NEW_ASSET_CHECK)
    op.create_table(
        "portfolio_transactions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("transaction_type", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=True),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("cash_amount", sa.Numeric(24, 6), nullable=True),
        sa.Column("fee_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate_to_base", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "transaction_type IN ('buy', 'sell', 'dividend', 'fee', "
            "'deposit', 'withdrawal', 'split')",
            name=op.f("ck_portfolio_transactions_valid_portfolio_transaction_type"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name=op.f("ck_portfolio_transactions_positive_transaction_quantity"),
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price > 0",
            name=op.f("ck_portfolio_transactions_positive_transaction_price"),
        ),
        sa.CheckConstraint(
            "cash_amount IS NULL OR cash_amount > 0",
            name=op.f("ck_portfolio_transactions_positive_cash_amount"),
        ),
        sa.CheckConstraint(
            "fee_amount >= 0",
            name=op.f("ck_portfolio_transactions_nonnegative_transaction_fee"),
        ),
        sa.CheckConstraint(
            "fx_rate_to_base > 0",
            name=op.f("ck_portfolio_transactions_positive_transaction_fx_rate"),
        ),
        sa.CheckConstraint(
            "settlement_date >= trade_date",
            name=op.f("ck_portfolio_transactions_valid_transaction_settlement"),
        ),
        sa.CheckConstraint(
            "available_time >= event_time",
            name=op.f("ck_portfolio_transactions_valid_transaction_availability"),
        ),
        sa.CheckConstraint(
            "(transaction_type IN ('buy', 'sell') AND stock_id IS NOT NULL "
            "AND quantity IS NOT NULL AND unit_price IS NOT NULL AND cash_amount IS NULL) OR "
            "(transaction_type = 'dividend' AND stock_id IS NOT NULL "
            "AND cash_amount IS NOT NULL AND quantity IS NULL AND unit_price IS NULL) OR "
            "(transaction_type = 'split' AND stock_id IS NOT NULL "
            "AND quantity IS NOT NULL AND unit_price IS NULL AND cash_amount IS NULL) OR "
            "(transaction_type IN ('deposit', 'withdrawal') AND stock_id IS NULL "
            "AND cash_amount IS NOT NULL AND quantity IS NULL AND unit_price IS NULL) OR "
            "(transaction_type = 'fee' AND cash_amount IS NOT NULL "
            "AND quantity IS NULL AND unit_price IS NULL)",
            name=op.f("ck_portfolio_transactions_valid_transaction_payload"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_transactions_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            name=op.f("fk_portfolio_transactions_stock_id_stocks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_transactions")),
        sa.UniqueConstraint(
            "portfolio_id",
            "source",
            "external_id",
            name="uq_portfolio_transaction_external_id",
        ),
    )
    op.create_index(
        "ix_portfolio_transactions_portfolio_trade_date",
        "portfolio_transactions",
        ["portfolio_id", "trade_date", "id"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_transactions_portfolio_available",
        "portfolio_transactions",
        ["portfolio_id", "available_time"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_transactions_stock_id"),
        "portfolio_transactions",
        ["stock_id"],
        unique=False,
    )

    op.create_table(
        "portfolio_allocation_targets",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("cash_currency", sa.String(length=3), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("target_weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
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
            "target_weight >= 0 AND target_weight <= 1",
            name=op.f("ck_portfolio_allocation_targets_valid_allocation_target_weight"),
        ),
        sa.CheckConstraint(
            "(stock_id IS NOT NULL AND cash_currency IS NULL) OR "
            "(stock_id IS NULL AND cash_currency IS NOT NULL)",
            name=op.f("ck_portfolio_allocation_targets_valid_allocation_target_asset"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_allocation_targets_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            name=op.f("fk_portfolio_allocation_targets_stock_id_stocks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_allocation_targets")),
        sa.UniqueConstraint(
            "portfolio_id",
            "effective_date",
            "stock_id",
            name="uq_portfolio_target_stock_date",
        ),
        sa.UniqueConstraint(
            "portfolio_id",
            "effective_date",
            "cash_currency",
            name="uq_portfolio_target_cash_date",
        ),
    )
    op.create_index(
        "ix_portfolio_targets_portfolio_effective",
        "portfolio_allocation_targets",
        ["portfolio_id", "effective_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_allocation_targets_stock_id"),
        "portfolio_allocation_targets",
        ["stock_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_portfolio_allocation_targets_stock_id"),
        table_name="portfolio_allocation_targets",
    )
    op.drop_index(
        "ix_portfolio_targets_portfolio_effective",
        table_name="portfolio_allocation_targets",
    )
    op.drop_table("portfolio_allocation_targets")
    op.drop_index(
        op.f("ix_portfolio_transactions_stock_id"),
        table_name="portfolio_transactions",
    )
    op.drop_index(
        "ix_portfolio_transactions_portfolio_available",
        table_name="portfolio_transactions",
    )
    op.drop_index(
        "ix_portfolio_transactions_portfolio_trade_date",
        table_name="portfolio_transactions",
    )
    op.drop_table("portfolio_transactions")
    _replace_asset_check(OLD_ASSET_CHECK)
