"""Add immutable manual execution audit records.

Revision ID: b2e3f4a5c6d7
Revises: a1d2e3f4b5c6
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.us_quant import ManualExecutionRecord

revision: str = "b2e3f4a5c6d7"
down_revision: str | None = "a1d2e3f4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ManualExecutionRecord.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ManualExecutionRecord.__table__.drop(bind=op.get_bind(), checkfirst=True)
