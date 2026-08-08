from __future__ import annotations

from datetime import date

from personal_alpha_terminal.automation.runner import PipelineExecution
from personal_alpha_terminal.automation.service import run_daily_pipeline
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.intelligence.integration import (
    IntegratedDailyInput,
    IntegratedDailyOutput,
    IntegratedIntelligencePipeline,
)
from personal_alpha_terminal.intelligence.service import IntelligenceService
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantOutput,
    DailyQuantPipeline,
)


class PipelineService:
    def __init__(
        self,
        settings: Settings,
        quant_pipeline: DailyQuantPipeline | None = None,
    ) -> None:
        self._settings = settings
        self._quant_pipeline = quant_pipeline or DailyQuantPipeline()

    def run_daily_pipeline(self, as_of_date: date | None = None) -> PipelineExecution:
        return run_daily_pipeline(settings=self._settings, as_of_date=as_of_date, trigger="console")

    def run_quant_decision(self, inputs: DailyQuantInput) -> DailyQuantOutput:
        """Run the only production-safe Alpha-to-decision chain.

        The existing scheduler remains responsible for data and research jobs.
        It cannot synthesize positions; callers must provide fully authorized,
        point-in-time inputs to this deterministic service boundary.
        """

        return self._quant_pipeline.run(inputs)

    def run_integrated_intelligence_decision(
        self,
        inputs: IntegratedDailyInput,
        intelligence_service: IntelligenceService,
    ) -> IntegratedDailyOutput:
        """Run Quant Core, optional research intelligence, then the scanner.

        The scanner receives only Portfolio/Risk-approved proposals. Any critical
        Quant Core failure remains fail-closed; optional Intelligence failures
        degrade explicitly to quant-only research.
        """

        return IntegratedIntelligencePipeline(
            intelligence_service,
            self._quant_pipeline,
        ).run(inputs)
