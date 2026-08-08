from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from personal_alpha_terminal.intelligence.event_study import EventStudyStatistic
from personal_alpha_terminal.intelligence.research_service import (
    PhaseBResearchInput,
    PhaseBResearchOutput,
)
from personal_alpha_terminal.intelligence.scanner import OpportunityCandidate, ScannerMode
from personal_alpha_terminal.intelligence.service import IntelligenceService
from personal_alpha_terminal.quant_engine.probability import ConditionalProbability2
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantOutput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)


class IntegratedPipelineStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class IntegratedDailyInput:
    quant: DailyQuantInput
    research: PhaseBResearchInput
    probability_by_symbol: dict[str, ConditionalProbability2]
    event_statistics_by_symbol: dict[str, EventStudyStatistic]
    risk_flags_by_symbol: dict[str, tuple[str, ...]]
    portfolio_constraints_by_symbol: dict[str, tuple[str, ...]]
    scanner_mode: ScannerMode = ScannerMode.QUANT_FULL_VALIDATED_INTELLIGENCE
    ai_ready: bool = False


@dataclass(frozen=True, slots=True)
class IntegratedDailyOutput:
    status: IntegratedPipelineStatus
    quant: DailyQuantOutput
    research: PhaseBResearchOutput | None
    candidates: tuple[OpportunityCandidate, ...]
    blockers: tuple[str, ...]
    intelligence_mode_used: ScannerMode


class IntegratedIntelligencePipeline:
    """Quant Core first; optional intelligence cannot bypass Portfolio/Risk."""

    def __init__(
        self,
        intelligence_service: IntelligenceService,
        quant_pipeline: DailyQuantPipeline | None = None,
    ) -> None:
        self.intelligence_service = intelligence_service
        self.quant_pipeline = quant_pipeline or DailyQuantPipeline()

    def run(self, inputs: IntegratedDailyInput) -> IntegratedDailyOutput:
        quant = self.quant_pipeline.run(inputs.quant)
        if quant.status is not ProductionPipelineStatus.READY:
            return IntegratedDailyOutput(
                IntegratedPipelineStatus.BLOCKED,
                quant,
                None,
                (),
                quant.blockers or ("Quant Core, Portfolio, or Risk Engine blocked",),
                ScannerMode.QUANT_ONLY,
            )
        if inputs.research.data_cutoff > inputs.quant.decision_time:
            return IntegratedDailyOutput(
                IntegratedPipelineStatus.BLOCKED,
                quant,
                None,
                (),
                ("intelligence data_cutoff follows the daily decision time",),
                ScannerMode.QUANT_ONLY,
            )

        research: PhaseBResearchOutput | None
        mode = inputs.scanner_mode
        blockers: list[str] = []
        try:
            research = self.intelligence_service.run_phase_b_research(inputs.research)
            blockers.extend(research.blockers)
        except (ArithmeticError, RuntimeError, ValueError) as error:
            # Optional research failures cannot suppress the deterministic Quant Core.
            research = None
            mode = ScannerMode.QUANT_ONLY
            blockers.append(f"intelligence degraded to quant-only: {error}")

        try:
            candidates = self.intelligence_service.scan(
                authorization=inputs.quant.authorization,
                alpha_signals=inputs.quant.alpha_signals,
                proposals=quant.trades,
                probability_by_symbol=inputs.probability_by_symbol,
                event_statistics_by_symbol=inputs.event_statistics_by_symbol,
                current_weights=inputs.quant.current_weights,
                risk_flags_by_symbol=inputs.risk_flags_by_symbol,
                mode=mode,
                ai_ready=inputs.ai_ready,
                as_of=inputs.quant.decision_time,
                research_features_by_symbol=(
                    research.research_features_by_symbol if research is not None else {}
                ),
                lineage_by_symbol=(research.lineage_by_symbol if research is not None else {}),
                portfolio_constraints_by_symbol=(
                    inputs.portfolio_constraints_by_symbol
                ),
            )
        except (ArithmeticError, RuntimeError, ValueError) as error:
            return IntegratedDailyOutput(
                IntegratedPipelineStatus.BLOCKED,
                quant,
                research,
                (),
                (*blockers, f"opportunity scanner failed safely: {error}"),
                mode,
            )
        status = (
            IntegratedPipelineStatus.READY
            if research is not None and not blockers
            else IntegratedPipelineStatus.DEGRADED
        )
        return IntegratedDailyOutput(
            status,
            quant,
            research,
            candidates,
            tuple(dict.fromkeys(blockers)),
            mode,
        )
