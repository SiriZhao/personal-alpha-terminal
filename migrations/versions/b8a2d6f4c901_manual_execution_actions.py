"""Add explicit ADD and REDUCE manual-review actions.

Revision ID: b8a2d6f4c901
Revises: e7f1b3c9a620
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8a2d6f4c901"
down_revision: str | None = "e7f1b3c9a620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("quant_decision_recommendations") as batch:
        batch.drop_constraint("valid_quant_decision_action", type_="check")
        batch.create_check_constraint(
            "valid_quant_decision_action",
            "action IN ('BUY', 'ADD', 'REDUCE', 'SELL', 'HOLD', 'WATCH')",
        )


def downgrade() -> None:
    with op.batch_alter_table("quant_decision_recommendations") as batch:
        batch.drop_constraint("valid_quant_decision_action", type_="check")
        batch.create_check_constraint(
            "valid_quant_decision_action",
            "action IN ('BUY', 'SELL', 'HOLD', 'WATCH')",
        )
