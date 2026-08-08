from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument

RegimeName = Literal["risk_on", "risk_off", "neutral"]
CalibrationStatus = Literal["calibrated", "score_only"]


@dataclass(frozen=True, slots=True)
class RegimePricePoint:
    date: date
    close: float
    volume: int | None


@dataclass(frozen=True, slots=True)
class RegimeAssetSeries:
    instrument: GraphInstrument
    prices: tuple[RegimePricePoint, ...]


@dataclass(frozen=True, slots=True)
class RegimeUniversePoint:
    snapshot_id: int
    as_of_date: date
    available_at: datetime
    asset_ids: frozenset[int]
    source: str


@dataclass(frozen=True, slots=True)
class RegimeMarketData:
    vix: RegimeAssetSeries
    rate: RegimeAssetSeries
    dollar: RegimeAssetSeries
    benchmark: RegimeAssetSeries
    breadth_constituents: tuple[RegimeAssetSeries, ...]
    breadth_universe_timeline: tuple[RegimeUniversePoint, ...] = ()
    calibration_eligible: bool = False
    calibration_limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RawRegimeFeatures:
    as_of_date: date
    values: dict[str, float]
    breadth_constituent_count: int


@dataclass(frozen=True, slots=True)
class MarketRegimePoint:
    as_of_date: date
    regime: RegimeName
    risk_on_score: float
    risk_off_score: float
    neutral_score: float
    composite_score: float
    breadth_constituent_count: int
    feature_values: dict[str, float]
    feature_zscores: dict[str, float]
    feature_contributions: dict[str, float]
    risk_on_probability: float | None = None
    risk_off_probability: float | None = None
    neutral_probability: float | None = None

    @property
    def scores(self) -> dict[RegimeName, float]:
        return {
            "risk_on": self.risk_on_score,
            "risk_off": self.risk_off_score,
            "neutral": self.neutral_score,
        }

    @property
    def probabilities(self) -> dict[RegimeName, float] | None:
        risk_on = self.risk_on_probability
        risk_off = self.risk_off_probability
        neutral = self.neutral_probability
        values = (risk_on, risk_off, neutral)
        if any(value is None for value in values):
            return None
        assert risk_on is not None and risk_off is not None and neutral is not None
        return {
            "risk_on": risk_on,
            "risk_off": risk_off,
            "neutral": neutral,
        }


@dataclass(frozen=True, slots=True)
class CalibrationCurvePoint:
    regime: RegimeName
    bin_lower: float
    bin_upper: float
    mean_predicted: float
    observed_frequency: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class RegimeCalibrationReport:
    status: CalibrationStatus
    method: str
    label_horizon_days: int
    risk_on_return_threshold: float
    risk_off_return_threshold: float
    training_minimum: int
    out_of_sample_count: int
    brier_score: float | None
    raw_score_brier: float | None
    baseline_brier: float | None
    calibration_curve: tuple[CalibrationCurvePoint, ...]
    reasons: tuple[str, ...]

    @property
    def probability_output_enabled(self) -> bool:
        return self.status == "calibrated"


@dataclass(frozen=True, slots=True)
class MarketRegimeResult:
    run_id: int
    start_date: date
    end_date: date
    market: str
    model_type: str
    model_version: str
    observations: tuple[MarketRegimePoint, ...]
    calibration: RegimeCalibrationReport

    @property
    def current(self) -> MarketRegimePoint:
        if not self.observations:
            raise ValueError("market regime result has no observations")
        return self.observations[-1]
