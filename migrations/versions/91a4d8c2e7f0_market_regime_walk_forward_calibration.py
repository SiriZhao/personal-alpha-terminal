"""add guarded walk-forward market regime calibration

Revision ID: 91a4d8c2e7f0
Revises: 7f2c1d9a6b40
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "91a4d8c2e7f0"
down_revision: str | None = "7f2c1d9a6b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("market_regime_runs") as batch:
        batch.add_column(
            sa.Column(
                "calibration_status",
                sa.String(length=16),
                server_default="score_only",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "calibration_method",
                sa.String(length=64),
                server_default="none",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "calibration_observation_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("brier_score", sa.Numeric(18, 16), nullable=True))
        batch.add_column(sa.Column("raw_score_brier", sa.Numeric(18, 16), nullable=True))
        batch.add_column(sa.Column("baseline_brier", sa.Numeric(18, 16), nullable=True))
        batch.add_column(
            sa.Column("calibration_curve", sa.JSON(), server_default="[]", nullable=False)
        )
        batch.add_column(
            sa.Column("calibration_reasons", sa.JSON(), server_default="[]", nullable=False)
        )
        batch.create_check_constraint(
            "valid_regime_calibration_status",
            "calibration_status IN ('calibrated', 'score_only')",
        )

    with op.batch_alter_table("market_regime_observations") as batch:
        batch.drop_constraint("valid_risk_on_probability", type_="check")
        batch.drop_constraint("valid_risk_off_probability", type_="check")
        batch.drop_constraint("valid_neutral_probability", type_="check")
        batch.alter_column("risk_on_probability", new_column_name="risk_on_score")
        batch.alter_column("risk_off_probability", new_column_name="risk_off_score")
        batch.alter_column("neutral_probability", new_column_name="neutral_score")
        batch.create_check_constraint(
            "valid_risk_on_score", "risk_on_score >= 0 AND risk_on_score <= 1"
        )
        batch.create_check_constraint(
            "valid_risk_off_score", "risk_off_score >= 0 AND risk_off_score <= 1"
        )
        batch.create_check_constraint(
            "valid_neutral_score", "neutral_score >= 0 AND neutral_score <= 1"
        )

    with op.batch_alter_table("market_regime_observations") as batch:
        batch.add_column(sa.Column("risk_on_probability", sa.Numeric(18, 16), nullable=True))
        batch.add_column(sa.Column("risk_off_probability", sa.Numeric(18, 16), nullable=True))
        batch.add_column(sa.Column("neutral_probability", sa.Numeric(18, 16), nullable=True))
        batch.create_check_constraint(
            "valid_optional_regime_probabilities",
            "(risk_on_probability IS NULL AND risk_off_probability IS NULL AND "
            "neutral_probability IS NULL) OR "
            "(risk_on_probability >= 0 AND risk_on_probability <= 1 AND "
            "risk_off_probability >= 0 AND risk_off_probability <= 1 AND "
            "neutral_probability >= 0 AND neutral_probability <= 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("market_regime_observations") as batch:
        batch.drop_constraint("valid_optional_regime_probabilities", type_="check")
        batch.drop_column("neutral_probability")
        batch.drop_column("risk_off_probability")
        batch.drop_column("risk_on_probability")

    with op.batch_alter_table("market_regime_observations") as batch:
        batch.drop_constraint("valid_neutral_score", type_="check")
        batch.drop_constraint("valid_risk_off_score", type_="check")
        batch.drop_constraint("valid_risk_on_score", type_="check")
        batch.alter_column("neutral_score", new_column_name="neutral_probability")
        batch.alter_column("risk_off_score", new_column_name="risk_off_probability")
        batch.alter_column("risk_on_score", new_column_name="risk_on_probability")
        batch.create_check_constraint(
            "valid_risk_on_probability",
            "risk_on_probability >= 0 AND risk_on_probability <= 1",
        )
        batch.create_check_constraint(
            "valid_risk_off_probability",
            "risk_off_probability >= 0 AND risk_off_probability <= 1",
        )
        batch.create_check_constraint(
            "valid_neutral_probability",
            "neutral_probability >= 0 AND neutral_probability <= 1",
        )

    with op.batch_alter_table("market_regime_runs") as batch:
        batch.drop_constraint("valid_regime_calibration_status", type_="check")
        batch.drop_column("calibration_reasons")
        batch.drop_column("calibration_curve")
        batch.drop_column("baseline_brier")
        batch.drop_column("raw_score_brier")
        batch.drop_column("brier_score")
        batch.drop_column("calibration_observation_count")
        batch.drop_column("calibration_method")
        batch.drop_column("calibration_status")
