"""Add governed multi-fill manual execution orders.

Revision ID: d4a5b6c7d8e9
Revises: c3f4a5b6d7e8
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.manual_execution import (
    ManualExecutionFill,
    ManualExecutionOrder,
)

revision: str = "d4a5b6c7d8e9"
down_revision: str | None = "c3f4a5b6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    ManualExecutionOrder.__table__.create(bind=bind, checkfirst=True)
    ManualExecutionFill.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ManualExecutionFill.__table__.drop(bind=bind, checkfirst=True)
    ManualExecutionOrder.__table__.drop(bind=bind, checkfirst=True)
