"""Allow unknown corporate-action announcement dates without fabricating them.

Revision ID: c3f4a5b6d7e8
Revises: b2e3f4a5c6d7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f4a5b6d7e8"
down_revision: str | None = "b2e3f4a5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("corporate_actions") as batch:
        batch.drop_constraint("valid_corporate_action_availability", type_="check")
        batch.alter_column(
            "announcement_date",
            existing_type=sa.Date(),
            nullable=True,
        )
        batch.create_check_constraint(
            "valid_corporate_action_availability",
            "announcement_date IS NULL OR announcement_date <= available_date",
        )


def downgrade() -> None:
    connection = op.get_bind()
    unknown = connection.scalar(
        sa.text("SELECT COUNT(*) FROM corporate_actions WHERE announcement_date IS NULL")
    )
    if unknown:
        raise RuntimeError(
            "cannot restore mandatory announcement_date while unknown dates exist"
        )
    with op.batch_alter_table("corporate_actions") as batch:
        batch.drop_constraint("valid_corporate_action_availability", type_="check")
        batch.alter_column(
            "announcement_date",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch.create_check_constraint(
            "valid_corporate_action_availability",
            "announcement_date <= available_date",
        )
