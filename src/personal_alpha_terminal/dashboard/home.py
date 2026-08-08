from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    BacktestRun,
    ConditionalProbabilityResult,
    ConditionalProbabilityRun,
    DailyPipelineRun,
    EventOccurrence,
    EventStudyRun,
    EventStudyStatistic,
    FactorResearchRun,
    FactorScore,
    MarketDataQualityRun,
    Portfolio,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    RelationshipAnalysisRun,
    RelationshipAnomaly,
    ResearchReport,
    Stock,
)
from personal_alpha_terminal.research import (
    ResearchDataGateService,
    ResearchDataRequest,
    ResearchPurpose,
)

SAFE_PRICE_POLICY = AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value


@dataclass(frozen=True, slots=True)
class EventInsight:
    event_name: str
    trigger_symbol: str
    target_symbol: str
    horizon_days: int
    sample_size: int
    probability: float
    average_return: float
    interval_lower: float | None
    interval_upper: float | None
    as_of_date: date
    last_event_date: date | None


@dataclass(frozen=True, slots=True)
class ProbabilityInsight:
    target_symbol: str
    horizon_days: int
    sample_size: int
    probability: float
    interval_lower: float | None
    interval_upper: float | None
    average_return: float | None


@dataclass(frozen=True, slots=True)
class RelationshipInsight:
    left_label: str
    right_label: str
    baseline_correlation: float
    current_correlation: float
    absolute_change: float
    direction: str
    detected_on: date


@dataclass(frozen=True, slots=True)
class PortfolioDigest:
    name: str
    base_currency: str
    as_of_date: date
    total_value: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_ratio: float | None
    beta: float | None
    top_positions: tuple[tuple[str, float], ...]
    industry_exposure: dict[str, float]


@dataclass(frozen=True, slots=True)
class ReportDigest:
    title: str
    report_type: str
    as_of_date: date
    generated_by: str
    source_count: int


@dataclass(frozen=True, slots=True)
class FactorDigest:
    market: str
    analysis_type: str
    as_of_date: date
    score_count: int
    cumulative_return: float | None
    max_drawdown: float | None


@dataclass(frozen=True, slots=True)
class BacktestDigest:
    strategy_name: str
    market: str
    end_date: date
    total_return: float
    sharpe_ratio: float | None
    max_drawdown: float
    validation_issue_count: int


@dataclass(frozen=True, slots=True)
class HomeDigest:
    events: tuple[EventInsight, ...]
    probabilities: tuple[ProbabilityInsight, ...]
    relationships: tuple[RelationshipInsight, ...]
    portfolio: PortfolioDigest | None
    reports: tuple[ReportDigest, ...]
    factor: FactorDigest | None
    backtest: BacktestDigest | None
    refreshed_at: datetime | None
    quality_status: str
    quality_sample_count: int
    quality_blockers: tuple[str, ...]
    pipeline_status: str
    pipeline_run_date: date | None
    data_gate_status: str
    data_gate_blockers: tuple[str, ...]

    @classmethod
    def unavailable(cls, reason: str) -> HomeDigest:
        return cls(
            events=(),
            probabilities=(),
            relationships=(),
            portfolio=None,
            reports=(),
            factor=None,
            backtest=None,
            refreshed_at=None,
            quality_status="not_run",
            quality_sample_count=0,
            quality_blockers=(reason,),
            pipeline_status="not_run",
            pipeline_run_date=None,
            data_gate_status="BLOCKED",
            data_gate_blockers=(reason,),
        )


