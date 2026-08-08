from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from personal_alpha_terminal.research.data_gate import GateDecision, GateStatus, ResearchPurpose


class GateLayer(StrEnum):
    APPLICATION_HEALTH = "ApplicationHealth"
    LIVE_MARKET_DATA = "LiveMarketDataGate"
    RESEARCH_DATA = "ResearchDataGate"
    PIT_HISTORICAL_DATA = "PITHistoricalDataGate"
    BACKTEST_DATA = "BacktestDataGate"
    MODEL_VALIDATION = "ModelValidationGate"
    PORTFOLIO_DECISION = "PortfolioDecisionGate"
    ACTION = "ActionGate"


@dataclass(frozen=True, slots=True)
class LayerGateResult:
    layer: GateLayer
    status: GateStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LayeredGateStatus:
    market: str
    results: tuple[LayerGateResult, ...]

    def result(self, layer: GateLayer) -> LayerGateResult:
        return next(item for item in self.results if item.layer is layer)

    @property
    def action_allowed(self) -> bool:
        return self.result(GateLayer.ACTION).status is GateStatus.APPROVED


def classify_layered_gate(
    decisions: dict[ResearchPurpose, GateDecision],
    *,
    market: str,
    application_healthy: bool,
    model_approved: bool,
) -> LayeredGateStatus:
    """Expose independent capabilities without an A/HK/US aggregate score."""

    def from_purpose(layer: GateLayer, purpose: ResearchPurpose) -> LayerGateResult:
        decision = decisions[purpose]
        return LayerGateResult(layer, decision.status, decision.blockers, decision.warnings)

    application = LayerGateResult(
        GateLayer.APPLICATION_HEALTH,
        GateStatus.APPROVED if application_healthy else GateStatus.BLOCKED,
        () if application_healthy else ("application/database health check failed",),
        (),
    )
    display = from_purpose(GateLayer.LIVE_MARKET_DATA, ResearchPurpose.DISPLAY)
    research = from_purpose(GateLayer.RESEARCH_DATA, ResearchPurpose.RESEARCH)
    pit = from_purpose(GateLayer.PIT_HISTORICAL_DATA, ResearchPurpose.BACKTEST)
    backtest = from_purpose(GateLayer.BACKTEST_DATA, ResearchPurpose.BACKTEST)
    model = LayerGateResult(
        GateLayer.MODEL_VALIDATION,
        GateStatus.APPROVED if model_approved else GateStatus.BLOCKED,
        () if model_approved else ("no independently approved model manifest",),
        (),
    )
    portfolio = from_purpose(
        GateLayer.PORTFOLIO_DECISION, ResearchPurpose.PORTFOLIO_DECISION
    )
    action_blockers = tuple(
        blocker
        for item in (application, portfolio, model)
        if item.status is not GateStatus.APPROVED
        for blocker in item.blockers
    )
    action = LayerGateResult(
        GateLayer.ACTION,
        GateStatus.APPROVED if not action_blockers else GateStatus.BLOCKED,
        action_blockers,
        (),
    )
    return LayeredGateStatus(
        market,
        (application, display, research, pit, backtest, model, portfolio, action),
    )
