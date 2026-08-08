from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import permutations

from personal_alpha_terminal.analysis.lead_lag.repository import LeadLagRepository
from personal_alpha_terminal.analysis.lead_lag.schemas import (
    LagMetric,
    LeadLagAnalysisResult,
    PairEvidence,
)
from personal_alpha_terminal.analysis.lead_lag.statistics import (
    benjamini_hochberg,
    bonferroni_adjust,
    calculate_lag_metrics,
)
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphInstrument,
    MarketSeries,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    LeadLagAnalysisRun,
    LeadLagMetric,
    LeadLagPairResult,
)


@dataclass(frozen=True, slots=True)
class _PairCandidate:
    source: GraphInstrument
    target: GraphInstrument
    best: LagMetric
    lag_adjusted_p_value: float
    metrics: tuple[LagMetric, ...]


class LeadLagAnalysisService:
    """Discover, correct, persist, and restore directional market relationships."""

    def __init__(self, repository: LeadLagRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def list_instruments(self) -> tuple[GraphInstrument, ...]:
        return tuple(self._repository.list_instruments())

    def run(
        self,
        *,
        instrument_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
        maximum_lag_days: int | None = None,
    ) -> LeadLagAnalysisResult:
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        unique_ids = tuple(dict.fromkeys(instrument_ids))
        if len(unique_ids) < 2:
            raise ValueError("at least two instruments are required")
        if len(unique_ids) > self._settings.lead_lag_maximum_assets:
            raise ValueError(
                f"asset count exceeds configured maximum ({self._settings.lead_lag_maximum_assets})"
            )
        maximum_lag = maximum_lag_days or self._settings.lead_lag_maximum_lag_days
        if maximum_lag < 1 or maximum_lag > self._settings.lead_lag_maximum_lag_days:
            raise ValueError(
                "maximum_lag_days must be between 1 and configured maximum "
                f"({self._settings.lead_lag_maximum_lag_days})"
            )

        run = LeadLagAnalysisRun(
            start_date=start_date,
            end_date=end_date,
            maximum_lag_days=maximum_lag,
            minimum_observations=self._settings.lead_lag_minimum_observations,
            fdr_alpha=self._decimal(self._settings.lead_lag_fdr_alpha),
            minimum_abs_correlation=self._decimal(self._settings.lead_lag_minimum_abs_correlation),
            status="running",
            parameters={
                "instrument_ids": list(unique_ids),
                "input": "adjusted_close_daily_returns",
                "alignment": "common_trading_dates_no_forward_fill",
                "lag_unit": "common_trading_observations",
                "cross_correlation": "corr(source[t], target[t+lag])",
                "granger_test": "ssr_ftest",
                "within_pair_correction": "bonferroni",
                "across_pair_correction": "benjamini_hochberg",
                "confidence_definition": "1_minus_q_value_evidence_score",
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            series = self._repository.load_series(
                unique_ids,
                start_date=start_date,
                end_date=end_date,
            )
            if len(series) != len(unique_ids):
                raise ValueError("one or more selected instruments do not exist")
            candidates = self._calculate_candidates(series, maximum_lag)
            q_values = benjamini_hochberg(
                [candidate.lag_adjusted_p_value for candidate in candidates]
            )
            pairs = tuple(
                self._to_evidence(candidate, q_value)
                for candidate, q_value in zip(candidates, q_values, strict=True)
            )
            self._persist_pairs(run.id, pairs)
            run.status = "completed"
            self._repository.session.flush()
            return LeadLagAnalysisResult(
                run_id=run.id,
                start_date=start_date,
                end_date=end_date,
                pairs=tuple(
                    sorted(
                        pairs,
                        key=lambda item: (
                            not item.is_significant,
                            item.q_value,
                            -abs(item.cross_correlation),
                        ),
                    )
                ),
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self) -> LeadLagAnalysisResult | None:
        run = self._repository.latest_run()
        if run is None:
            return None
        instruments = {item.id: item for item in self._repository.list_instruments()}
        pairs: list[PairEvidence] = []
        for model in self._repository.pairs_for_run(run.id):
            source = instruments.get(model.source_stock_id)
            target = instruments.get(model.target_stock_id)
            if source is None or target is None:
                continue
            metrics = tuple(
                LagMetric(
                    lag_days=item.lag_days,
                    cross_correlation=float(item.cross_correlation),
                    granger_f_statistic=float(item.granger_f_statistic),
                    granger_p_value=float(item.granger_p_value),
                    sample_size=item.sample_size,
                )
                for item in self._repository.metrics_for_pair(model.id)
            )
            pairs.append(
                PairEvidence(
                    source=source,
                    target=target,
                    best_lag_days=model.best_lag_days,
                    cross_correlation=float(model.cross_correlation),
                    granger_f_statistic=float(model.granger_f_statistic),
                    raw_p_value=float(model.raw_p_value),
                    lag_adjusted_p_value=float(model.lag_adjusted_p_value),
                    q_value=float(model.q_value),
                    confidence_score=float(model.confidence_score),
                    sample_size=model.sample_size,
                    is_significant=model.is_significant,
                    metrics=metrics,
                )
            )
        return LeadLagAnalysisResult(
            run_id=run.id,
            start_date=run.start_date,
            end_date=run.end_date,
            pairs=tuple(pairs),
        )

    def _calculate_candidates(
        self,
        series: tuple[MarketSeries, ...],
        maximum_lag_days: int,
    ) -> tuple[_PairCandidate, ...]:
        candidates: list[_PairCandidate] = []
        for source, target in permutations(series, 2):
            metrics = calculate_lag_metrics(
                source,
                target,
                maximum_lag_days=maximum_lag_days,
                minimum_observations=self._settings.lead_lag_minimum_observations,
            )
            if not metrics:
                continue
            best = min(metrics, key=lambda item: (item.granger_p_value, item.lag_days))
            candidates.append(
                _PairCandidate(
                    source=source.instrument,
                    target=target.instrument,
                    best=best,
                    lag_adjusted_p_value=bonferroni_adjust(
                        best.granger_p_value,
                        len(metrics),
                    ),
                    metrics=metrics,
                )
            )
        return tuple(candidates)

    def _to_evidence(
        self,
        candidate: _PairCandidate,
        q_value: float,
    ) -> PairEvidence:
        confidence = 1 - q_value
        significant = (
            q_value <= self._settings.lead_lag_fdr_alpha
            and abs(candidate.best.cross_correlation)
            >= self._settings.lead_lag_minimum_abs_correlation
        )
        return PairEvidence(
            source=candidate.source,
            target=candidate.target,
            best_lag_days=candidate.best.lag_days,
            cross_correlation=candidate.best.cross_correlation,
            granger_f_statistic=candidate.best.granger_f_statistic,
            raw_p_value=candidate.best.granger_p_value,
            lag_adjusted_p_value=candidate.lag_adjusted_p_value,
            q_value=q_value,
            confidence_score=confidence,
            sample_size=candidate.best.sample_size,
            is_significant=significant,
            metrics=candidate.metrics,
        )

    def _persist_pairs(
        self,
        run_id: int,
        pairs: tuple[PairEvidence, ...],
    ) -> None:
        for item in pairs:
            pair_model = LeadLagPairResult(
                run_id=run_id,
                source_stock_id=item.source.id,
                target_stock_id=item.target.id,
                best_lag_days=item.best_lag_days,
                cross_correlation=self._decimal(item.cross_correlation),
                granger_f_statistic=self._decimal(item.granger_f_statistic),
                raw_p_value=self._decimal(item.raw_p_value),
                lag_adjusted_p_value=self._decimal(item.lag_adjusted_p_value),
                q_value=self._decimal(item.q_value),
                confidence_score=self._decimal(item.confidence_score),
                sample_size=item.sample_size,
                is_significant=item.is_significant,
            )
            self._repository.session.add(pair_model)
            self._repository.session.flush()
            self._repository.session.add_all(
                [
                    LeadLagMetric(
                        pair_result_id=pair_model.id,
                        lag_days=metric.lag_days,
                        cross_correlation=self._decimal(metric.cross_correlation),
                        granger_f_statistic=self._decimal(metric.granger_f_statistic),
                        granger_p_value=self._decimal(metric.granger_p_value),
                        sample_size=metric.sample_size,
                    )
                    for metric in item.metrics
                ]
            )

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 16)))
