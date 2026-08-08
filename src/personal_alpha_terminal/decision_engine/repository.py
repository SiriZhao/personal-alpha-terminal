from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.decision_engine.schemas import (
    DecisionBatch,
    UserDecision,
)
from personal_alpha_terminal.models import (
    DecisionHistory,
    Portfolio,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    Stock,
)


class DecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_batch(self, batch: DecisionBatch) -> QuantDecisionRun:
        existing = self.session.scalar(
            select(QuantDecisionRun)
            .options(selectinload(QuantDecisionRun.recommendations))
            .where(
                QuantDecisionRun.portfolio_id == batch.portfolio_id,
                QuantDecisionRun.as_of_time == batch.as_of_time,
                QuantDecisionRun.input_fingerprint == batch.input_fingerprint,
            )
        )
        if existing is not None:
            return existing
        if self.session.get(Portfolio, batch.portfolio_id) is None:
            raise ValueError("decision portfolio does not exist")
        stock_ids = {item.stock_id for item in batch.recommendations}
        if stock_ids:
            found = set(
                self.session.scalars(select(Stock.id).where(Stock.id.in_(stock_ids)))
            )
            if found != stock_ids:
                raise ValueError("decision recommendations contain unknown assets")
        run = QuantDecisionRun(
            portfolio_id=batch.portfolio_id,
            as_of_time=batch.as_of_time,
            status=batch.status.value,
            gate_status=batch.gate_status,
            authorization_id=batch.authorization_id,
            data_version=batch.data_version,
            model_version=batch.model_version,
            input_fingerprint=batch.input_fingerprint,
            source_ids=list(batch.source_ids),
            blockers=list(batch.blockers),
        )
        run.recommendations.extend(
            QuantDecisionRecommendation(
                recommendation_id=item.recommendation_id,
                stock_id=item.stock_id,
                action=item.action.value,
                current_weight=Decimal(str(item.current_weight)),
                target_weight=Decimal(str(item.target_weight)),
                quant_score=Decimal(str(item.quant_score)),
                confidence_score=Decimal(str(item.confidence_score)),
                component_scores=item.component_scores,
                rationale=list(item.rationale),
                risk_factors=list(item.risk_factors),
                evidence_grade=item.evidence_grade,
                sample_size=item.sample_size,
                source_ids=list(item.source_ids),
                reference_price=Decimal(str(item.reference_price)),
                suggested_shares=item.suggested_shares,
                earliest_execution_time=item.earliest_execution_time,
                expires_at=item.expires_at,
                review_status="pending",
            )
            for item in batch.recommendations
        )
        self.session.add(run)
        self.session.flush()
        return run

    def latest_run(self, portfolio_id: int | None = None) -> QuantDecisionRun | None:
        statement = select(QuantDecisionRun).options(
            selectinload(QuantDecisionRun.recommendations).selectinload(
                QuantDecisionRecommendation.stock
            )
        )
        if portfolio_id is not None:
            statement = statement.where(QuantDecisionRun.portfolio_id == portfolio_id)
        return self.session.scalar(
            statement.order_by(
                QuantDecisionRun.as_of_time.desc(),
                QuantDecisionRun.id.desc(),
            ).limit(1)
        )

    def pending_recommendations(
        self,
        *,
        now: datetime,
        portfolio_id: int | None = None,
    ) -> tuple[QuantDecisionRecommendation, ...]:
        statement = (
            select(QuantDecisionRecommendation)
            .options(selectinload(QuantDecisionRecommendation.stock))
            .join(QuantDecisionRun, QuantDecisionRun.id == QuantDecisionRecommendation.run_id)
            .where(
                QuantDecisionRecommendation.review_status == "pending",
                QuantDecisionRecommendation.expires_at >= now,
                QuantDecisionRun.status == "generated",
                QuantDecisionRun.gate_status == "APPROVED",
            )
        )
        if portfolio_id is not None:
            statement = statement.where(QuantDecisionRun.portfolio_id == portfolio_id)
        return tuple(
            self.session.scalars(
                statement.order_by(
                    QuantDecisionRecommendation.confidence_score.desc(),
                    QuantDecisionRecommendation.id,
                )
            )
        )

    def get_recommendation(
        self,
        recommendation_id: str,
    ) -> QuantDecisionRecommendation | None:
        return self.session.scalar(
            select(QuantDecisionRecommendation)
            .options(
                selectinload(QuantDecisionRecommendation.run),
                selectinload(QuantDecisionRecommendation.stock),
                selectinload(QuantDecisionRecommendation.history),
            )
            .where(QuantDecisionRecommendation.recommendation_id == recommendation_id)
        )

    def review(
        self,
        *,
        recommendation_id: str,
        decision: UserDecision,
        decided_at: datetime,
        reason: str = "",
    ) -> DecisionHistory:
        recommendation = self.session.scalar(
            select(QuantDecisionRecommendation)
            .options(
                selectinload(QuantDecisionRecommendation.run),
                selectinload(QuantDecisionRecommendation.stock),
            )
            .where(QuantDecisionRecommendation.recommendation_id == recommendation_id)
        )
        if recommendation is None:
            raise ValueError("decision recommendation does not exist")
        if decided_at.tzinfo is None:
            raise ValueError("decision review timestamp must be timezone-aware")
        existing = self.session.scalar(
            select(DecisionHistory).where(
                DecisionHistory.recommendation_id == recommendation.id
            )
        )
        if existing is not None:
            if existing.decision != decision.value:
                raise ValueError("decision is immutable after review")
            return existing
        expires_at = recommendation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if decision is UserDecision.ACCEPTED and decided_at > expires_at:
            raise ValueError("expired recommendation cannot be accepted")
        history = DecisionHistory(
            recommendation_id=recommendation.id,
            decision=decision.value,
            decided_at=decided_at,
            reason=reason.strip(),
        )
        recommendation.review_status = decision.value
        self.session.add(history)
        self.session.flush()
        return history
