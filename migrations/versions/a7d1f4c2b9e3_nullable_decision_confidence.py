"""allow unavailable probability confidence to be null

Revision ID: a7d1f4c2b9e3
Revises: f4c1b3a9d7e2
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d1f4c2b9e3"
down_revision: str | None = "f4c1b3a9d7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NULLABLE_SCORE_CHECK = (
    "quant_score >= 0 AND quant_score <= 100 AND "
    "(confidence_score IS NULL OR "
    "(confidence_score >= 0 AND confidence_score <= 100))"
)
_REQUIRED_SCORE_CHECK = (
    "quant_score >= 0 AND quant_score <= 100 AND "
    "confidence_score >= 0 AND confidence_score <= 100"
)


def upgrade() -> None:
    with op.batch_alter_table("quant_decision_recommendations", recreate="always") as batch:
        batch.alter_column(
            "confidence_score",
            existing_type=sa.Numeric(8, 4),
            nullable=True,
        )
        batch.drop_constraint("valid_quant_decision_scores", type_="check")
        batch.create_check_constraint("valid_quant_decision_scores", _NULLABLE_SCORE_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("quant_decision_recommendations", recreate="always") as batch:
        batch.alter_column(
            "confidence_score",
            existing_type=sa.Numeric(8, 4),
            nullable=False,
        )
        batch.drop_constraint("valid_quant_decision_scores", type_="check")
        batch.create_check_constraint("valid_quant_decision_scores", _REQUIRED_SCORE_CHECK)
