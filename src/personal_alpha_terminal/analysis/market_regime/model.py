from typing import Protocol

from personal_alpha_terminal.analysis.market_regime.calibration import (
    walk_forward_calibrate,
)
from personal_alpha_terminal.analysis.market_regime.schemas import (
    MarketRegimePoint,
    RegimeCalibrationReport,
    RegimeMarketData,
)
from personal_alpha_terminal.analysis.market_regime.statistics import (
    FEATURE_WEIGHTS,
    build_raw_features,
    classify_regimes,
)
from personal_alpha_terminal.core.config import Settings


class RegimeModel(Protocol):
    """Extension seam for future statistical or machine-learning models."""

    model_type: str
    model_version: str

    def calculate(
        self,
        data: RegimeMarketData,
        settings: Settings,
    ) -> tuple[tuple[MarketRegimePoint, ...], RegimeCalibrationReport]: ...

    def parameters(self, settings: Settings) -> dict[str, object]: ...


class StatisticalRegimeModel:
    """Causal score model with guarded walk-forward probability calibration."""

    model_type = "statistical"
    model_version = "2.0"

    def calculate(
        self,
        data: RegimeMarketData,
        settings: Settings,
    ) -> tuple[tuple[MarketRegimePoint, ...], RegimeCalibrationReport]:
        raw_features = build_raw_features(
            data,
            rate_window=settings.regime_rate_change_window,
            dollar_window=settings.regime_dollar_trend_window,
            index_window=settings.regime_index_trend_window,
            breadth_window=settings.regime_breadth_window,
            minimum_breadth_assets=settings.regime_minimum_breadth_assets,
        )
        scores = classify_regimes(
            raw_features,
            calibration_window=settings.regime_calibration_window,
            minimum_calibration_observations=(settings.regime_minimum_calibration_observations),
            softmax_temperature=settings.regime_softmax_temperature,
            neutral_bias=settings.regime_neutral_bias,
        )
        return walk_forward_calibrate(
            scores,
            data.benchmark.prices,
            label_horizon_days=settings.regime_probability_label_horizon,
            return_threshold=settings.regime_probability_return_threshold,
            minimum_training_observations=(
                settings.regime_probability_minimum_training_observations
            ),
            minimum_out_of_sample_observations=(
                settings.regime_probability_minimum_oos_observations
            ),
            minimum_class_observations=(
                settings.regime_probability_minimum_class_observations
            ),
            bins=settings.regime_probability_calibration_bins,
            minimum_bin_observations=(
                settings.regime_probability_minimum_bin_observations
            ),
            minimum_brier_improvement=(
                settings.regime_probability_minimum_brier_improvement
            ),
            data_eligible=data.calibration_eligible,
            data_limitations=data.calibration_limitations,
        )

    def parameters(self, settings: Settings) -> dict[str, object]:
        return {
            "features": list(FEATURE_WEIGHTS),
            "weights": dict(FEATURE_WEIGHTS),
            "rate_change_window": settings.regime_rate_change_window,
            "dollar_trend_window": settings.regime_dollar_trend_window,
            "index_trend_window": settings.regime_index_trend_window,
            "breadth_window": settings.regime_breadth_window,
            "calibration_window": settings.regime_calibration_window,
            "minimum_calibration_observations": (settings.regime_minimum_calibration_observations),
            "minimum_breadth_assets": settings.regime_minimum_breadth_assets,
            "softmax_temperature": settings.regime_softmax_temperature,
            "neutral_bias": settings.regime_neutral_bias,
            "standardization": "prior_observations_only_sample_standard_deviation",
            "zscore_clip": 3.0,
            "raw_output_name": "market_regime_score",
            "raw_score_method": "three_class_softmax_normalized_score",
            "probability_calibration": "walk_forward_fixed_bin_beta_smoothing",
            "probability_label_horizon": settings.regime_probability_label_horizon,
            "probability_return_threshold": settings.regime_probability_return_threshold,
            "probability_minimum_training_observations": (
                settings.regime_probability_minimum_training_observations
            ),
            "probability_minimum_oos_observations": (
                settings.regime_probability_minimum_oos_observations
            ),
            "probability_minimum_class_observations": (
                settings.regime_probability_minimum_class_observations
            ),
            "probability_calibration_bins": settings.regime_probability_calibration_bins,
            "probability_minimum_bin_observations": (
                settings.regime_probability_minimum_bin_observations
            ),
            "probability_minimum_brier_improvement": (
                settings.regime_probability_minimum_brier_improvement
            ),
            "probability_gate": (
                "requires certified point-in-time data, adequate OOS class coverage, "
                "and Brier improvement over raw scores and expanding climatology"
            ),
        }
