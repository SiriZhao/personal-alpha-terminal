import importlib
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.database_health import inspect_database_health
from personal_alpha_terminal.data.migrations import migration_root


def test_postgresql_asset_check_drop_uses_preformatted_constraint_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = importlib.import_module(
        "migrations.versions.0a7c9e4d2b61_portfolio_management_ledger"
    )
    formatted_name = object()
    dropped: list[tuple[object, str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(
        migration.op,
        "f",
        lambda name: formatted_name if name == "ck_stocks_valid_asset_type" else name,
    )
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, *, type_: dropped.append((name, table, type_)),
    )
    monkeypatch.setattr(migration.op, "create_check_constraint", lambda *_args: None)

    migration._replace_asset_check(migration.NEW_ASSET_CHECK)

    assert dropped == [(formatted_name, "stocks", "check")]


def test_market_data_migration_does_not_match_reflected_check_sql() -> None:
    migration = importlib.import_module(
        "migrations.versions.7f2c1d9a6b40_production_market_data_layer"
    )
    source = (
        migration_root()
        .joinpath(
            "migrations",
            "versions",
            "7f2c1d9a6b40_production_market_data_layer.py",
        )
        .read_text(encoding="utf-8")
    )

    assert migration.revision == "7f2c1d9a6b40"
    assert "_legacy_action_type_constraint_name" in source
    assert 'item["sqltext"]' not in source


def test_initial_migration_builds_versioned_schema() -> None:
    root = migration_root()
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    engine = build_engine("sqlite://")
    try:
        with engine.begin() as connection:
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
        tables = set(inspect(engine).get_table_names())
        event_statistic_columns = {
            item["name"] for item in inspect(engine).get_columns("event_study_statistics")
        }
        conditional_columns = {
            item["name"] for item in inspect(engine).get_columns("conditional_probability_results")
        }
        graph_edge_columns = {
            item["name"] for item in inspect(engine).get_columns("market_graph_edges")
        }
        regime_run_columns = {
            item["name"] for item in inspect(engine).get_columns("market_regime_runs")
        }
        regime_observation_columns = {
            item["name"] for item in inspect(engine).get_columns("market_regime_observations")
        }
        portfolio_position_indexes = {
            item["name"] for item in inspect(engine).get_indexes("portfolio_positions")
        }
        graph_edge_indexes = {
            item["name"] for item in inspect(engine).get_indexes("market_graph_edges")
        }
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        health = inspect_database_health(engine)
    finally:
        engine.dispose()

    assert "prices" in tables
    assert "research_reports" in tables
    assert "alpha_discovery_runs" in tables
    assert "alpha_factor_evaluations" in tables
    assert "alpha_combination_results" in tables
    assert "backtest_runs" in tables
    assert "backtest_daily_results" in tables
    assert "backtest_rebalances" in tables
    assert "backtest_summary_metrics" in tables
    assert "scenario_risk_factors" in tables
    assert "asset_risk_factor_exposures" in tables
    assert "scenario_definitions" in tables
    assert "scenario_simulation_runs" in tables
    assert "scenario_asset_impacts" in tables
    assert "market_universe_snapshots" in tables
    assert "market_universe_members" in tables
    assert "exchange_sessions" in tables
    assert "corporate_actions" in tables
    assert "market_data_quality_runs" in tables
    assert "market_data_quality_results" in tables
    assert "daily_pipeline_runs" in tables
    assert "daily_task_runs" in tables
    assert "portfolio_transactions" in tables
    assert "portfolio_allocation_targets" in tables
    assert "provider_capabilities" in tables
    assert {
        "intelligence_raw_information",
        "intelligence_events",
        "intelligence_event_evidence",
        "intelligence_features",
        "intelligence_research_results",
        "intelligence_extraction_cache",
        "intelligence_hypotheses",
        "intelligence_relationships",
        "intelligence_narratives",
        "intelligence_narrative_exposures",
        "intelligence_decision_lineage",
    } <= tables
    assert {
        "meets_minimum",
        "positive_probability_lower",
        "average_return_upper",
    } <= event_statistic_columns
    assert "raw_probability" in conditional_columns
    assert {"p_value", "fdr_q_value", "bonferroni_p_value"} <= graph_edge_columns
    assert {
        "calibration_status",
        "calibration_observation_count",
        "brier_score",
        "calibration_curve",
    } <= regime_run_columns
    assert {
        "risk_on_score",
        "neutral_score",
        "risk_off_score",
        "risk_on_probability",
    } <= regime_observation_columns
    assert "ix_portfolio_positions_stock_id" in portfolio_position_indexes
    assert "ix_market_graph_edges_source_stock_id" in graph_edge_indexes
    assert "ix_market_graph_edges_target_stock_id" in graph_edge_indexes
    assert revision == "b8a2d6f4c901"
    assert not any(table.startswith("paper_") for table in tables)
    assert not health.ready
    assert health.dialect == "sqlite"
    assert health.current_revision == "b8a2d6f4c901"


def test_production_index_migration_round_trip() -> None:
    root = migration_root()
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    engine = build_engine("sqlite://")
    try:
        with engine.begin() as connection:
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
        with engine.begin() as connection:
            configuration.attributes["connection"] = connection
            command.downgrade(configuration, "e19f7b3c4a62")
        downgraded_indexes = {
            item["name"] for item in inspect(engine).get_indexes("market_graph_edges")
        }
        with engine.connect() as connection:
            downgraded_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        with engine.begin() as connection:
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
        upgraded_indexes = {
            item["name"] for item in inspect(engine).get_indexes("market_graph_edges")
        }
        with engine.connect() as connection:
            upgraded_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    assert downgraded_revision == "e19f7b3c4a62"
    assert "ix_market_graph_edges_source_stock_id" not in downgraded_indexes
    assert upgraded_revision == "b8a2d6f4c901"
    assert "ix_market_graph_edges_source_stock_id" in upgraded_indexes
