"""add ROUND80 authority raw, snapshot, constituent, and conflict ledgers

Revision ID: c8d3e7f1a4b6
Revises: b7e0a2d4c5f6
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d3e7f1a4b6"
down_revision: str | None = "b7e0a2d4c5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.BigInteger:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "authority_raw_fetch_evidence",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("fetch_id", sa.String(128), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("logical_endpoint", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_identity", sa.String(128), nullable=False),
        sa.Column("storage_reference", sa.String(1024), nullable=True),
        sa.Column("immutable_identity", sa.String(64), nullable=False),
        sa.CheckConstraint("received_at >= requested_at", name="valid_authority_fetch_timestamps"),
        sa.UniqueConstraint("fetch_id", name="uq_authority_raw_fetch_id"),
        sa.UniqueConstraint("immutable_identity", name="uq_authority_raw_fetch_identity"),
    )
    op.create_index(
        "ix_authority_raw_fetch_domain_received",
        "authority_raw_fetch_evidence",
        ["domain", "received_at"],
    )
    op.create_table(
        "authority_dataset_snapshots",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("snapshot_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_versions", sa.JSON(), nullable=False),
        sa.Column("raw_hashes", sa.JSON(), nullable=False),
        sa.Column("normalized_dataset_hashes", sa.JSON(), nullable=False),
        sa.Column("security_master_hash", sa.String(64), nullable=False),
        sa.Column("corporate_action_hash", sa.String(64), nullable=False),
        sa.Column("benchmark_hash", sa.String(64), nullable=False),
        sa.Column("fundamental_hash", sa.String(64), nullable=False),
        sa.Column("universe_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("git_sha", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("data_cutoff <= created_at", name="valid_authority_snapshot_cutoff"),
        sa.UniqueConstraint("snapshot_id", name="uq_authority_dataset_snapshot_id"),
        sa.UniqueConstraint("manifest_hash", name="uq_authority_dataset_manifest_hash"),
    )
    op.create_index(
        "ix_authority_dataset_snapshot_cutoff",
        "authority_dataset_snapshots",
        ["data_cutoff"],
    )
    op.create_table(
        "historical_index_constituent_evidence",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("index_id", sa.String(16), nullable=False),
        sa.Column("security_id", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("announcement_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_record_id", sa.String(512), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("index_id IN ('SP500', 'NASDAQ100')", name="valid_historical_index_id"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from <= effective_to",
            name="valid_historical_index_period",
        ),
        sa.CheckConstraint(
            "announcement_time IS NULL OR announcement_time <= known_at",
            name="valid_historical_index_announcement",
        ),
        sa.UniqueConstraint(
            "index_id",
            "security_id",
            "effective_from",
            "source",
            "source_record_id",
            name="uq_historical_index_constituent_source",
        ),
    )
    op.create_index(
        "ix_historical_index_constituent_pit",
        "historical_index_constituent_evidence",
        ["index_id", "effective_from", "effective_to", "known_at"],
    )
    op.create_table(
        "authority_provider_conflicts",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("conflict_id", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_a", sa.String(128), nullable=False),
        sa.Column("provider_b", sa.String(128), nullable=False),
        sa.Column("value_a", sa.Text(), nullable=False),
        sa.Column("value_b", sa.Text(), nullable=False),
        sa.Column("tolerance", sa.String(32), nullable=False),
        sa.Column("resolution", sa.String(64), nullable=False),
        sa.Column("resolved_provider", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("quality_status", sa.String(64), nullable=False),
        sa.UniqueConstraint("conflict_id", name="uq_authority_provider_conflict_id"),
    )
    op.create_index(
        "ix_authority_provider_conflict_domain_status",
        "authority_provider_conflicts",
        ["domain", "quality_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_authority_provider_conflict_domain_status", table_name="authority_provider_conflicts")
    op.drop_table("authority_provider_conflicts")
    op.drop_index("ix_historical_index_constituent_pit", table_name="historical_index_constituent_evidence")
    op.drop_table("historical_index_constituent_evidence")
    op.drop_index("ix_authority_dataset_snapshot_cutoff", table_name="authority_dataset_snapshots")
    op.drop_table("authority_dataset_snapshots")
    op.drop_index("ix_authority_raw_fetch_domain_received", table_name="authority_raw_fetch_evidence")
    op.drop_table("authority_raw_fetch_evidence")
