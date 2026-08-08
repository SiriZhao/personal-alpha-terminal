"""add point-in-time market-data safety fields

Revision ID: c91b7e4a2d60
Revises: f6a9d2c41e7b
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91b7e4a2d60"
down_revision: str | None = "f6a9d2c41e7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prices",
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prices",
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prices",
        sa.Column("open_tradable", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "ix_prices_available_time",
        "prices",
        ["stock_id", "available_time"],
        unique=False,
    )
    op.add_column(
        "financials",
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "event_occurrences",
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "event_occurrences",
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "event_occurrences",
        sa.Column("ingested_time", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_occurrences", "ingested_time")
    op.drop_column("event_occurrences", "available_time")
    op.drop_column("event_occurrences", "event_time")
    op.drop_column("financials", "ingested_at")
    op.drop_index("ix_prices_available_time", table_name="prices")
    op.drop_column("prices", "open_tradable")
    op.drop_column("prices", "available_time")
    op.drop_column("prices", "event_time")
