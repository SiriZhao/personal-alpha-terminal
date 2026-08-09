from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.models import Industry, Price, Stock

EXPECTED_TABLES = {
    "alpha_combination_results",
    "alpha_discovery_runs",
    "alpha_factor_evaluations",
    "backtest_daily_results",
    "backtest_rebalances",
    "backtest_runs",
    "backtest_run_manifests",
    "backtest_summary_metrics",
    "conditional_probability_results",
    "conditional_probability_runs",
    "corporate_actions",
    "daily_pipeline_runs",
    "daily_task_runs",
    "data_snapshot_manifests",
    "decision_history",
    "exchange_sessions",
    "events",
    "event_definitions",
    "event_occurrences",
    "event_study_observations",
    "event_study_runs",
    "event_study_statistics",
    "financials",
    "fundamental_vintages",
    "financial_per_share_metrics",
    "factor_backtest_periods",
    "factor_backtest_summaries",
    "factor_research_runs",
    "factor_scores",
    "industries",
    "intelligence_event_evidence",
    "intelligence_events",
    "intelligence_extraction_cache",
    "intelligence_features",
    "intelligence_raw_information",
    "intelligence_research_results",
    "intelligence_hypotheses",
    "intelligence_relationships",
    "intelligence_narratives",
    "intelligence_narrative_exposures",
    "intelligence_decision_lineage",
    "lead_lag_analysis_runs",
    "lead_lag_metrics",
    "lead_lag_pair_results",
    "market_graph_edges",
    "market_graph_nodes",
    "market_graph_paths",
    "market_graph_runs",
    "market_data_quality_results",
    "market_data_quality_runs",
    "market_regime_observations",
    "market_regime_runs",
    "market_universe_members",
    "market_universe_snapshots",
    "manual_rebalance_fills",
    "manual_execution_records",
    "manual_execution_orders_v2",
    "manual_execution_fills_v2",
    "manual_rebalance_tickets",
    "model_registry",
    "pit_total_return_versions",
    "portfolio_positions",
    "portfolio_allocation_targets",
    "portfolio_transactions",
    "portfolio_risk_metrics",
    "portfolio_risk_runs",
    "portfolio_stress_results",
    "portfolios",
    "prices",
    "provider_capabilities",
    "quant_decision_recommendations",
    "quant_decision_runs",
    "relationship_analysis_runs",
    "relationship_anomalies",
    "relationship_correlations",
    "research_reports",
    "research_data_certifications",
    "signals",
    "scenario_asset_impacts",
    "scenario_definitions",
    "scenario_risk_factors",
    "scenario_simulation_runs",
    "asset_risk_factor_exposures",
    "security_master",
    "security_identifier_history",
    "fx_rates",
    "security_symbol_aliases",
    "security_listing_history",
    "security_delisting_history",
    "universe_definitions",
    "universe_memberships",
    "security_trading_status",
    "pit_total_return_points",
    "model_approval_records",
    "quant_experiments",
    "quant_experiment_results",
    "portfolio_reconciliations",
}


def test_database_contains_phase_one_tables(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES


def test_production_market_reference_tables_expose_point_in_time_contracts(
    engine: Engine,
) -> None:
    inspector = inspect(engine)
    security_columns = {item["name"] for item in inspector.get_columns("security_master")}
    assert {
        "symbol",
        "market",
        "exchange",
        "currency",
        "timezone",
        "listing_date",
        "delisting_date",
        "security_type",
        "is_active",
        "source",
        "provider",
        "available_time",
        "ingested_time",
    } <= security_columns
    calendar_columns = {item["name"] for item in inspector.get_columns("exchange_sessions")}
    assert {"session_date", "is_open", "open_time", "close_time", "timezone"} <= (calendar_columns)
    action_columns = {item["name"] for item in inspector.get_columns("corporate_actions")}
    assert {
        "effective_date",
        "announcement_date",
        "available_date",
        "event_time",
        "available_time",
        "ingested_time",
    } <= action_columns


def test_sqlite_foreign_keys_are_enabled(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_foreign_key_rejects_orphan_market_data(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError), session_scope(session_factory) as session:
        session.add(
            Price(
                stock_id=999_999,
                trade_date=date(2026, 7, 29),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                source="orphan-test",
            )
        )

    with session_factory() as session:
        assert session.query(Price).filter_by(source="orphan-test").count() == 0


def test_session_scope_persists_related_market_data(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        industry = Industry(taxonomy="GICS", code="45", name="Information Technology")
        stock = Stock(
            canonical_code="US:XNAS:NVDA",
            symbol="NVDA",
            name="NVIDIA Corporation",
            market="US",
            exchange="XNAS",
            currency="USD",
            timezone="America/New_York",
            industry=industry,
        )
        stock.prices.append(
            Price(
                trade_date=date(2026, 7, 29),
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("99"),
                close=Decimal("104"),
                adjusted_close=Decimal("104"),
                volume=1_000_000,
                source="test",
            )
        )
        session.add(stock)

    with session_factory() as session:
        assert session.query(Stock).filter_by(symbol="NVDA").one().prices[0].close == Decimal(
            "104.000000"
        )


def test_price_uniqueness_constraint_is_enforced(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        stock = Stock(
            canonical_code="HK:XHKG:00700",
            symbol="00700",
            name="Tencent Holdings",
            market="HK",
            exchange="XHKG",
            currency="HKD",
            timezone="Asia/Hong_Kong",
        )
        session.add(stock)

    values = {
        "stock_id": stock.id,
        "trade_date": date(2026, 7, 29),
        "open": Decimal("500"),
        "high": Decimal("510"),
        "low": Decimal("495"),
        "close": Decimal("505"),
        "source": "test",
    }
    with pytest.raises(IntegrityError), session_scope(session_factory) as session:
        session.add_all([Price(**values), Price(**values)])

    with session_factory() as session:
        assert session.query(Price).filter_by(source="test").count() == 0
