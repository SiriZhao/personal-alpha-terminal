"""add provider capability matrix and normalized price contracts

Revision ID: 4d9e8a7c6b51
Revises: 0a7c9e4d2b61
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d9e8a7c6b51"
down_revision: str | None = "0a7c9e4d2b61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_empty_prices() -> None:
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM prices")).scalar_one()
    if count:
        raise RuntimeError(
            "market-data contract migration requires an empty prices table; "
            "quarantine and re-ingest legacy rows instead of assigning unverified units"
        )


def upgrade() -> None:
    _assert_empty_prices()
    op.create_table(
        "provider_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("raw_volume_unit", sa.String(length=16), nullable=False),
        sa.Column("volume_unit", sa.String(length=16), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("volume_multiplier", sa.Numeric(20, 8), nullable=False),
        sa.Column("raw_share_unit", sa.Numeric(20, 8), nullable=False),
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
        sa.CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_capability_market"),
        sa.CheckConstraint(
            "asset_type IN ('stock', 'etf', 'index', 'bond')",
            name="valid_capability_asset_type",
        ),
        sa.CheckConstraint(
            "raw_volume_unit IN ('share', 'hand', 'face_value', 'none', 'unknown')",
            name="valid_raw_volume_unit",
        ),
        sa.CheckConstraint(
            "volume_unit IN ('share', 'face_value', 'none')",
            name="valid_normalized_volume_unit",
        ),
        sa.CheckConstraint(
            "price_type IN ('unadjusted_ohlcv', 'index_level_ohlcv', "
            "'clean_price_ohlcv')",
            name="valid_capability_price_type",
        ),
        sa.CheckConstraint("volume_multiplier > 0", name="positive_volume_multiplier"),
        sa.CheckConstraint("raw_share_unit > 0", name="positive_raw_share_unit"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_capabilities")),
        sa.UniqueConstraint(
            "provider",
            "market",
            "asset_type",
            name="uq_provider_capabilities_provider_market_asset",
        ),
    )
    with op.batch_alter_table("prices") as batch_op:
        batch_op.add_column(
            sa.Column("asset_type", sa.String(length=16), nullable=False)
        )
        batch_op.add_column(
            sa.Column("volume_unit", sa.String(length=16), nullable=False)
        )
        batch_op.add_column(
            sa.Column("price_currency", sa.String(length=3), nullable=False)
        )
        batch_op.add_column(
            sa.Column("share_unit", sa.Numeric(20, 8), nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "price_type",
                sa.String(length=32),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "data_contract_version",
                sa.String(length=32),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "valid_price_asset_type", "asset_type IN ('stock', 'etf', 'index', 'bond')"
        )
        batch_op.create_check_constraint(
            "valid_price_volume_unit", "volume_unit IN ('share', 'face_value', 'none')"
        )
        batch_op.create_check_constraint("normalized_share_unit", "share_unit = 1")
        batch_op.create_check_constraint(
            "valid_price_currency",
            "length(price_currency) = 3 AND price_currency = upper(price_currency)",
        )
        batch_op.create_check_constraint(
            "valid_price_type",
            "price_type IN ('unadjusted_ohlcv', 'index_level_ohlcv', "
            "'clean_price_ohlcv')",
        )
        batch_op.create_check_constraint(
            "valid_data_contract_version",
            "data_contract_version = 'market-data-v1'",
        )
        batch_op.create_check_constraint(
            "asset_volume_unit_match",
            "(asset_type IN ('stock', 'etf') AND volume_unit = 'share') OR "
            "(asset_type = 'bond' AND volume_unit = 'face_value') OR "
            "(asset_type = 'index' AND volume_unit IN ('share', 'none'))",
        )
        batch_op.create_check_constraint(
            "volume_matches_unit",
            "(volume_unit = 'none' AND volume IS NULL) OR volume_unit <> 'none'",
        )


def downgrade() -> None:
    with op.batch_alter_table("prices") as batch_op:
        batch_op.drop_constraint("volume_matches_unit", type_="check")
        batch_op.drop_constraint("asset_volume_unit_match", type_="check")
        batch_op.drop_constraint("valid_data_contract_version", type_="check")
        batch_op.drop_constraint("valid_price_type", type_="check")
        batch_op.drop_constraint("valid_price_currency", type_="check")
        batch_op.drop_constraint("normalized_share_unit", type_="check")
        batch_op.drop_constraint("valid_price_volume_unit", type_="check")
        batch_op.drop_constraint("valid_price_asset_type", type_="check")
        batch_op.drop_column("data_contract_version")
        batch_op.drop_column("price_type")
        batch_op.drop_column("share_unit")
        batch_op.drop_column("price_currency")
        batch_op.drop_column("volume_unit")
        batch_op.drop_column("asset_type")
    op.drop_table("provider_capabilities")
