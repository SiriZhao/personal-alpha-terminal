"""Quant core closure part 2 governance and reconciliation.

Revision ID: a1d2e3f4b5c6
Revises: f9c0a1b2d3e4
"""

from collections.abc import Sequence

from alembic import op

from personal_alpha_terminal.models.governance import (
    ExperimentRecord,
    ExperimentResultRecord,
    PortfolioReconciliationRecord,
)

revision: str = "a1d2e3f4b5c6"
down_revision: str | None = "f9c0a1b2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    ExperimentRecord.__table__,
    ExperimentResultRecord.__table__,
    PortfolioReconciliationRecord.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in NEW_TABLES:
        table.create(bind=bind, checkfirst=True)
    op.create_index(
        "ix_market_universe_snapshots_definition_id",
        "market_universe_snapshots",
        ["definition_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index(
        "ix_market_universe_snapshots_definition_id",
        table_name="market_universe_snapshots",
    )
    for table in reversed(NEW_TABLES):
        table.drop(bind=bind, checkfirst=True)
