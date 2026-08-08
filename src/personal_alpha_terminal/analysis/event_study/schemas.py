from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class InstrumentOption:
    id: int
    symbol: str
    name: str
    market: str

    @property
    def label(self) -> str:
        return f"{self.symbol} · {self.name} ({self.market})"


@dataclass(frozen=True, slots=True)
class EventDefinitionView:
    id: int
    name: str
    version: int
    description: str | None
    rule_type: str
    parameters: dict[str, object]

    @property
    def label(self) -> str:
        return f"{self.name} · v{self.version}"


@dataclass(frozen=True, slots=True)
class PriceBar:
    date: date
    close: float
    volume: int | None
    available_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventMatch:
    date: date
    trigger_value: float
    reference_value: float | None
    details: dict[str, object]
    available_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventOutcome:
    event: EventMatch
    target: InstrumentOption
    horizon_days: int
    baseline_date: date
    horizon_date: date
    forward_return: float
    max_upside: float
    max_drawdown: float
    is_win: bool


@dataclass(frozen=True, slots=True)
class EventStatistic:
    target: InstrumentOption
    horizon_days: int
    sample_size: int
    positive_probability: float
    win_rate: float
    average_return: float
    median_return: float
    return_stddev: float
    best_return: float
    worst_return: float
    average_max_upside: float
    best_max_upside: float
    average_max_drawdown: float
    worst_max_drawdown: float
    meets_minimum: bool = True
    confidence_level: float = 0.95
    positive_probability_lower: float | None = None
    positive_probability_upper: float | None = None
    win_rate_lower: float | None = None
    win_rate_upper: float | None = None
    average_return_lower: float | None = None
    average_return_upper: float | None = None

    @property
    def inference_status(self) -> str:
        return "eligible" if self.meets_minimum else "low_confidence"


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    run_id: int
    definition: EventDefinitionView
    trigger: InstrumentOption
    start_date: date
    end_date: date
    horizons: tuple[int, ...]
    occurrences: tuple[EventMatch, ...]
    statistics: tuple[EventStatistic, ...]
