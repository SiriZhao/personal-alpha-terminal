from dataclasses import replace

from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.reports.service import ResearchReportService
from personal_alpha_terminal.scenario_simulator.catalog import (
    RISK_FACTORS,
    direct_proxy_exposures,
)
from personal_alpha_terminal.scenario_simulator.engine import ScenarioEngine
from personal_alpha_terminal.scenario_simulator.report import (
    render_scenario_report,
)
from personal_alpha_terminal.scenario_simulator.repository import (
    ScenarioRepository,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioPortfolio,
    ScenarioResult,
)


class ScenarioService:
    """Load validated portfolio snapshots, simulate, persist, and report."""

    def __init__(
        self,
        repository: ScenarioRepository,
        report_service: ResearchReportService,
        engine: ScenarioEngine | None = None,
    ) -> None:
        self._repository = repository
        self._report_service = report_service
        self._engine = engine or ScenarioEngine()

    def register_exposures(
        self,
        exposures: tuple[AssetFactorExposure, ...],
    ) -> None:
        self._repository.save_exposures(exposures, RISK_FACTORS)

    def mapping_snapshot(
        self,
        portfolio_id: int,
    ) -> tuple[ScenarioPortfolio, tuple[AssetFactorExposure, ...]]:
        """Return the exact portfolio snapshot and mappings used by simulations."""

        self._repository.ensure_factors(RISK_FACTORS)
        portfolio = self._repository.load_latest_portfolio(portfolio_id)
        return portfolio, self._merged_exposures(portfolio, ())

    def run_latest(
        self,
        *,
        portfolio_id: int,
        scenario: ScenarioDefinition,
        exposure_overrides: tuple[AssetFactorExposure, ...] = (),
    ) -> tuple[ScenarioResult, ReportDocument]:
        portfolio = self._repository.load_latest_portfolio(portfolio_id)
        return self.run(
            portfolio,
            scenario,
            exposure_overrides=exposure_overrides,
        )

    def run(
        self,
        portfolio: ScenarioPortfolio,
        scenario: ScenarioDefinition,
        *,
        exposure_overrides: tuple[AssetFactorExposure, ...] = (),
    ) -> tuple[ScenarioResult, ReportDocument]:
        self._repository.ensure_factors(RISK_FACTORS)
        exposures = self._merged_exposures(portfolio, exposure_overrides)
        draft = self._engine.simulate(
            portfolio,
            scenario,
            factors=RISK_FACTORS,
            exposures=exposures,
        )
        definition = self._repository.save_definition(scenario)
        run = self._repository.save_result(draft, definition)
        result = replace(draft, run_id=run.id)
        report = render_scenario_report(result)
        self._report_service.save(report)
        return result, report

    def compare_latest(
        self,
        *,
        portfolio_id: int,
        scenarios: tuple[ScenarioDefinition, ...],
        exposure_overrides: tuple[AssetFactorExposure, ...] = (),
    ) -> ScenarioComparison:
        if not 1 <= len(scenarios) <= 20:
            raise ValueError("scenario comparison requires between 1 and 20 scenarios")
        names = [item.name for item in scenarios]
        if len(names) != len(set(names)):
            raise ValueError("scenario comparison names must be unique")
        results = tuple(
            self.run_latest(
                portfolio_id=portfolio_id,
                scenario=scenario,
                exposure_overrides=exposure_overrides,
            )[0]
            for scenario in scenarios
        )
        return ScenarioComparison(
            portfolio_id=portfolio_id,
            as_of_date=results[0].as_of_date,
            results=results,
        )

    def _merged_exposures(
        self,
        portfolio: ScenarioPortfolio,
        overrides: tuple[AssetFactorExposure, ...],
    ) -> tuple[AssetFactorExposure, ...]:
        stock_ids = tuple(item.instrument.id for item in portfolio.positions)
        stored = self._repository.load_exposures(
            stock_ids=stock_ids,
            as_of_date=portfolio.as_of_date,
        )
        identity = tuple(
            exposure
            for position in portfolio.positions
            for exposure in direct_proxy_exposures(
                asset_id=position.instrument.id,
                symbol=position.instrument.symbol,
                as_of_date=portfolio.as_of_date,
            )
        )
        merged: dict[tuple[int, str], AssetFactorExposure] = {
            (item.asset_id, item.factor_code): item for item in identity
        }
        merged.update({(item.asset_id, item.factor_code): item for item in stored})
        merged.update({(item.asset_id, item.factor_code): item for item in overrides})
        return tuple(merged[key] for key in sorted(merged))
