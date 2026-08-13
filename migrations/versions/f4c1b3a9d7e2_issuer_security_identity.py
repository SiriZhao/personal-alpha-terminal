"""add canonical issuer security identity history and raw identity columns

Revision ID: f4c1b3a9d7e2
Revises: e7f1b3c9a620
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "f4c1b3a9d7e2"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.BigInteger:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "issuer_security_identity_history",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("cik", _id(), nullable=False),
        sa.Column("issuer_id", sa.String(64), nullable=False),
        sa.Column("issuer_name", sa.String(256), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("permanent_security_id", sa.String(64), nullable=True),
        sa.Column("ticker_as_of", sa.String(32), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mapping_source_type", sa.String(48), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("evidence_identifier", sa.String(512), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="valid_issuer_security_period",
        ),
        sa.CheckConstraint(
            "permanent_security_id IS NULL OR ticker_as_of IS NOT NULL",
            name="issuer_security_mapping_requires_ticker",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "cik",
            "evidence_identifier",
            "ticker_as_of",
            "effective_from",
            "source",
            "source_version",
            name="uq_issuer_security_identity_vintage",
        ),
    )
    op.create_index(
        "ix_issuer_security_identity_pit",
        "issuer_security_identity_history",
        ["cik", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_issuer_security_identity_cik",
        "issuer_security_identity_history",
        ["cik"],
    )
    op.create_index(
        "ix_issuer_security_identity_stock_id",
        "issuer_security_identity_history",
        ["stock_id"],
    )

    bind = op.get_bind()
    existing_columns = {
        column["name"]
        for column in inspect(bind).get_columns("intelligence_raw_information")
    }
    raw_columns = (
        ("issuer_id", sa.String(64)),
        ("issuer_name", sa.String(256)),
        ("permanent_security_id", sa.String(64)),
        ("ticker_as_of", sa.String(32)),
        ("document_type", sa.String(32)),
        ("issuer_resolution_status", sa.String(48)),
        ("security_mapping_status", sa.String(48)),
        ("security_mapping_source", sa.String(256)),
        ("security_mapping_source_version", sa.String(128)),
    )
    for name, column_type in raw_columns:
        if name not in existing_columns:
            op.add_column(
                "intelligence_raw_information",
                sa.Column(name, column_type, nullable=True),
            )
    op.create_index(
        "ix_intelligence_raw_identity",
        "intelligence_raw_information",
        ["issuer_id", "permanent_security_id", "security_mapping_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_intelligence_raw_identity", table_name="intelligence_raw_information")
    for column in (
        "security_mapping_source_version",
        "security_mapping_source",
        "security_mapping_status",
        "issuer_resolution_status",
        "document_type",
        "ticker_as_of",
        "permanent_security_id",
        "issuer_name",
        "issuer_id",
    ):
        op.drop_column("intelligence_raw_information", column)
    op.drop_index(
        "ix_issuer_security_identity_stock_id",
        table_name="issuer_security_identity_history",
    )
    op.drop_index(
        "ix_issuer_security_identity_cik",
        table_name="issuer_security_identity_history",
    )
    op.drop_index(
        "ix_issuer_security_identity_pit",
        table_name="issuer_security_identity_history",
    )
    op.drop_table("issuer_security_identity_history")
