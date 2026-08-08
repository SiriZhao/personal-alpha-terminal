from dataclasses import replace
from datetime import date, datetime

from personal_alpha_terminal.backtest.engine import BacktestEngine
from personal_alpha_terminal.backtest.report import render_strategy_report
from personal_alpha_terminal.backtest.repository import BacktestRepository
from personal_alpha_terminal.backtest.schemas import (
    BacktestConfig,
    BacktestDataset,
    BacktestResult,
)
from personal_alpha_terminal.backtest.strategy import BacktestStrategy
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.reports.service import ResearchReportService
from personal_alpha_terminal.research import (
    ResearchDataGateService,
    ResearchDataRequest,
    ResearchPurpose,
)


class BacktestService:
    """Run, persist, and report a deterministic backtest as one unit of work."""

    def __init__(
        self,
        repository: BacktestRepository,
        report_service: ResearchReportService,
        engine: BacktestEngine | None = None,
    ) -> None:
        self._repository = repository
        self._report_service = report_service
        self._engine = engine or BacktestEngine()

    def run(
        self,
        dataset: BacktestDataset,
        strategy: BacktestStrategy,
        config: BacktestConfig,
    ) -> tuple[BacktestResult, ReportDocument]:
        draft = self._engine.run(dataset, strategy, config)
        run = self._repository.save(draft, config)
        result = replace(draft, run_id=run.id)
        report = render_strategy_report(
            result,
            config,
            data_sources=dataset.data_sources,
        )
        self._report_service.save(report)
        return result, report

    def run_from_database(
        self,
        *,
        market: str,
        universe_snapshot_id: int | None = None,
        decision_time: datetime,
        strategy: BacktestStrategy,
        config: BacktestConfig,
        calendar: tuple[date, ...],
        calendar_source: str,
        universe_snapshot_ids: tuple[int, ...] | None = None,
    ) -> tuple[BacktestResult, ReportDocument]:
        snapshot_ids = universe_snapshot_ids or (
            (universe_snapshot_id,) if universe_snapshot_id is not None else ()
        )
        if not snapshot_ids:
            raise ValueError("backtest requires at least one PIT universe snapshot")
        gate = ResearchDataGateService(self._repository.session)
        for snapshot_id in snapshot_ids:
            authorization = gate.authorize(
                ResearchDataRequest(
                    purpose=ResearchPurpose.BACKTEST,
                    market=market,
                    asset_type="stock",
                    start_date=config.start_date,
                    end_date=config.end_date,
                    decision_time=decision_time,
                    adjustment_mode=AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
                    universe_snapshot_id=str(snapshot_id),
                )
            )
            if not authorization.permits(ResearchPurpose.BACKTEST):
                raise RuntimeError(
                    f"backtest authorization was not approved for snapshot {snapshot_id}"
                )
        universe_timeline = self._repository.load_universe_timeline(
            snapshot_ids,
            market=market,
        )
        asset_ids = tuple(
            sorted({asset_id for point in universe_timeline for asset_id in point.asset_ids})
        )
        dataset = self._repository.load_dataset(
            market=market,
            asset_ids=asset_ids,
            start_date=config.start_date,
            end_date=config.end_date,
            calendar=calendar,
            calendar_source=calendar_source,
            universe_timeline=universe_timeline,
        )
        return self.run(dataset, strategy, replace(config, require_pit_universe=True))
