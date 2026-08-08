"""Replace preview model stages with quant validation statuses.

Revision ID: c2a7e5d9b104
Revises: a84d6e2c1f09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2a7e5d9b104"
down_revision: str | None = "a84d6e2c1f09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = (
    "status IN ('Experimental', 'Research', 'Validating', 'Tested', "
    "'Production Approved', 'Manual Pilot', 'Disabled', 'Suspended', 'Retired')"
)
_OLD = (
    "status IN ('Experimental', 'Research', 'Paper Trading', 'Shadow', "
    "'Manual Pilot', 'Suspended', 'Retired')"
)


def upgrade() -> None:
    with op.batch_alter_table("model_registry") as batch:
        batch.drop_constraint("valid_model_registry_status", type_="check")
        batch.create_check_constraint("valid_model_registry_status", _NEW)


def downgrade() -> None:
    with op.batch_alter_table("model_registry") as batch:
        batch.drop_constraint("valid_model_registry_status", type_="check")
        batch.create_check_constraint("valid_model_registry_status", _OLD)
