from datetime import date, timedelta
from decimal import Decimal

from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.analysis.factors.schemas import (
    FactorBacktestPeriodResult,
    FactorBacktestResult,
    FactorBacktestSummaryResult,
    FactorDataset,
    FactorSnapshotResult,
    FactorStockScore,
)
from personal_alpha_terminal.analysis.factors.statistics import (
    CATEGORIES,
    FACTOR_DIRECTIONS,
    calculate_factor_scores,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    FactorBacktestPeriod,
    FactorBacktestSummary,
    FactorResearchRun,
    FactorScore,
)


class FactorResearchService:
    """Calculate and persist point-in-time factor snapshots and backtests."""

    def __init__(self, repository: FactorResearchRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def run_snapshot(
        self,
        *,
        market: str,
        as_of_date: date,
        universe_snapshot_id: int | None = None,
    ) -> FactorSnapshotResult:
        self._validate_market(market)
        run = self._new_run(
            analysis_type="snapshot",
            market=market,
            start_date=as_of_date,
            end_date=as_of_date,
        )
        try:
            dataset = self._load_dataset(
                market=market,
                start_date=as_of_date,
                end_date=as_of_date,
                include_inactive=False,
                universe_snapshot_id=universe_snapshot_id,
            )
            scores = self._scores(dataset, as_of_date)
            self._validate_score_count(scores)
            self._persist_scores(run.id, scores)
            run.status = "completed"
            self._repository.session.flush()
            return FactorSnapshotResult(
                run_id=run.id,
                market=market,
                as_of_date=as_of_date,
                scores=scores,
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def run_backtest(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
    ) -> FactorBacktestResult:
        raise ValueError(
            "legacy close-to-close factor backtest is disabled because it has no "
            "next-open execution, transaction costs, verified trading calendar, or "
            "tradability model; use Backtest Laboratory with "
            "FactorQuantileStrategy"
        )

    def latest_snapshot(self) -> FactorSnapshotResult | None:
        run = self._repository.latest_run("snapshot")
        if run is None:
            return None
        if (
            run.parameters.get("price_adjustment_policy")
            != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
        ):
            return None
        scores = self._restore_scores(run.id)
        return FactorSnapshotResult(
            run_id=run.id,
            market=run.market,
            as_of_date=run.end_date,
            scores=scores,
        )

    def latest_backtest(self) -> FactorBacktestResult | None:
        # Historical results from the retired close-to-close path are deliberately
        # hidden because their performance metrics are not execution-valid.
        return None

    def _new_run(
        self,
        *,
        analysis_type: str,
        market: str,
        start_date: date,
        end_date: date,
    ) -> FactorResearchRun:
        run = FactorResearchRun(
            analysis_type=analysis_type,
            market=market,
            start_date=start_date,
            end_date=end_date,
            status="running",
            parameters={
                "factors": list(FACTOR_DIRECTIONS),
                "categories": {name: list(factors) for name, factors in CATEGORIES.items()},
                "normalization": "directional_cross_sectional_percentile_0_100",
                "category_weighting": "equal_weight_available_categories",
                "missing_value_policy": "no_imputation",
                "momentum_lookback": self._settings.factor_momentum_lookback,
                "momentum_skip": self._settings.factor_momentum_skip,
                "volatility_window": self._settings.factor_volatility_window,
                "minimum_categories": self._settings.factor_minimum_categories,
                "selection_quantile": self._settings.factor_selection_quantile,
                "rebalance_interval": self._settings.factor_rebalance_interval,
                "holding_period": self._settings.factor_holding_period,
                "benchmark": "equal_weight_scored_universe",
                "transaction_costs": 0.0,
                "price_adjustment_policy": AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()
        return run

    def _load_dataset(
        self,
        *,
        market: str,
        start_date: date,
        end_date: date,
        include_inactive: bool,
        universe_snapshot_id: int | None = None,
    ) -> FactorDataset:
        history = max(
            self._settings.factor_momentum_lookback,
            self._settings.factor_volatility_window,
        )
        query_start = start_date - timedelta(days=history * 2 + 30)
        return self._repository.load_dataset(
            market=market,
            query_start_date=query_start,
            end_date=end_date,
            include_inactive=include_inactive,
            maximum_universe_size=self._settings.factor_maximum_universe_size,
            universe_snapshot_id=universe_snapshot_id,
        )

    def _scores(
        self,
        dataset: FactorDataset,
        as_of_date: date,
    ) -> tuple[FactorStockScore, ...]:
        return calculate_factor_scores(
            dataset,
            as_of_date=as_of_date,
            momentum_lookback=self._settings.factor_momentum_lookback,
            momentum_skip=self._settings.factor_momentum_skip,
            volatility_window=self._settings.factor_volatility_window,
            minimum_categories=self._settings.factor_minimum_categories,
        )

    def _validate_score_count(self, scores: tuple[FactorStockScore, ...]) -> None:
        if len(scores) < self._settings.factor_minimum_scored_stocks:
            raise ValueError(
                "insufficient stocks with valid factor coverage; need at least "
                f"{self._settings.factor_minimum_scored_stocks}"
            )

    def _persist_scores(
        self,
        run_id: int,
        scores: tuple[FactorStockScore, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                FactorScore(
                    run_id=run_id,
                    as_of_date=item.as_of_date,
                    stock_id=item.instrument.id,
                    raw_factors=item.raw_factors,
                    normalized_factors=item.normalized_factors,
                    category_scores=item.category_scores,
                    factor_score=self._decimal(item.factor_score),
                    category_coverage=item.category_coverage,
                )
                for item in scores
            ]
        )

    def _persist_backtest(
        self,
        run_id: int,
        periods: tuple[FactorBacktestPeriodResult, ...],
        summary: FactorBacktestSummaryResult,
    ) -> None:
        self._repository.session.add_all(
            [
                FactorBacktestPeriod(
                    run_id=run_id,
                    rebalance_date=item.rebalance_date,
                    period_end_date=item.period_end_date,
                    selected_stock_ids=[asset.id for asset in item.selected],
                    selected_symbols=[asset.symbol for asset in item.selected],
                    selected_count=len(item.selected),
                    portfolio_return=self._decimal(item.portfolio_return),
                    benchmark_return=self._decimal(item.benchmark_return),
                    excess_return=self._decimal(item.excess_return),
                )
                for item in periods
            ]
        )
        self._repository.session.add(
            FactorBacktestSummary(
                run_id=run_id,
                period_count=summary.period_count,
                cumulative_return=self._decimal(summary.cumulative_return),
                benchmark_cumulative_return=self._decimal(summary.benchmark_cumulative_return),
                annualized_return=self._decimal(summary.annualized_return),
                annualized_volatility=self._decimal(summary.annualized_volatility),
                sharpe_ratio=(
                    self._decimal(summary.sharpe_ratio)
                    if summary.sharpe_ratio is not None
                    else None
                ),
                max_drawdown=self._decimal(summary.max_drawdown),
                excess_hit_rate=self._decimal(summary.excess_hit_rate),
            )
        )

    def _restore_scores(self, run_id: int) -> tuple[FactorStockScore, ...]:
        models = self._repository.scores_for_run(run_id)
        instruments = self._repository.instruments_by_ids({item.stock_id for item in models})
        return tuple(
            FactorStockScore(
                as_of_date=item.as_of_date,
                instrument=instruments[item.stock_id],
                raw_factors=dict(item.raw_factors),
                normalized_factors=dict(item.normalized_factors),
                category_scores=dict(item.category_scores),
                factor_score=float(item.factor_score),
                category_coverage=item.category_coverage,
            )
            for item in models
            if item.stock_id in instruments
        )

    @staticmethod
    def _validate_market(market: str) -> None:
        if market not in {"A", "HK", "US"}:
            raise ValueError("market must be A, HK, or US")

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 12)))
