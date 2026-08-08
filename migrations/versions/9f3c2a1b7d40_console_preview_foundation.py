"""Add the immutable console data-snapshot manifest.

Revision ID: 9f3c2a1b7d40
Revises: 6e2a1c4d9b70
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.console import DataSnapshotManifest

revision: str = "9f3c2a1b7d40"
down_revision: str | None = "6e2a1c4d9b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    DataSnapshotManifest.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
