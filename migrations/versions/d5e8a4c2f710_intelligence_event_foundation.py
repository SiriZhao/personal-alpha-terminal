"""Add versioned intelligence event and research stores.

Revision ID: d5e8a4c2f710
Revises: c2a7e5d9b104
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.intelligence import (
    IntelligenceEvent,
    IntelligenceEventEvidence,
    IntelligenceExtractionCache,
    IntelligenceFeature,
    IntelligenceRawInformation,
    IntelligenceResearchResult,
)

revision: str = "d5e8a4c2f710"
down_revision: str | None = "c2a7e5d9b104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    IntelligenceRawInformation.__table__,
    IntelligenceEvent.__table__,
    IntelligenceEventEvidence.__table__,
    IntelligenceFeature.__table__,
    IntelligenceResearchResult.__table__,
    IntelligenceExtractionCache.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
