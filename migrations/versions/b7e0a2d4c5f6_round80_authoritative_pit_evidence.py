"""add ROUND80 authoritative SEC and lifecycle evidence ledgers

Revision ID: b7e0a2d4c5f6
Revises: a7d1f4c2b9e3
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e0a2d4c5f6"
down_revision: str | None = "a7d1f4c2b9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.BigInteger:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "security_lifecycle_events",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("issuer_id", sa.String(64), nullable=True),
        sa.Column("security_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("old_ticker", sa.String(32), nullable=True),
        sa.Column("new_ticker", sa.String(32), nullable=True),
        sa.Column("old_name", sa.String(256), nullable=True),
        sa.Column("new_name", sa.String(256), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("announcement_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=True),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("predecessor_security_id", sa.String(64), nullable=True),
        sa.Column("successor_security_id", sa.String(64), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_record_id", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('LISTING', 'DELISTING', 'SUSPENSION', 'TICKER_CHANGE', "
            "'NAME_CHANGE', 'MERGER', 'ACQUISITION', 'SPINOFF', 'SPLIT', "
            "'REVERSE_SPLIT', 'EXCHANGE_CHANGE', 'OTHER')",
            name="valid_security_lifecycle_event_type",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="valid_security_lifecycle_confidence",
        ),
        sa.CheckConstraint(
            "announcement_timestamp IS NULL OR announcement_timestamp <= known_at",
            name="valid_security_lifecycle_announcement",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "event_id",
            "source",
            "source_record_id",
            name="uq_security_lifecycle_source_record",
        ),
    )
    op.create_index(
        "ix_security_lifecycle_security_pit",
        "security_lifecycle_events",
        ["security_id", "effective_date", "known_at"],
    )

    op.create_table(
        "sec_filing_evidence",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("cik", _id(), nullable=False),
        sa.Column("issuer_id", sa.String(64), nullable=False),
        sa.Column("issuer_name", sa.String(256), nullable=False),
        sa.Column("accession_number", sa.String(32), nullable=False),
        sa.Column("form", sa.String(32), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("report_period_end", sa.Date(), nullable=True),
        sa.Column("acceptance_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("primary_document", sa.String(256), nullable=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="sec_edgar"),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("revision_identity", sa.String(256), nullable=False),
        sa.CheckConstraint("cik > 0", name="positive_sec_filing_cik"),
        sa.CheckConstraint(
            "acceptance_datetime <= known_at AND known_at <= fetched_at",
            name="valid_sec_filing_timestamps",
        ),
        sa.UniqueConstraint("cik", "accession_number", name="uq_sec_filing_accession"),
    )
    op.create_index("ix_sec_filing_known_at", "sec_filing_evidence", ["cik", "known_at"])

    op.create_table(
        "sec_company_fact_evidence",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("filing_id", _id(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("issuer_id", sa.String(64), nullable=False),
        sa.Column("cik", _id(), nullable=False),
        sa.Column("taxonomy", sa.String(64), nullable=False),
        sa.Column("concept", sa.String(128), nullable=False),
        sa.Column("value", sa.Numeric(36, 10), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(16), nullable=True),
        sa.Column("form", sa.String(32), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("acceptance_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accession_number", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_identity", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("cik > 0", name="positive_sec_fact_cik"),
        sa.CheckConstraint(
            "acceptance_datetime <= known_at AND known_at <= fetched_at",
            name="valid_sec_fact_timestamps",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["sec_filing_evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("revision_identity", name="uq_sec_fact_revision_identity"),
    )
    op.create_index(
        "ix_sec_fact_pit",
        "sec_company_fact_evidence",
        ["cik", "taxonomy", "concept", "known_at", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_sec_fact_pit", table_name="sec_company_fact_evidence")
    op.drop_table("sec_company_fact_evidence")
    op.drop_index("ix_sec_filing_known_at", table_name="sec_filing_evidence")
    op.drop_table("sec_filing_evidence")
    op.drop_index("ix_security_lifecycle_security_pit", table_name="security_lifecycle_events")
    op.drop_table("security_lifecycle_events")
