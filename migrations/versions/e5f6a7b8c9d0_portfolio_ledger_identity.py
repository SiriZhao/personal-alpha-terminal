"""Record portfolio ledger source and schema version.

Revision ID: e5f6a7b8c9d0
Revises: d4a5b6c7d8e9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("portfolios") as batch:
        batch.add_column(
            sa.Column(
                "source",
                sa.String(length=64),
                nullable=False,
                server_default="manual",
            )
        )
        batch.add_column(
            sa.Column(
                "schema_version",
                sa.String(length=32),
                nullable=False,
                server_default="portfolio-v1",
            )
        )
    op.execute("UPDATE portfolios SET source = 'manual' WHERE source IS NULL")
    op.execute(
        "UPDATE portfolios SET schema_version = 'portfolio-v1' "
        "WHERE schema_version IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("portfolios") as batch:
        batch.drop_column("schema_version")
        batch.drop_column("source")
