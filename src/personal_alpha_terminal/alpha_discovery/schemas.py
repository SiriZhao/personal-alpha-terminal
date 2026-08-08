from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument

FactorDirection = Literal["high", "low"]
FactorScope = Literal["cross_sectional", "time_series"]
SplitName = Literal["full", "train", "validation", "test"]


@dataclass(frozen=True, slots=True)
class FactorDefinition:
    name: str
    category: str
    direction: FactorDirection
    scope: FactorScope
    description: str
    formula: str
    minimum_history: int = 0


@dataclass(frozen=True, slots=True)
class MarketEnvironmentPoint:
    date: date
    available_at: datetime
    vix: float | None = None
    interest_rate: float | None = None
    dollar_index: float | None = None
    market_breadth: float | None = None
    source: str = "unknown"


@dataclass(frozen=True, slots=True)
class FactorObservation:
    as_of_date: date
    forward_end_date: date
    instrument: GraphInstrument
    factor_values: dict[str, float | None]
    forward_return: float


@dataclass(frozen=True, slots=True)
class FactorPanel:
    market: str
    horizon_days: int
    definitions: tuple[FactorDefinition, ...]
    observations: tuple[FactorObservation, ...]
    data_fingerprint: str

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(sorted({item.as_of_date for item in self.observations}))


@dataclass(frozen=True, slots=True)
class ICEvaluation:
    factor_name: str
    split_name: SplitName
    evaluation_axis: FactorScope
    date_count: int
    observation_count: int
    raw_mean_ic: float | None
    directional_mean_ic: float | None
    median_ic: float | None
    ic_standard_deviation: float | None
    information_ratio: float | None
    positive_ratio: float | None
    pearson_ic: float | None
    p_value: float | None
    adjusted_p_value: float | None
    significant: bool
    confidence_score: int
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    purged_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class AlphaDiscoveryConfig:
    horizon_days: int = 21
    rebalance_interval: int = 21
    minimum_cross_section: int = 20
    minimum_dates_per_split: int = 12
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    fdr_alpha: float = 0.10
    minimum_abs_directional_ic: float = 0.02
    maximum_factor_correlation: float = 0.85
    maximum_combination_size: int = 3
    maximum_candidate_factors: int = 12
    maximum_selected_combinations: int = 10
    maximum_universe_size: int = 2000
    selection_quantile: float = 0.20
    environment_max_staleness_days: int = 5

    def __post_init__(self) -> None:
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be positive")
        if self.rebalance_interval < self.horizon_days:
            raise ValueError("rebalance_interval must be at least horizon_days to avoid overlap")
        if self.minimum_cross_section < 3:
            raise ValueError("minimum_cross_section must be at least 3")
        if self.minimum_dates_per_split < 3:
            raise ValueError("minimum_dates_per_split must be at least 3")
        if not 0 < self.train_fraction < 1:
            raise ValueError("train_fraction must be between 0 and 1")
        if not 0 < self.validation_fraction < 1:
            raise ValueError("validation_fraction must be between 0 and 1")
        if self.train_fraction + self.validation_fraction >= 1:
            raise ValueError("train and validation fractions must leave a test set")
        if not 0 < self.fdr_alpha < 1:
            raise ValueError("fdr_alpha must be between 0 and 1")
        if not 0 <= self.minimum_abs_directional_ic <= 1:
            raise ValueError("minimum_abs_directional_ic must be between 0 and 1")
        if not 0 < self.maximum_factor_correlation < 1:
            raise ValueError("maximum_factor_correlation must be between 0 and 1")
        if not 1 <= self.maximum_combination_size <= 5:
            raise ValueError("maximum_combination_size must be between 1 and 5")
        if self.maximum_candidate_factors < 1:
            raise ValueError("maximum_candidate_factors must be positive")
        if self.maximum_selected_combinations < 1:
            raise ValueError("maximum_selected_combinations must be positive")
        if self.maximum_universe_size < self.minimum_cross_section:
            raise ValueError("maximum_universe_size cannot be below minimum_cross_section")
        if not 0 < self.selection_quantile <= 0.5:
            raise ValueError("selection_quantile must be in (0, 0.5]")
        if self.environment_max_staleness_days < 0:
            raise ValueError("environment_max_staleness_days cannot be negative")


@dataclass(frozen=True, slots=True)
class FactorCombinationEvaluation:
    rank: int
    factors: tuple[str, ...]
    weights: tuple[float, ...]
    train: ICEvaluation
    validation: ICEvaluation
    test: ICEvaluation
    train_long_short_return: float | None
    validation_long_short_return: float | None
    test_long_short_return: float | None
    maximum_pairwise_correlation: float
    confidence_score: int
    status: Literal["test_confirmed", "test_not_confirmed"]
    selection_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FactorSelectionResult:
    split: ChronologicalSplit
    factor_evaluations: tuple[ICEvaluation, ...]
    combinations: tuple[FactorCombinationEvaluation, ...]
    tested_factor_count: int
    tested_combination_count: int


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_number: int
    train_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    purged_train_dates: tuple[date, ...]
    train: ICEvaluation
    test: ICEvaluation
    confirmed: bool


@dataclass(frozen=True, slots=True)
class WalkForwardValidationResult:
    factors: tuple[str, ...]
    folds: tuple[WalkForwardFold, ...]
    mean_out_of_sample_ic: float | None
    positive_fold_ratio: float
    confirmed_fold_ratio: float
    confidence_score: int
    status: Literal["stable", "unstable"]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlphaDiscoveryResult:
    run_id: int | None
    market: str
    start_date: date
    end_date: date
    horizon_days: int
    data_fingerprint: str
    split: ChronologicalSplit
    factor_evaluations: tuple[ICEvaluation, ...]
    combinations: tuple[FactorCombinationEvaluation, ...]
    tested_factor_count: int
    tested_combination_count: int