class HomeDashboardRepository:
    """Bounded read model for the summary-first terminal home page."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self) -> HomeDigest:
        events, event_refreshed = self._events()
        probabilities, probability_refreshed = self._probabilities()
        relationships, relationship_refreshed = self._relationships()
        portfolio, portfolio_refreshed = self._portfolio()
        reports, report_refreshed = self._reports()
        factor, factor_refreshed = self._factor()
        backtest, backtest_refreshed = self._backtest()
        quality = self._session.scalar(
            select(MarketDataQualityRun)
            .order_by(MarketDataQualityRun.created_at.desc(), MarketDataQualityRun.id.desc())
            .limit(1)
        )
        pipeline = self._session.scalar(
            select(DailyPipelineRun)
            .order_by(DailyPipelineRun.start_time.desc(), DailyPipelineRun.id.desc())
            .limit(1)
        )
        decision = ResearchDataGateService(self._session).evaluate(
            ResearchDataRequest(
                purpose=ResearchPurpose.DISPLAY,
                market="US",
                asset_type="stock",
                start_date=date.today(),
                end_date=date.today(),
                decision_time=datetime.now(UTC),
                adjustment_mode="raw",
            )
        )
        timestamps = tuple(
            item
            for item in (
                event_refreshed,
                probability_refreshed,
                relationship_refreshed,
                portfolio_refreshed,
                report_refreshed,
                factor_refreshed,
                backtest_refreshed,
            )
            if item is not None
        )
        return HomeDigest(
            events=events,
            probabilities=probabilities,
            relationships=relationships,
            portfolio=portfolio,
            reports=reports,
            factor=factor,
            backtest=backtest,
            refreshed_at=max(timestamps) if timestamps else None,
            quality_status=quality.status if quality is not None else "not_run",
            quality_sample_count=quality.sample_count if quality is not None else 0,
            quality_blockers=tuple(quality.blockers) if quality is not None else (),
            pipeline_status=pipeline.status if pipeline is not None else "not_run",
            pipeline_run_date=pipeline.run_date if pipeline is not None else None,
            data_gate_status=decision.status.value,
            data_gate_blockers=decision.blockers,
        )

    def _events(self) -> tuple[tuple[EventInsight, ...], datetime | None]:
        run = self._session.scalar(
            select(EventStudyRun)
            .options(selectinload(EventStudyRun.definition))
            .where(EventStudyRun.status == "completed")
            .order_by(EventStudyRun.created_at.desc(), EventStudyRun.id.desc())
            .limit(1)
        )
        if run is None:
            return (), None
        if run.parameters.get("price_adjustment_policy") != SAFE_PRICE_POLICY:
            return (), run.updated_at
        trigger = self._session.get(Stock, run.trigger_stock_id)
        rows = tuple(
            self._session.scalars(
                select(EventStudyStatistic)
                .where(
                    EventStudyStatistic.run_id == run.id,
                    EventStudyStatistic.meets_minimum.is_(True),
                )
                .order_by(
                    EventStudyStatistic.sample_size.desc(),
                    EventStudyStatistic.target_stock_id.asc(),
                    EventStudyStatistic.horizon_days.asc(),
                )
                .limit(3)
            )
        )
        targets = self._stocks_by_id({item.target_stock_id for item in rows})
        last_event_date = self._session.scalar(
            select(func.max(EventOccurrence.event_date)).where(EventOccurrence.run_id == run.id)
        )
        return (
            tuple(
                EventInsight(
                    event_name=run.definition.name,
                    trigger_symbol=trigger.symbol if trigger is not None else "—",
                    target_symbol=targets[item.target_stock_id].symbol,
                    horizon_days=item.horizon_days,
                    sample_size=item.sample_size,
                    probability=float(item.positive_probability),
                    average_return=float(item.average_return),
                    interval_lower=(
                        float(item.positive_probability_lower)
                        if item.positive_probability_lower is not None
                        else None
                    ),
                    interval_upper=(
                        float(item.positive_probability_upper)
                        if item.positive_probability_upper is not None
                        else None
                    ),
                    as_of_date=run.end_date,
                    last_event_date=last_event_date,
                )
                for item in rows
                if item.target_stock_id in targets
            ),
            run.updated_at,
        )

    def _probabilities(self) -> tuple[tuple[ProbabilityInsight, ...], datetime | None]:
        run = self._session.scalar(
            select(ConditionalProbabilityRun)
            .where(ConditionalProbabilityRun.status == "completed")
            .order_by(
                ConditionalProbabilityRun.created_at.desc(),
                ConditionalProbabilityRun.id.desc(),
            )
            .limit(1)
        )
        if run is None:
            return (), None
        event_run = self._session.get(EventStudyRun, run.event_study_run_id)
        if (
            run.parameters.get("price_adjustment_policy") != SAFE_PRICE_POLICY
            or event_run is None
            or event_run.parameters.get("price_adjustment_policy") != SAFE_PRICE_POLICY
        ):
            return (), run.updated_at
        rows = tuple(
            self._session.scalars(
                select(ConditionalProbabilityResult)
                .where(
                    ConditionalProbabilityResult.run_id == run.id,
                    ConditionalProbabilityResult.meets_minimum.is_(True),
                    ConditionalProbabilityResult.probability.is_not(None),
                )
                .order_by(
                    ConditionalProbabilityResult.sample_size.desc(),
                    ConditionalProbabilityResult.target_stock_id.asc(),
                    ConditionalProbabilityResult.horizon_days.asc(),
                )
                .limit(3)
            )
        )
        targets = self._stocks_by_id({item.target_stock_id for item in rows})
        return (
            tuple(
                ProbabilityInsight(
                    target_symbol=targets[item.target_stock_id].symbol,
                    horizon_days=item.horizon_days,
                    sample_size=item.sample_size,
                    probability=float(item.probability),
                    interval_lower=(
                        float(item.confidence_lower)
                        if item.confidence_lower is not None
                        else None
                    ),
                    interval_upper=(
                        float(item.confidence_upper)
                        if item.confidence_upper is not None
                        else None
                    ),
                    average_return=(
                        float(item.average_return) if item.average_return is not None else None
                    ),
                )
                for item in rows
                if item.target_stock_id in targets and item.probability is not None
            ),
            run.updated_at,
        )

    def _relationships(self) -> tuple[tuple[RelationshipInsight, ...], datetime | None]:
        run = self._session.scalar(
            select(RelationshipAnalysisRun)
            .where(RelationshipAnalysisRun.status == "completed")
            .order_by(
                RelationshipAnalysisRun.created_at.desc(),
                RelationshipAnalysisRun.id.desc(),
            )
            .limit(1)
        )
        if run is None:
            return (), None
        if run.parameters.get("significance_method") not in {"fdr", "bonferroni"}:
            # The legacy relationship-change detector applies an effect-size
            # threshold only. Keep uncorrected exploratory anomalies out of the
            # decision-oriented home page.
            return (), run.updated_at
        rows = self._session.scalars(
            select(RelationshipAnomaly)
            .where(RelationshipAnomaly.run_id == run.id)
            .order_by(RelationshipAnomaly.absolute_change.desc())
            .limit(3)
        )
        return (
            tuple(
                RelationshipInsight(
                    left_label=item.left_entity_label,
                    right_label=item.right_entity_label,
                    baseline_correlation=float(item.baseline_correlation),
                    current_correlation=float(item.current_correlation),
                    absolute_change=float(item.absolute_change),
                    direction=item.direction,
                    detected_on=item.detected_on,
                )
                for item in rows
            ),
            run.updated_at,
        )

    def _portfolio(self) -> tuple[PortfolioDigest | None, datetime | None]:
        run = self._session.scalar(
            select(PortfolioRiskRun)
            .options(selectinload(PortfolioRiskRun.metrics))
            .where(PortfolioRiskRun.status == "completed")
            .order_by(PortfolioRiskRun.created_at.desc(), PortfolioRiskRun.id.desc())
            .limit(1)
        )
        if run is None or run.metrics is None:
            return None, None
        portfolio = self._session.get(Portfolio, run.portfolio_id)
        if portfolio is None:
            return None, run.updated_at
        metric: PortfolioRiskMetric = run.metrics
        raw_weights = {
            int(key): float(value) for key, value in metric.position_weights.items()
        }
        stocks = self._stocks_by_id(set(raw_weights))
        top_positions = tuple(
            sorted(
                (
                    (stocks[stock_id].symbol, weight)
                    for stock_id, weight in raw_weights.items()
                    if stock_id in stocks
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:5]
        )
        return (
            PortfolioDigest(
                name=portfolio.name,
                base_currency=portfolio.base_currency,
                as_of_date=run.as_of_date,
                total_value=float(metric.total_value),
                annualized_return=float(metric.annualized_return),
                annualized_volatility=float(metric.annualized_volatility),
                max_drawdown=float(metric.max_drawdown),
                sharpe_ratio=(
                    float(metric.sharpe_ratio) if metric.sharpe_ratio is not None else None
                ),
                beta=float(metric.beta) if metric.beta is not None else None,
                top_positions=top_positions,
                industry_exposure={
                    str(key): float(value) for key, value in metric.industry_exposure.items()
                },
            ),
            run.updated_at,
        )

    def _reports(self) -> tuple[tuple[ReportDigest, ...], datetime | None]:
        rows = tuple(
            self._session.scalars(
                select(ResearchReport)
                .order_by(ResearchReport.as_of_date.desc(), ResearchReport.created_at.desc())
                .limit(4)
            )
        )
        return (
            tuple(
                ReportDigest(
                    title=item.title,
                    report_type=item.report_type,
                    as_of_date=item.as_of_date,
                    generated_by=item.generated_by,
                    source_count=len(item.data_sources),
                )
                for item in rows
            ),
            max((item.updated_at for item in rows), default=None),
        )

    def _factor(self) -> tuple[FactorDigest | None, datetime | None]:
        run = self._session.scalar(
            select(FactorResearchRun)
            .options(selectinload(FactorResearchRun.summary))
            .where(
                FactorResearchRun.status == "completed",
                FactorResearchRun.analysis_type == "snapshot",
            )
            .order_by(FactorResearchRun.created_at.desc(), FactorResearchRun.id.desc())
            .limit(1)
        )
        if run is None:
            return None, None
        if run.parameters.get("price_adjustment_policy") != SAFE_PRICE_POLICY:
            return None, run.updated_at
        score_count = int(
            self._session.scalar(
                select(func.count(FactorScore.id)).where(FactorScore.run_id == run.id)
            )
            or 0
        )
        return (
            FactorDigest(
                market=run.market,
                analysis_type=run.analysis_type,
                as_of_date=run.end_date,
                score_count=score_count,
                cumulative_return=(
                    float(run.summary.cumulative_return) if run.summary is not None else None
                ),
                max_drawdown=(
                    float(run.summary.max_drawdown) if run.summary is not None else None
                ),
            ),
            run.updated_at,
        )

    def _backtest(self) -> tuple[BacktestDigest | None, datetime | None]:
        run = self._session.scalar(
            select(BacktestRun)
            .options(selectinload(BacktestRun.summary))
            .where(BacktestRun.status == "completed")
            .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
            .limit(1)
        )
        if run is None or run.summary is None:
            return None, None
        parameters = run.parameters
        if not (
            parameters.get("execution_policy")
            == "signal_close_execute_next_session_open"
            and parameters.get("require_adjusted_prices") is True
            and parameters.get("require_verified_calendar") is True
            and parameters.get("require_explicit_open_tradability") is True
            and self._positive_cost_assumption(parameters)
        ):
            return None, run.updated_at
        return (
            BacktestDigest(
                strategy_name=run.strategy_name,
                market=run.market,
                end_date=run.end_date,
                total_return=float(run.summary.total_return),
                sharpe_ratio=(
                    float(run.summary.sharpe_ratio)
                    if run.summary.sharpe_ratio is not None
                    else None
                ),
                max_drawdown=float(run.summary.maximum_drawdown),
                validation_issue_count=len(run.validation_issues),
            ),
            run.updated_at,
        )

    def _stocks_by_id(self, identifiers: set[int]) -> dict[int, Stock]:
        if not identifiers:
            return {}
        return {
            item.id: item
            for item in self._session.scalars(select(Stock).where(Stock.id.in_(identifiers)))
        }

    @staticmethod
    def _positive_cost_assumption(parameters: dict[str, object]) -> bool:
        total = 0.0
        for key in ("commission_bps", "fee_bps", "slippage_bps"):
            value = parameters.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            total += float(value)
        return total > 0
