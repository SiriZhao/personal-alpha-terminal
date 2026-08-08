"""Retain the historical revision after paper-ledger removal.

Revision ID: a84d6e2c1f09
Revises: 9f3c2a1b7d40

The original preview revision added indexes to paper-ledger tables. New
installations no longer create those tables. Existing installations keep their
inert legacy tables so an application upgrade never destroys user data.
"""

from collections.abc import Sequence

revision: str = "a84d6e2c1f09"
down_revision: str | None = "9f3c2a1b7d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
