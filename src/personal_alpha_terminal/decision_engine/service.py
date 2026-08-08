from datetime import datetime

from personal_alpha_terminal.decision_engine.engine import DecisionEngine
from personal_alpha_terminal.decision_engine.repository import DecisionRepository
from personal_alpha_terminal.decision_engine.schemas import (
    DecisionBatch,
    DecisionCandidate,
    UserDecision,
)
from personal_alpha_terminal.models import (
    DecisionHistory,
    QuantDecisionRecommendation,
    QuantDecisionRun,
)
from personal_alpha_terminal.research import ResearchDataAuthorization


class DecisionService:
    def __init__(
        self,
        repository: DecisionRepository,
        engine: DecisionEngine | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine or DecisionEngine()

    def generate(
        self,
        *,
        authorization: ResearchDataAuthorization,
        portfolio_id: int,
        portfolio_value: float,
        candidates: tuple[DecisionCandidate, ...],
        generated_at: datetime,
        earliest_execution_time: datetime,
    ) -> tuple[DecisionBatch, QuantDecisionRun]:
        batch = self.engine.generate(
            authorization=authorization,
            portfolio_id=portfolio_id,
            portfolio_value=portfolio_value,
            candidates=candidates,
            generated_at=generated_at,
            earliest_execution_time=earliest_execution_time,
        )
        return batch, self.repository.save_batch(batch)

    def latest_run(self, portfolio_id: int | None = None) -> QuantDecisionRun | None:
        return self.repository.latest_run(portfolio_id)

    def pending(
        self,
        *,
        now: datetime,
        portfolio_id: int | None = None,
    ) -> tuple[QuantDecisionRecommendation, ...]:
        return self.repository.pending_recommendations(now=now, portfolio_id=portfolio_id)

    def review(
        self,
        *,
        recommendation_id: str,
        decision: UserDecision,
        decided_at: datetime,
        reason: str = "",
    ) -> DecisionHistory:
        return self.repository.review(
            recommendation_id=recommendation_id,
            decision=decision,
            decided_at=decided_at,
            reason=reason,
        )
