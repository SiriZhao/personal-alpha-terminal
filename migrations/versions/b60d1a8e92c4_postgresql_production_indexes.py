"""add PostgreSQL production foreign-key indexes

Revision ID: b60d1a8e92c4
Revises: e19f7b3c4a62
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b60d1a8e92c4"
down_revision: str | None = "e19f7b3c4a62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_asset_risk_factor_exposures_factor_id",
        "asset_risk_factor_exposures",
        ("factor_id",),
    ),
    (
        "ix_conditional_probability_results_target_stock_id",
        "conditional_probability_results",
        ("target_stock_id",),
    ),
    ("ix_event_study_runs_trigger_stock_id", "event_study_runs", ("trigger_stock_id",)),
    (
        "ix_event_study_statistics_target_stock_id",
        "event_study_statistics",
        ("target_stock_id",),
    ),
    ("ix_events_stock_id", "events", ("stock_id",)),
    ("ix_factor_scores_stock_id", "factor_scores", ("stock_id",)),
    ("ix_industries_parent_id", "industries", ("parent_id",)),
    (
        "ix_lead_lag_pair_results_source_stock_id",
        "lead_lag_pair_results",
        ("source_stock_id",),
    ),
    (
        "ix_lead_lag_pair_results_target_stock_id",
        "lead_lag_pair_results",
        ("target_stock_id",),
    ),
    (
        "ix_market_data_quality_results_stock_id",
        "market_data_quality_results",
        ("stock_id",),
    ),
    ("ix_market_graph_edges_source_stock_id", "market_graph_edges", ("source_stock_id",)),
    ("ix_market_graph_edges_target_stock_id", "market_graph_edges", ("target_stock_id",)),
    ("ix_market_graph_nodes_stock_id", "market_graph_nodes", ("stock_id",)),
    ("ix_market_regime_runs_vix_stock_id", "market_regime_runs", ("vix_stock_id",)),
    ("ix_market_regime_runs_rate_stock_id", "market_regime_runs", ("rate_stock_id",)),
    (
        "ix_market_regime_runs_dollar_stock_id",
        "market_regime_runs",
        ("dollar_stock_id",),
    ),
    (
        "ix_market_regime_runs_benchmark_stock_id",
        "market_regime_runs",
        ("benchmark_stock_id",),
    ),
    ("ix_market_universe_members_stock_id", "market_universe_members", ("stock_id",)),
    ("ix_portfolio_positions_stock_id", "portfolio_positions", ("stock_id",)),
    (
        "ix_portfolio_risk_runs_benchmark_stock_id",
        "portfolio_risk_runs",
        ("benchmark_stock_id",),
    ),
    ("ix_scenario_asset_impacts_stock_id", "scenario_asset_impacts", ("stock_id",)),
    (
        "ix_scenario_simulation_runs_definition_id",
        "scenario_simulation_runs",
        ("definition_id",),
    ),
)


def upgrade() -> None:
    for index_name, table_name, columns in INDEXES:
        op.create_index(index_name, table_name, list(columns), unique=False)


def downgrade() -> None:
    for index_name, table_name, _columns in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
