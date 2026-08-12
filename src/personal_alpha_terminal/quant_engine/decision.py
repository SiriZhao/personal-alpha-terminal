from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioTarget
from personal_alpha_terminal.quant_engine.portfolio.trades import TradeProposal
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchPurpose,
)


class ProductionDecisionStatus(StrEnum):
    READY = "READY"
    NO_VALID_TRADE = "NO_VALID_TRADE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ProductionDecision:
    status: ProductionDecisionStatus
    as_of: datetime
    current_portfolio: dict[str, float]
    target_portfolio: dict[str, float]
    proposals: tuple[TradeProposal, ...]
    model_version: str
    data_version: str
    data_quality: str
    blockers: tuple[str, ...]
    manual_confirmation_required: bool = True
    automatic_execution_allowed: bool = False


class ProductionDecisionEngine:
    """Explains a validated portfolio difference; it never creates a strategy."""

    def generate(
        self,
        *,
        authorization: ResearchDataAuthorization,
        target: PortfolioTarget,
        current_weights: dict[str, float],
        proposals: tuple[TradeProposal, ...],
        as_of: datetime,
    ) -> ProductionDecision:
        if as_of.tzinfo is None:
            raise ValueError("decision time must be timezone-aware")
        if not authorization.permits(ResearchPurpose.PORTFOLIO_DECISION):
            return ProductionDecision(
                ProductionDecisionStatus.BLOCKED,
                as_of,
                current_weights,
                {},
                (),
                target.model_version,
                target.data_version,
                authorization.decision.status.value,
                authorization.decision.blockers,
            )
        if not target.operational_approved:
            return ProductionDecision(
                ProductionDecisionStatus.BLOCKED,
                as_of,
                current_weights,
                {},
                (),
                target.model_version,
                target.data_version,
                "BLOCKED",
                target.blockers,
            )
        actionable = tuple(item for item in proposals if item.delta_weight != 0)
        return ProductionDecision(
            (
                ProductionDecisionStatus.READY
                if actionable
                else ProductionDecisionStatus.NO_VALID_TRADE
            ),
            as_of,
            dict(current_weights),
            dict(target.target_weights),
            proposals,
            target.model_version,
            target.data_version,
            "VALID",
            (),
        )
