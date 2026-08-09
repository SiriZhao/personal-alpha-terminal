from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from personal_alpha_terminal.application.manual_execution_service import (
    ManualExecutionOrderService,
    ManualFillSubmission,
)
from personal_alpha_terminal.decision_engine.repository import DecisionRepository
from personal_alpha_terminal.decision_engine.schemas import UserDecision


@dataclass(frozen=True, slots=True)
class CandidateView:
    recommendation_id: str
    ticker: str
    action: str
    current_weight: Decimal
    target_weight: Decimal
    quant_score: Decimal
    confidence_score: Decimal
    evidence_grade: str
    rationale: tuple[str, ...]
    risk_factors: tuple[str, ...]
    model_version: str
    data_version: str
    executable: bool
    blocked_reason: str | None


class DecisionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = DecisionRepository(session)

    def get_action_candidates(self) -> tuple[CandidateView, ...]:
        run = self._repository.latest_run()
        if run is None:
            return ()
        approved = run.status == "generated" and run.gate_status == "APPROVED"
        return tuple(
            CandidateView(
                recommendation_id=item.recommendation_id,
                ticker=item.stock.symbol,
                action=item.action,
                current_weight=item.current_weight,
                target_weight=item.target_weight,
                quant_score=item.quant_score,
                confidence_score=item.confidence_score,
                evidence_grade=item.evidence_grade,
                rationale=tuple(item.rationale),
                risk_factors=tuple(item.risk_factors),
                model_version=run.model_version,
                data_version=run.data_version,
                executable=approved and item.review_status == "pending",
                blocked_reason=None if approved else "; ".join(run.blockers) or run.gate_status,
            )
            for item in run.recommendations
        )

    def review(self, recommendation_id: str, decision: UserDecision, reason: str = "") -> str:
        history = self._repository.review(
            recommendation_id=recommendation_id,
            decision=decision,
            decided_at=datetime.now(UTC),
            reason=reason,
        )
        if decision is UserDecision.ACCEPTED:
            recommendation = self._repository.get_recommendation(recommendation_id)
            if (
                recommendation is not None
                and recommendation.action.upper() in {"BUY", "ADD", "SELL", "REDUCE"}
            ):
                ManualExecutionOrderService(self._session).ensure_order(recommendation)
        return history.decision

    def mark_executed(
        self,
        recommendation_id: str,
        *,
        actual_price: float,
        quantity: float,
        fees: float = 0.0,
        executed_at: datetime | None = None,
        notes: str = "",
        fill_id: str | None = None,
        external_reference: str | None = None,
    ) -> str:
        """Record a fill entered manually at Charles Schwab in the real ledger."""

        recommendation = self._repository.get_recommendation(recommendation_id)
        if recommendation is None:
            raise ValueError("decision recommendation does not exist")
        if recommendation.review_status != "accepted":
            raise ValueError("only an accepted recommendation can be marked executed")
        if recommendation.run.gate_status != "APPROVED":
            raise ValueError("recommendation data gate is not approved")
        if actual_price <= 0 or quantity <= 0 or fees < 0:
            raise ValueError("manual fill price/quantity/fees are invalid")
        timestamp = executed_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("manual fill timestamp must be timezone-aware")
        earliest = recommendation.earliest_execution_time
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=UTC)
        if timestamp.astimezone(UTC) < earliest.astimezone(UTC):
            raise ValueError("manual fill precedes the earliest permitted execution time")
        metrics = ManualExecutionOrderService(self._session).record_fill(
            ManualFillSubmission(
                fill_id=fill_id or f"legacy:{recommendation_id}",
                recommendation_id=recommendation_id,
                quantity=quantity,
                price=actual_price,
                fee=fees,
                executed_at=timestamp,
                external_reference=external_reference,
                notes=notes,
            )
        )
        if metrics.idempotent_replay:
            return (
                f"manual fill already recorded status={metrics.status.value} "
                f"fill_ratio={metrics.fill_ratio:.6f} order_id={metrics.order_id}"
            )
        return (
            f"EXECUTED_MANUALLY status={metrics.status.value} "
            f"fill_ratio={metrics.fill_ratio:.6f} order_id={metrics.order_id}"
        )
