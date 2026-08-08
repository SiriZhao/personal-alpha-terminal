"""add statistical validation safeguards

Revision ID: e19f7b3c4a62
Revises: a72d4e9c1f30
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e19f7b3c4a62"
down_revision: str | None = "a72d4e9c1f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_study_statistics",
        sa.Column(
            "meets_minimum",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "event_study_statistics",
        sa.Column(
            "confidence_level",
            sa.Numeric(8, 6),
            server_default="0.95",
            nullable=False,
        ),
    )
    for column_name, numeric_type in (
        ("positive_probability_lower", sa.Numeric(12, 10)),
        ("positive_probability_upper", sa.Numeric(12, 10)),
        ("win_rate_lower", sa.Numeric(12, 10)),
        ("win_rate_upper", sa.Numeric(12, 10)),
        ("average_return_lower", sa.Numeric(20, 10)),
        ("average_return_upper", sa.Numeric(20, 10)),
    ):
        op.add_column(
            "event_study_statistics",
            sa.Column(column_name, numeric_type, nullable=True),
        )

    op.add_column(
        "conditional_probability_results",
        sa.Column("raw_probability", sa.Numeric(12, 10), nullable=True),
    )

    for column_name in ("p_value", "fdr_q_value", "bonferroni_p_value"):
        op.add_column(
            "market_graph_edges",
            sa.Column(column_name, sa.Numeric(12, 10), nullable=True),
        )
    op.add_column(
        "market_graph_edges",
        sa.Column(
            "significant_fdr",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "market_graph_edges",
        sa.Column(
            "significant_bonferroni",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("market_graph_edges", "significant_bonferroni")
    op.drop_column("market_graph_edges", "significant_fdr")
    op.drop_column("market_graph_edges", "bonferroni_p_value")
    op.drop_column("market_graph_edges", "fdr_q_value")
    op.drop_column("market_graph_edges", "p_value")
    op.drop_column("conditional_probability_results", "raw_probability")
    op.drop_column("event_study_statistics", "average_return_upper")
    op.drop_column("event_study_statistics", "average_return_lower")
    op.drop_column("event_study_statistics", "win_rate_upper")
    op.drop_column("event_study_statistics", "win_rate_lower")
    op.drop_column("event_study_statistics", "positive_probability_upper")
    op.drop_column("event_study_statistics", "positive_probability_lower")
    op.drop_column("event_study_statistics", "confidence_level")
    op.drop_column("event_study_statistics", "meets_minimum")
