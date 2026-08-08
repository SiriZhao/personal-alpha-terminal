from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Literal

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument

ShockUnit = Literal["decimal_return", "basis_points", "standard_score"]
ScenarioType = Literal["custom", "historical", "hypothetical"]
EvidenceLevel = Literal[
    "source_backed",
    "calibrated_historical",
    "user_assumption",
    "illustrative",
]
RiskLevel = Literal["Low", "Medium", "High", "Critical"]


@dataclass(frozen=True, slots=True)
class RiskFactorDefinition:
    code: str
    name: str
    category: str
    shock_unit: ShockUnit
    description: str
    normalized_minimum: float
    normalized_maximum: float

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise ValueError("risk factor code and name cannot be empty")
        if self.normalized_minimum >= self.normalized_maximum:
            raise ValueError("risk factor normalized bounds are invalid")


@dataclass(frozen=True, slots=True)
class FactorShock:
    factor_code: str
    magnitude: float
    unit: ShockUnit
    rationale: str

    def __post_init__(self) -> None:
        if not self.factor_code.strip() or not self.rationale.strip():
            raise ValueError("factor shock requires a code and rationale")
        if not isfinite(self.magnitude):
            raise ValueError("factor shock magnitude must be finite")

    @property
    def normalized_magnitude(self) -> float:
        if self.unit == "basis_points":
            return self.magnitude / 100
        return self.magnitude


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    name: str
    scenario_type: ScenarioType
    description: str
    factor_shocks: tuple[FactorShock, ...]
    currency_shocks: dict[str, float]
    evidence_level: EvidenceLevel
    data_sources: tuple[str, ...]
    historical_start: date | None = None
    historical_end: date | None = None
    is_builtin: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.description.strip():
            raise ValueError("scenario name and description cannot be empty")
        if not self.factor_shocks and not self.currency_shocks:
            raise ValueError("scenario requires at least one factor or currency shock")
        codes = [item.factor_code for item in self.factor_shocks]
        if len(codes) != len(set(codes)):
            raise ValueError("scenario factor shocks must be unique")
        if any(
            not currency.strip()
            or len(currency) != 3
            or not currency.isalpha()
            or currency != currency.upper()
            or not isfinite(shock)
            or not -1 <= shock <= 10
            for currency, shock in self.currency_shocks.items()
        ):
            raise ValueError(
                "currency shocks require uppercase ISO-like codes and finite "
                "values between -100% and 1000%"
            )
        if self.scenario_type == "historical":
            if self.historical_start is None or self.historical_end is None:
                raise ValueError("historical scenario requires a date window")
            if self.historical_start >= self.historical_end:
                raise ValueError("historical scenario date window is invalid")
        if not self.data_sources or any(not item.strip() for item in self.data_sources):
            raise ValueError("scenario requires explicit source or assumption labels")


@dataclass(frozen=True, slots=True)
class AssetFactorExposure:
    asset_id: int
    factor_code: str
    sensitivity: float
    sensitivity_low: float
    sensitivity_high: float
    as_of_date: date
    method: str
    source: str
    confidence_score: int

    def __post_init__(self) -> None:
        if self.asset_id <= 0 or not self.factor_code.strip():
            raise ValueError("asset exposure requires a positive asset id and factor")
        values = (self.sensitivity, self.sensitivity_low, self.sensitivity_high)
        if not all(isfinite(item) for item in values):
            raise ValueError("asset exposure sensitivities must be finite")
        if not self.sensitivity_low <= self.sensitivity <= self.sensitivity_high:
            raise ValueError("asset exposure sensitivity interval is invalid")
        if not self.method.strip() or not self.source.strip():
            raise ValueError("asset exposure requires method and source")
        if not 0 <= self.confidence_score <= 100:
            raise ValueError("asset exposure confidence must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class ScenarioPosition:
    instrument: GraphInstrument
    currency: str
    market_value: float
    weight: float

    def __post_init__(self) -> None:
        if (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise ValueError("position currency must be a three-letter uppercase code")
        if self.market_value < 0 or not isfinite(self.market_value):
            raise ValueError("position market value must be finite and nonnegative")
        if not 0 <= self.weight <= 1 or not isfinite(self.weight):
            raise ValueError("position weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ScenarioPortfolio:
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    as_of_date: date
    total_value: float
    cash_value: float
    positions: tuple[ScenarioPosition, ...]

    def __post_init__(self) -> None:
        if self.portfolio_id <= 0 or not self.portfolio_name.strip():
            raise ValueError("scenario portfolio identity is invalid")
        if (
            len(self.base_currency) != 3
            or not self.base_currency.isalpha()
            or self.base_currency != self.base_currency.upper()
        ):
            raise ValueError("portfolio base currency must be a three-letter uppercase code")
        if self.total_value <= 0 or self.cash_value < 0:
            raise ValueError("portfolio and cash values must be nonnegative")
        asset_ids = [item.instrument.id for item in self.positions]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("scenario portfolio positions must be unique")
        position_value = sum(item.market_value for item in self.positions)
        tolerance = max(0.01, self.total_value * 1e-8)
        if abs(position_value + self.cash_value - self.total_value) > tolerance:
            raise ValueError("position values plus cash do not reconcile to total value")
        for item in self.positions:
            expected_weight = item.market_value / self.total_value
            if abs(item.weight - expected_weight) > 1e-8:
                raise ValueError("position weight does not reconcile to current market value")


@dataclass(frozen=True, slots=True)
class FactorContribution:
    factor_code: str
    normalized_shock: float
    sensitivity: float
    contribution: float
    sensitivity_low: float
    sensitivity_high: float
    source: str
    confidence_score: int


@dataclass(frozen=True, slots=True)
class PositionScenarioImpact:
    instrument: GraphInstrument
    currency: str
    weight: float
    original_value: float
    factor_return: float
    currency_return: float
    combined_return: float
    return_low: float
    return_high: float
    contribution: float
    stressed_value: float
    mapped: bool
    factor_contributions: tuple[FactorContribution, ...]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    run_id: int | None
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    as_of_date: date
    scenario: ScenarioDefinition
    original_value: float
    stressed_value: float
    pnl_amount: float
    pnl_percent: float
    pnl_percent_low: float
    pnl_percent_high: float
    risk_level: RiskLevel
    mapped_weight: float
    uncovered_weight: float
    confidence_score: int
    data_fingerprint: str
    impacts: tuple[PositionScenarioImpact, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HistoricalFactorPoint:
    date: date
    value: float

    def __post_init__(self) -> None:
        if not isfinite(self.value):
            raise ValueError("historical factor point must be finite")


@dataclass(frozen=True, slots=True)
class HistoricalFactorSeries:
    factor_code: str
    unit: ShockUnit
    points: tuple[HistoricalFactorPoint, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.factor_code.strip() or not self.source.strip():
            raise ValueError("historical factor series requires factor and source")
        if len(self.points) < 2:
            raise ValueError("historical factor series requires at least two points")
        point_dates = [item.date for item in self.points]
        if len(point_dates) != len(set(point_dates)):
            raise ValueError("historical factor series dates must be unique")


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    portfolio_id: int
    as_of_date: date
    results: tuple[ScenarioResult, ...]

    def __post_init__(self) -> None:
        if self.portfolio_id <= 0 or not self.results:
            raise ValueError("scenario comparison requires a portfolio and results")
        if any(
            item.portfolio_id != self.portfolio_id or item.as_of_date != self.as_of_date
            for item in self.results
        ):
            raise ValueError("scenario comparison results must share one snapshot")
