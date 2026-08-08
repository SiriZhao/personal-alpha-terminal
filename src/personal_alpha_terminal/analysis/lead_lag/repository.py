from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphInstrument,
    MarketSeries,
)
from personal_alpha_terminal.models import (
    LeadLagAnalysisRun,
    LeadLagMetric,
    LeadLagPairResult,
)


class LeadLagRepository:
    """Market-series input and persisted lead-lag result access."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._market_repository = MarketGraphRepository(session)

    def list_instruments(self) -> list[GraphInstrument]:
        return self._market_repository.list_instruments()

    def load_series(
        self,
        instrument_ids: tuple[int, ...],
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[MarketSeries, ...]:
        return self._market_repository.load_series(
            instrument_ids,
            start_date=start_date,
            end_date=end_date,
            flow_lookback_days=2,
        )

    def latest_run(self) -> LeadLagAnalysisRun | None:
        return self.session.scalar(
            select(LeadLagAnalysisRun)
            .where(LeadLagAnalysisRun.status == "completed")
            .order_by(
                LeadLagAnalysisRun.created_at.desc(),
                LeadLagAnalysisRun.id.desc(),
            )
            .limit(1)
        )

    def pairs_for_run(self, run_id: int) -> list[LeadLagPairResult]:
        return list(
            self.session.scalars(
                select(LeadLagPairResult)
                .where(LeadLagPairResult.run_id == run_id)
                .order_by(
                    LeadLagPairResult.is_significant.desc(),
                    LeadLagPairResult.confidence_score.desc(),
                )
            )
        )

    def metrics_for_pair(self, pair_result_id: int) -> list[LeadLagMetric]:
        return list(
            self.session.scalars(
                select(LeadLagMetric)
                .where(LeadLagMetric.pair_result_id == pair_result_id)
                .order_by(LeadLagMetric.lag_days)
            )
        )
