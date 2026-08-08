from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import (
    ConditionalProbabilityResult,
    ConditionalProbabilityRun,
    EventOccurrence,
    EventStudyObservation,
    EventStudyRun,
)


class ConditionalProbabilityRepository:
    """Read event-study samples and persist probability inference outputs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def grouped_returns(
        self,
        event_study_run_id: int,
    ) -> dict[tuple[int, int], tuple[float, ...]]:
        rows = self.session.execute(
            select(
                EventStudyObservation.target_stock_id,
                EventStudyObservation.horizon_days,
                EventStudyObservation.forward_return,
            )
            .join(
                EventOccurrence,
                EventOccurrence.id == EventStudyObservation.occurrence_id,
            )
            .where(EventOccurrence.run_id == event_study_run_id)
            .order_by(
                EventStudyObservation.target_stock_id,
                EventStudyObservation.horizon_days,
                EventOccurrence.event_date,
            )
        )
        grouped: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
        for target_stock_id, horizon_days, forward_return in rows:
            grouped[(target_stock_id, horizon_days)].append(float(forward_return))
        return {key: tuple(values) for key, values in grouped.items()}

    def get_event_study_run(self, run_id: int) -> EventStudyRun | None:
        return self.session.get(EventStudyRun, run_id)

    def event_count(self, event_study_run_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(EventOccurrence.id)).where(
                    EventOccurrence.run_id == event_study_run_id
                )
            )
            or 0
        )

    def latest_run(self) -> ConditionalProbabilityRun | None:
        return self.session.scalar(
            select(ConditionalProbabilityRun)
            .where(ConditionalProbabilityRun.status == "completed")
            .order_by(
                ConditionalProbabilityRun.created_at.desc(),
                ConditionalProbabilityRun.id.desc(),
            )
            .limit(1)
        )

    def results_for_run(self, run_id: int) -> list[ConditionalProbabilityResult]:
        return list(
            self.session.scalars(
                select(ConditionalProbabilityResult)
                .where(ConditionalProbabilityResult.run_id == run_id)
                .order_by(
                    ConditionalProbabilityResult.horizon_days,
                    ConditionalProbabilityResult.target_stock_id,
                )
            )
        )
