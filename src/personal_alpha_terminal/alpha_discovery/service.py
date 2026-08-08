from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import date, timedelta

from personal_alpha_terminal.alpha_discovery.alpha_report import (
    render_alpha_research_report,
)
from personal_alpha_terminal.alpha_discovery.factor_generator import (
    FACTOR_LIBRARY,
    build_rebalance_dates,
    generate_factor_panel,
)
from personal_alpha_terminal.alpha_discovery.factor_selector import (
    discover_factor_combinations,
)
from personal_alpha_terminal.alpha_discovery.repository import (
    AlphaDiscoveryRepository,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryConfig,
    AlphaDiscoveryResult,
    FactorDefinition,
    MarketEnvironmentPoint,
)
from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.analysis.factors.schemas import FactorDataset
from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.reports.service import ResearchReportService


class AlphaDiscoveryService:
    """Orchestrate reproducible point-in-time discovery and persistence."""

    def __init__(
        self,
        factor_repository: FactorResearchRepository,
        alpha_repository: AlphaDiscoveryRepository,
        report_service: ResearchReportService,
    ) -> None:
        self._factor_repository = factor_repository
        self._alpha_repository = alpha_repository
        self._report_service = report_service

    def run_from_database(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
        config: AlphaDiscoveryConfig,
        environment: Sequence[MarketEnvironmentPoint] = (),
        definitions: Sequence[FactorDefinition] = FACTOR_LIBRARY,
    ) -> tuple[AlphaDiscoveryResult, ReportDocument]:
        query_start = start_date - timedelta(days=800)
        dataset = self._factor_repository.load_dataset(
            market=market,
            query_start_date=query_start,
            end_date=end_date + timedelta(days=config.horizon_days * 3),
            include_inactive=True,
            maximum_universe_size=config.maximum_universe_size,
        )
        return self.run(
            dataset,
            market=market,
            start_date=start_date,
            end_date=end_date,
            config=config,
            environment=environment,
            definitions=definitions,
            data_sources=(
                "prices:selected_consistent_provider:adjusted_and_raw_close",
                "financials:point_in_time_available_at",
                "stocks:historical_eligibility_fields",
                *(("market_environment:caller_supplied_point_in_time",) if environment else ()),
            ),
        )

    def run(
        self,
        dataset: FactorDataset,
        *,
        market: str,
        start_date: date,
        end_date: date,
        config: AlphaDiscoveryConfig,
        environment: Sequence[MarketEnvironmentPoint] = (),
        definitions: Sequence[FactorDefinition] = FACTOR_LIBRARY,
        data_sources: tuple[str, ...],
    ) -> tuple[AlphaDiscoveryResult, ReportDocument]:
        dates = build_rebalance_dates(
            dataset,
            start_date=start_date,
            end_date=end_date,
            interval=config.rebalance_interval,
            minimum_cross_section=config.minimum_cross_section,
        )
        panel = generate_factor_panel(
            dataset,
            market=market,
            rebalance_dates=dates,
            horizon_days=config.horizon_days,
            minimum_cross_section=config.minimum_cross_section,
            definitions=definitions,
            environment=environment,
            environment_max_staleness_days=config.environment_max_staleness_days,
        )
        if not panel.observations:
            raise ValueError("no complete point-in-time factor observations")
        selected = discover_factor_combinations(panel, config)
        draft = AlphaDiscoveryResult(
            run_id=None,
            market=market,
            start_date=start_date,
            end_date=end_date,
            horizon_days=config.horizon_days,
            data_fingerprint=panel.data_fingerprint,
            split=selected.split,
            factor_evaluations=selected.factor_evaluations,
            combinations=selected.combinations,
            tested_factor_count=selected.tested_factor_count,
            tested_combination_count=selected.tested_combination_count,
        )
        run = self._alpha_repository.create_run(draft, config)
        result = replace(draft, run_id=run.id)
        try:
            self._alpha_repository.save_evaluations(
                run.id,
                result.factor_evaluations,
            )
            self._alpha_repository.save_combinations(
                run.id,
                result.combinations,
            )
            report = render_alpha_research_report(
                result,
                data_sources=data_sources,
            )
            self._report_service.save(report)
            self._alpha_repository.mark_completed(run)
            return result, report
        except Exception as error:
            self._alpha_repository.mark_failed(run, error)
            raise


def config_parameters(config: AlphaDiscoveryConfig) -> dict[str, object]:
    """Expose stable JSON-compatible parameters for audit tooling."""

    return dict(asdict(config))
