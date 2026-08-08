"""Add hypothesis, relationship, narrative and decision-lineage stores.

Revision ID: e7f1b3c9a620
Revises: d5e8a4c2f710
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.intelligence import (
    IntelligenceDecisionLineage,
    IntelligenceHypothesis,
    IntelligenceNarrative,
    IntelligenceNarrativeExposure,
    IntelligenceRelationship,
)

revision: str = "e7f1b3c9a620"
down_revision: str | None = "d5e8a4c2f710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    IntelligenceHypothesis.__table__,
    IntelligenceRelationship.__table__,
    IntelligenceNarrative.__table__,
    IntelligenceNarrativeExposure.__table__,
    IntelligenceDecisionLineage.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
