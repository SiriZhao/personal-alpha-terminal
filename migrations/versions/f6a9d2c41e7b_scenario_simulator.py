"""add scenario simulator tables

Revision ID: f6a9d2c41e7b
Revises: d4e1c7a9b2f0
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a9d2c41e7b"
down_revision: str | None = "d4e1c7a9b2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_risk_factors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("shock_unit", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("normalized_minimum", sa.Numeric(18, 8), nullable=False),
        sa.Column("normalized_maximum", sa.Numeric(18, 8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "shock_unit IN ('decimal_return', 'basis_points', 'standard_score')",
            name=op.f("ck_scenario_risk_factors_valid_scenario_factor_unit"),
        ),
        sa.CheckConstraint(
            "normalized_minimum < normalized_maximum",
            name=op.f("ck_scenario_risk_factors_valid_scenario_factor_bounds"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_risk_factors")),
        sa.UniqueConstraint("code", name=op.f("uq_scenario_risk_factors_code")),
    )
    op.create_table(
        "scenario_definitions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scenario_type", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("definition_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("factor_shocks", sa.JSON(), nullable=False),
        sa.Column("currency_shocks", sa.JSON(), nullable=False),
        sa.Column("evidence_level", sa.String(length=32), nullable=False),
        sa.Column("data_sources", sa.JSON(), nullable=False),
        sa.Column("historical_start", sa.Date(), nullable=True),
        sa.Column("historical_end", sa.Date(), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scenario_type IN ('custom', 'historical', 'hypothetical')",
            name=op.f("ck_scenario_definitions_valid_scenario_definition_type"),
        ),
        sa.CheckConstraint(
            "evidence_level IN "
            "('source_backed', 'calibrated_historical', "
            "'user_assumption', 'illustrative')",
            name=op.f("ck_scenario_definitions_valid_scenario_evidence_level"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_definitions")),
        sa.UniqueConstraint(
            "definition_fingerprint",
            name=op.f("uq_scenario_definitions_definition_fingerprint"),
        ),
        sa.UniqueConstraint(
            "name",
            "version",
            name="uq_scenario_definition_version",
        ),
    )
    op.create_table(
        "asset_risk_factor_exposures",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("factor_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("sensitivity", sa.Numeric(18, 10), nullable=False),
        sa.Column("sensitivity_low", sa.Numeric(18, 10), nullable=False),
        sa.Column("sensitivity_high", sa.Numeric(18, 10), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sensitivity_low <= sensitivity AND sensitivity <= sensitivity_high",
            name=op.f("ck_asset_risk_factor_exposures_valid_asset_factor_sensitivity_interval"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 100",
            name=op.f("ck_asset_risk_factor_exposures_valid_asset_factor_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["factor_id"],
            ["scenario_risk_factors.id"],
            name=op.f("fk_asset_risk_factor_exposures_factor_id_scenario_risk_factors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            name=op.f("fk_asset_risk_factor_exposures_stock_id_stocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_asset_risk_factor_exposures"),
        ),
        sa.UniqueConstraint(
            "stock_id",
            "factor_id",
            "as_of_date",
            "source",
            name="uq_asset_factor_exposure_version",
        ),
    )
    op.create_index(
        "ix_asset_factor_exposure_lookup",
        "asset_risk_factor_exposures",
        ["stock_id", "factor_id", "as_of_date"],
        unique=False,
    )
    op.create_table(
        "scenario_simulation_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column(
            "definition_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("original_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("stressed_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("pnl_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("pnl_percent", sa.Numeric(18, 10), nullable=False),
        sa.Column("pnl_percent_low", sa.Numeric(18, 10), nullable=False),
        sa.Column("pnl_percent_high", sa.Numeric(18, 10), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("mapped_weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("uncovered_weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name=op.f("ck_scenario_simulation_runs_valid_scenario_run_status"),
        ),
        sa.CheckConstraint(
            "risk_level IN ('Low', 'Medium', 'High', 'Critical')",
            name=op.f("ck_scenario_simulation_runs_valid_scenario_risk_level"),
        ),
        sa.CheckConstraint(
            "mapped_weight >= 0 AND mapped_weight <= 1 "
            "AND uncovered_weight >= 0 AND uncovered_weight <= 1",
            name=op.f("ck_scenario_simulation_runs_valid_scenario_coverage"),
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 90",
            name=op.f("ck_scenario_simulation_runs_valid_scenario_run_confidence"),
        ),
        sa.CheckConstraint(
            "original_value > 0 AND stressed_value >= 0",
            name=op.f("ck_scenario_simulation_runs_valid_scenario_values"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["scenario_definitions.id"],
            name=op.f("fk_scenario_simulation_runs_definition_id_scenario_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_scenario_simulation_runs_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_scenario_simulation_runs"),
        ),
    )
    op.create_index(
        "ix_scenario_runs_portfolio_asof",
        "scenario_simulation_runs",
        ["portfolio_id", "as_of_date", "created_at"],
        unique=False,
    )
    op.create_table(
        "scenario_asset_impacts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("weight", sa.Numeric(12, 10), nullable=False),
        sa.Column("original_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("factor_return", sa.Numeric(18, 10), nullable=False),
        sa.Column("currency_return", sa.Numeric(18, 10), nullable=False),
        sa.Column("combined_return", sa.Numeric(18, 10), nullable=False),
        sa.Column("return_low", sa.Numeric(18, 10), nullable=False),
        sa.Column("return_high", sa.Numeric(18, 10), nullable=False),
        sa.Column("contribution", sa.Numeric(18, 10), nullable=False),
        sa.Column("stressed_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("mapped", sa.Boolean(), nullable=False),
        sa.Column("factor_contributions", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name=op.f("ck_scenario_asset_impacts_valid_scenario_asset_weight"),
        ),
        sa.CheckConstraint(
            "original_value >= 0 AND stressed_value >= 0",
            name=op.f("ck_scenario_asset_impacts_valid_scenario_asset_values"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["scenario_simulation_runs.id"],
            name=op.f("fk_scenario_asset_impacts_run_id_scenario_simulation_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_id"],
            ["stocks.id"],
            name=op.f("fk_scenario_asset_impacts_stock_id_stocks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_scenario_asset_impacts"),
        ),
        sa.UniqueConstraint(
            "run_id",
            "stock_id",
            name="uq_scenario_asset_impact_run_stock",
        ),
    )


def downgrade() -> None:
    op.drop_table("scenario_asset_impacts")
    op.drop_index(
        "ix_scenario_runs_portfolio_asof",
        table_name="scenario_simulation_runs",
    )
    op.drop_table("scenario_simulation_runs")
    op.drop_index(
        "ix_asset_factor_exposure_lookup",
        table_name="asset_risk_factor_exposures",
    )
    op.drop_table("asset_risk_factor_exposures")
    op.drop_table("scenario_definitions")
    op.drop_table("scenario_risk_factors")
