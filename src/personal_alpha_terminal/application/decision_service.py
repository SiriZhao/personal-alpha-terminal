from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from personal_alpha_terminal.decision_engine.repository import DecisionRepository
from personal_alpha_terminal.decision_engine.schemas import UserDecision
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)
from personal_alpha_terminal.portfolio.management_schemas import TransactionDraft
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSession,
    MarketSessionCalendar,
)


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
        action = recommendation.action.upper()
        if action not in {"BUY", "ADD", "SELL", "REDUCE"}:
            raise ValueError(f"{action} has no executable fill")
        transaction_type = "buy" if action in {"BUY", "ADD"} else "sell"
        calendar = MarketSessionCalendar()
        market_state = calendar.classify(timestamp)
        if market_state.session in {MarketSession.CLOSED, MarketSession.MAINTENANCE}:
            raise ValueError("manual fill timestamp is outside an eligible US trading session")
        trade_date = market_state.trade_date
        settlement_date = calendar.next_trading_day(trade_date)
        draft = TransactionDraft(
            transaction_type=transaction_type,
            trade_date=trade_date,
            settlement_date=settlement_date,
            currency=recommendation.stock.currency,
            fx_rate_to_base=1.0,
            event_time=timestamp,
            available_time=timestamp,
            stock_id=recommendation.stock_id,
            quantity=quantity,
            unit_price=actual_price,
            fee_amount=fees,
            source="manual_charles_schwab",
            external_id=f"decision:{recommendation_id}",
            notes=(
                f"Manual Charles Schwab fill; recommendation={recommendation_id}. "
                f"{notes.strip()}"
            ).strip(),
        )
        repository = PortfolioManagementRepository(self._session)
        external_id = f"decision:{recommendation_id}"
        existing = repository.transaction_by_external_id(
            portfolio_id=recommendation.run.portfolio_id,
            source="manual_charles_schwab",
            external_id=external_id,
        )
        if existing is not None:
            return f"EXECUTED_MANUALLY transaction_id={existing.id} (already recorded)"
        transaction = repository.add_transaction(
            portfolio_id=recommendation.run.portfolio_id,
            draft=draft,
        )
        repository.apply_trade_to_current_snapshot(
            portfolio_id=recommendation.run.portfolio_id,
            stock_id=recommendation.stock_id,
            as_of_date=trade_date,
            transaction_type=transaction_type,
            quantity=Decimal(str(quantity)),
            unit_price=Decimal(str(actual_price)),
            fee_amount=Decimal(str(fees)),
            currency=recommendation.stock.currency,
        )
        return f"EXECUTED_MANUALLY transaction_id={transaction.id}"
