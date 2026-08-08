from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from personal_alpha_terminal.analysis.conditional_probability.repository import (
    ConditionalProbabilityRepository,
)
from personal_alpha_terminal.analysis.conditional_probability.service import (
    ConditionalProbabilityService,
)
from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.analysis.factors.repository import FactorResearchRepository
from personal_alpha_terminal.analysis.factors.service import FactorResearchService
from personal_alpha_terminal.analysis.lead_lag.repository import LeadLagRepository
from personal_alpha_terminal.analysis.lead_lag.service import LeadLagAnalysisService
from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.service import MarketGraphService
from personal_alpha_terminal.analysis.market_regime.repository import (
    MarketRegimeRepository,
)
from personal_alpha_terminal.analysis.market_regime.service import MarketRegimeService
from personal_alpha_terminal.analysis.relationships.repository import RelationshipRepository
from personal_alpha_terminal.analysis.relationships.service import (
    RelationshipAnalysisService,
)
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.dashboard.home import HomeDashboardRepository
from personal_alpha_terminal.dashboard.repository import DashboardRepository
from personal_alpha_terminal.dashboard.service import DashboardService
from personal_alpha_terminal.data.database import (
    get_engine,
    get_session_factory,
    session_scope,
)
from personal_alpha_terminal.decision_engine import DecisionRepository, DecisionService
from personal_alpha_terminal.portfolio.position_import import PositionImportService
from personal_alpha_terminal.portfolio.repository import PortfolioRiskRepository
from personal_alpha_terminal.portfolio.service import PortfolioRiskService
from personal_alpha_terminal.reports.service import ResearchReportService
from personal_alpha_terminal.scenario_simulator.repository import ScenarioRepository
from personal_alpha_terminal.scenario_simulator.service import ScenarioService
from personal_alpha_terminal.strategies.us_adaptive_alpha.service import (
    USAdaptiveAlphaService,
)


def database_ready() -> bool:
    try:
        inspector = inspect(get_engine())
        return inspector.has_table("security_master") and inspector.has_table("prices")
    except (OSError, SQLAlchemyError):
        return False


def relationship_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "relationship_analysis_runs",
            "relationship_correlations",
            "relationship_anomalies",
        )
    )


def event_study_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "event_definitions",
            "event_study_runs",
            "event_occurrences",
            "event_study_observations",
            "event_study_statistics",
        )
    )


def conditional_probability_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "conditional_probability_runs",
            "conditional_probability_results",
        )
    )


def market_graph_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "market_graph_runs",
            "market_graph_nodes",
            "market_graph_edges",
            "market_graph_paths",
        )
    )


def lead_lag_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "lead_lag_analysis_runs",
            "lead_lag_pair_results",
            "lead_lag_metrics",
        )
    )


def market_regime_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "market_regime_runs",
            "market_regime_observations",
        )
    )


def factor_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "financial_per_share_metrics",
            "factor_research_runs",
            "factor_scores",
            "factor_backtest_periods",
            "factor_backtest_summaries",
        )
    )


def portfolio_risk_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "fx_rates",
            "portfolio_risk_runs",
            "portfolio_risk_metrics",
            "portfolio_stress_results",
        )
    )


def scenario_database_ready() -> bool:
    inspector = inspect(get_engine())
    return all(
        inspector.has_table(table_name)
        for table_name in (
            "scenario_risk_factors",
            "asset_risk_factor_exposures",
            "scenario_definitions",
            "scenario_simulation_runs",
            "scenario_asset_impacts",
            "research_reports",
        )
    )


def decision_database_ready() -> bool:
    try:
        inspector = inspect(get_engine())
        return all(
            inspector.has_table(table_name)
            for table_name in (
                "quant_decision_runs",
                "quant_decision_recommendations",
                "decision_history",
            )
        )
    except (OSError, SQLAlchemyError):
        return False


@contextmanager
def dashboard_service() -> Generator[DashboardService, None, None]:
    with get_session_factory()() as session:
        yield DashboardService(
            DashboardRepository(session),
            get_settings(),
        )


@contextmanager
def home_dashboard_repository() -> Generator[HomeDashboardRepository, None, None]:
    with get_session_factory()() as session:
        yield HomeDashboardRepository(session)


@contextmanager
def decision_service() -> Generator[DecisionService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield DecisionService(DecisionRepository(session))


@contextmanager
def position_import_service() -> Generator[PositionImportService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield PositionImportService(session)


@contextmanager
def relationship_service() -> Generator[RelationshipAnalysisService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield RelationshipAnalysisService(
            RelationshipRepository(session),
            get_settings(),
        )


@contextmanager
def event_study_service() -> Generator[EventStudyService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield EventStudyService(
            EventStudyRepository(session),
            get_settings(),
        )


@contextmanager
def conditional_probability_service() -> Generator[
    ConditionalProbabilityService,
    None,
    None,
]:
    with session_scope(get_session_factory()) as session:
        yield ConditionalProbabilityService(
            ConditionalProbabilityRepository(session),
            get_settings(),
        )


@contextmanager
def market_graph_service() -> Generator[MarketGraphService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield MarketGraphService(
            MarketGraphRepository(session),
            get_settings(),
        )


@contextmanager
def lead_lag_service() -> Generator[LeadLagAnalysisService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield LeadLagAnalysisService(
            LeadLagRepository(session),
            get_settings(),
        )


@contextmanager
def market_regime_service() -> Generator[MarketRegimeService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield MarketRegimeService(
            MarketRegimeRepository(session),
            get_settings(),
        )


@contextmanager
def factor_research_service() -> Generator[FactorResearchService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield FactorResearchService(
            FactorResearchRepository(session),
            get_settings(),
        )


@contextmanager
def portfolio_risk_service() -> Generator[PortfolioRiskService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield PortfolioRiskService(
            PortfolioRiskRepository(session),
            get_settings(),
        )


@contextmanager
def scenario_service() -> Generator[ScenarioService, None, None]:
    with session_scope(get_session_factory()) as session:
        yield ScenarioService(
            ScenarioRepository(session),
            ResearchReportService(session),
        )


@contextmanager
def us_adaptive_alpha_service() -> Generator[USAdaptiveAlphaService, None, None]:
    with get_session_factory()() as session:
        yield USAdaptiveAlphaService(session)
