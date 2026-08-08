from datetime import date, timedelta
from decimal import Decimal
from typing import cast

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.analysis.market_regime.model import (
    RegimeModel,
    StatisticalRegimeModel,
)
from personal_alpha_terminal.analysis.market_regime.repository import (
    MarketRegimeRepository,
)
from personal_alpha_terminal.analysis.market_regime.schemas import (
    CalibrationCurvePoint,
    CalibrationStatus,
    MarketRegimePoint,
    MarketRegimeResult,
    RegimeCalibrationReport,
    RegimeName,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import MarketRegimeObservation, MarketRegimeRun


class MarketRegimeService:
    """Run, persist, and restore explainable market-regime classifications."""

    def __init__(
        self,
        repository: MarketRegimeRepository,
        settings: Settings,
        model: RegimeModel | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._model = model or StatisticalRegimeModel()

    def list_instruments(self) -> tuple[GraphInstrument, ...]:
        return tuple(self._repository.list_instruments())

    def run(
        self,
        *,
        vix_stock_id: int,
        rate_stock_id: int,
        dollar_stock_id: int,
        benchmark_stock_id: int,
        market: str,
        start_date: date,
        end_date: date,
    ) -> MarketRegimeResult:
        if market not in {"A", "HK", "US"}:
            raise ValueError("market must be A, HK, or US")
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        driver_ids = (
            vix_stock_id,
            rate_stock_id,
            dollar_stock_id,
            benchmark_stock_id,
        )
        if len(set(driver_ids)) != 4:
            raise ValueError("VIX, rate, dollar, and benchmark must be distinct instruments")
        if (
            self._settings.regime_minimum_calibration_observations
            > self._settings.regime_calibration_window
        ):
            raise ValueError("minimum calibration observations cannot exceed calibration window")

        parameters = self._model.parameters(self._settings)
        parameters.update(
            {
                "driver_ids": {
                    "vix": vix_stock_id,
                    "rate": rate_stock_id,
                    "dollar": dollar_stock_id,
                    "benchmark": benchmark_stock_id,
                },
                "market": market,
                "breadth_universe": "latest_snapshot_available_at_each_as_of_date",
                "date_alignment": "exact_common_dates_no_forward_fill",
            }
        )
        run = MarketRegimeRun(
            start_date=start_date,
            end_date=end_date,
            market=market,
            model_type=self._model.model_type,
            model_version=self._model.model_version,
            vix_stock_id=vix_stock_id,
            rate_stock_id=rate_stock_id,
            dollar_stock_id=dollar_stock_id,
            benchmark_stock_id=benchmark_stock_id,
            status="running",
            parameters=parameters,
            calibration_status="score_only",
            calibration_method="pending",
            calibration_observation_count=0,
            calibration_curve=[],
            calibration_reasons=[],
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            maximum_feature_window = max(
                self._settings.regime_rate_change_window,
                self._settings.regime_dollar_trend_window,
                self._settings.regime_index_trend_window,
                self._settings.regime_breadth_window,
            )
            required_history = max(
                self._settings.regime_calibration_window,
                self._settings.regime_probability_minimum_training_observations
                + self._settings.regime_probability_minimum_oos_observations
                + self._settings.regime_probability_label_horizon,
            ) + maximum_feature_window
            query_start = start_date - timedelta(days=required_history * 2 + 30)
            data = self._repository.load_market_data(
                vix_stock_id=vix_stock_id,
                rate_stock_id=rate_stock_id,
                dollar_stock_id=dollar_stock_id,
                benchmark_stock_id=benchmark_stock_id,
                market=market,
                query_start_date=query_start,
                end_date=end_date,
                maximum_breadth_assets=(self._settings.regime_maximum_breadth_assets),
            )
            all_observations, calibration = self._model.calculate(data, self._settings)
            observations = tuple(
                item for item in all_observations if start_date <= item.as_of_date <= end_date
            )
            if not observations:
                raise ValueError(
                    "insufficient aligned history or breadth data for regime detection"
                )
            self._persist_observations(run.id, observations)
            self._persist_calibration(run, calibration)
            run.status = "completed"
            self._repository.session.flush()
            return MarketRegimeResult(
                run_id=run.id,
                start_date=start_date,
                end_date=end_date,
                market=market,
                model_type=self._model.model_type,
                model_version=self._model.model_version,
                observations=observations,
                calibration=calibration,
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self) -> MarketRegimeResult | None:
        run = self._repository.latest_run()
        if run is None:
            return None
        observations = tuple(
            MarketRegimePoint(
                as_of_date=item.as_of_date,
                regime=cast(RegimeName, item.regime),
                risk_on_score=float(item.risk_on_score),
                risk_off_score=float(item.risk_off_score),
                neutral_score=float(item.neutral_score),
                composite_score=float(item.composite_score),
                breadth_constituent_count=item.breadth_constituent_count,
                feature_values=dict(item.feature_values),
                feature_zscores=dict(item.feature_zscores),
                feature_contributions=dict(item.feature_contributions),
                risk_on_probability=self._optional_float(item.risk_on_probability),
                risk_off_probability=self._optional_float(item.risk_off_probability),
                neutral_probability=self._optional_float(item.neutral_probability),
            )
            for item in self._repository.observations_for_run(run.id)
        )
        return MarketRegimeResult(
            run_id=run.id,
            start_date=run.start_date,
            end_date=run.end_date,
            market=run.market,
            model_type=run.model_type,
            model_version=run.model_version,
            observations=observations,
            calibration=self._restore_calibration(run),
        )

    def _persist_observations(
        self,
        run_id: int,
        observations: tuple[MarketRegimePoint, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                MarketRegimeObservation(
                    run_id=run_id,
                    as_of_date=item.as_of_date,
                    regime=item.regime,
                    risk_on_score=self._decimal(item.risk_on_score),
                    risk_off_score=self._decimal(item.risk_off_score),
                    neutral_score=self._decimal(item.neutral_score),
                    risk_on_probability=self._optional_decimal(item.risk_on_probability),
                    risk_off_probability=self._optional_decimal(item.risk_off_probability),
                    neutral_probability=self._optional_decimal(item.neutral_probability),
                    composite_score=self._decimal(item.composite_score),
                    breadth_constituent_count=item.breadth_constituent_count,
                    feature_values=item.feature_values,
                    feature_zscores=item.feature_zscores,
                    feature_contributions=item.feature_contributions,
                )
                for item in observations
            ]
        )

    def _persist_calibration(
        self,
        run: MarketRegimeRun,
        calibration: RegimeCalibrationReport,
    ) -> None:
        run.calibration_status = calibration.status
        run.calibration_method = calibration.method
        run.calibration_observation_count = calibration.out_of_sample_count
        run.brier_score = self._optional_decimal(calibration.brier_score)
        run.raw_score_brier = self._optional_decimal(calibration.raw_score_brier)
        run.baseline_brier = self._optional_decimal(calibration.baseline_brier)
        run.calibration_curve = [
            {
                "regime": item.regime,
                "bin_lower": item.bin_lower,
                "bin_upper": item.bin_upper,
                "mean_predicted": item.mean_predicted,
                "observed_frequency": item.observed_frequency,
                "sample_size": item.sample_size,
            }
            for item in calibration.calibration_curve
        ]
        run.calibration_reasons = list(calibration.reasons)

    def _restore_calibration(self, run: MarketRegimeRun) -> RegimeCalibrationReport:
        return RegimeCalibrationReport(
            status=cast(CalibrationStatus, run.calibration_status),
            method=run.calibration_method,
            label_horizon_days=self._json_int(
                run.parameters.get("probability_label_horizon"), 20
            ),
            risk_on_return_threshold=self._json_float(
                run.parameters.get("probability_return_threshold"), 0.02
            ),
            risk_off_return_threshold=-self._json_float(
                run.parameters.get("probability_return_threshold"), 0.02
            ),
            training_minimum=self._json_int(
                run.parameters.get("probability_minimum_training_observations"), 252
            ),
            out_of_sample_count=run.calibration_observation_count,
            brier_score=self._optional_float(run.brier_score),
            raw_score_brier=self._optional_float(run.raw_score_brier),
            baseline_brier=self._optional_float(run.baseline_brier),
            calibration_curve=tuple(
                CalibrationCurvePoint(
                    regime=cast(RegimeName, item["regime"]),
                    bin_lower=self._json_float(item.get("bin_lower"), 0.0),
                    bin_upper=self._json_float(item.get("bin_upper"), 0.0),
                    mean_predicted=self._json_float(item.get("mean_predicted"), 0.0),
                    observed_frequency=self._json_float(
                        item.get("observed_frequency"), 0.0
                    ),
                    sample_size=self._json_int(item.get("sample_size"), 0),
                )
                for item in run.calibration_curve
            ),
            reasons=tuple(run.calibration_reasons),
        )

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 16)))

    @classmethod
    def _optional_decimal(cls, value: float | None) -> Decimal | None:
        return cls._decimal(value) if value is not None else None

    @staticmethod
    def _optional_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _json_int(value: object, default: int) -> int:
        if isinstance(value, (int, float, str)):
            return int(value)
        return default

    @staticmethod
    def _json_float(value: object, default: float) -> float:
        if isinstance(value, (int, float, str)):
            return float(value)
        return default
