"""Add deterministic decision and manual-review audit tables.

Revision ID: 6e2a1c4d9b70
Revises: 3b7e2d9f4a10
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6e2a1c4d9b70"
down_revision: str | None = "3b7e2d9f4a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.TypeEngine[object]:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "quant_decision_runs",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("as_of_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("gate_status", sa.String(16), nullable=False),
        sa.Column("authorization_id", sa.String(64), nullable=True),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('generated', 'no_decision', 'blocked')",
            name="valid_quant_decision_run_status",
        ),
        sa.CheckConstraint(
            "gate_status IN ('APPROVED', 'RESEARCH_ONLY', 'DEGRADED', 'BLOCKED')",
            name="valid_quant_decision_gate_status",
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "portfolio_id",
            "as_of_time",
            "input_fingerprint",
            name="uq_quant_decision_run_input",
        ),
    )
    op.create_index(
        "ix_quant_decision_run_latest",
        "quant_decision_runs",
        ["portfolio_id", "as_of_time"],
    )

    op.create_table(
        "quant_decision_recommendations",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("recommendation_id", sa.String(96), nullable=False, unique=True),
        sa.Column("run_id", _id(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("current_weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("target_weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("quant_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("confidence_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("component_scores", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("risk_factors", sa.JSON(), nullable=False),
        sa.Column("evidence_grade", sa.String(32), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("suggested_shares", sa.BigInteger(), nullable=False),
        sa.Column("earliest_execution_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('BUY', 'SELL', 'HOLD', 'WATCH')",
            name="valid_quant_decision_action",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'watch')",
            name="valid_quant_decision_review_status",
        ),
        sa.CheckConstraint(
            "current_weight >= 0 AND current_weight <= 1 AND "
            "target_weight >= 0 AND target_weight <= 1",
            name="valid_quant_decision_weights",
        ),
        sa.CheckConstraint(
            "quant_score >= 0 AND quant_score <= 100 AND "
            "confidence_score >= 0 AND confidence_score <= 100",
            name="valid_quant_decision_scores",
        ),
        sa.CheckConstraint("reference_price > 0", name="positive_decision_reference_price"),
        sa.ForeignKeyConstraint(["run_id"], ["quant_decision_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_id"], ["security_master.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "stock_id", name="uq_quant_decision_run_stock"),
    )
    op.create_index(
        "ix_quant_decision_pending",
        "quant_decision_recommendations",
        ["review_status", "expires_at"],
    )
    op.create_index(
        "ix_quant_decision_recommendation_stock",
        "quant_decision_recommendations",
        ["stock_id"],
    )

    op.create_table(
        "decision_history",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("recommendation_id", _id(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'watch')",
            name="valid_decision_history_choice",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["quant_decision_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("recommendation_id", name="uq_decision_history_recommendation"),
    )
    op.create_index("ix_decision_history_decided", "decision_history", ["decided_at"])

def downgrade() -> None:
    op.drop_index("ix_decision_history_decided", table_name="decision_history")
    op.drop_table("decision_history")
    op.drop_index(
        "ix_quant_decision_recommendation_stock",
        table_name="quant_decision_recommendations",
    )
    op.drop_index("ix_quant_decision_pending", table_name="quant_decision_recommendations")
    op.drop_table("quant_decision_recommendations")
    op.drop_index("ix_quant_decision_run_latest", table_name="quant_decision_runs")
    op.drop_table("quant_decision_runs")
