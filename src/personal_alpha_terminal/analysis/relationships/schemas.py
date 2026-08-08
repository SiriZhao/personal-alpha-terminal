from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class EntityOption:
    id: int
    entity_type: str
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class EntityReturns:
    option: EntityOption
    values: tuple[tuple[date, float], ...]


@dataclass(frozen=True, slots=True)
class CorrelationObservation:
    left: EntityOption
    right: EntityOption
    as_of_date: date
    correlation: float
    sample_size: int
    window_days: int | None = None


@dataclass(frozen=True, slots=True)
class CorrelationAnomaly:
    left: EntityOption
    right: EntityOption
    detected_on: date
    baseline_correlation: float
    current_correlation: float
    absolute_change: float
    threshold: float
    direction: str
    baseline_window_days: int
    current_window_days: int
    baseline_sample_size: int
    current_sample_size: int


@dataclass(frozen=True, slots=True)
class RelationshipResult:
    run_id: int
    universe_type: str
    method: str
    start_date: date
    end_date: date
    entities: tuple[EntityOption, ...]
    matrix: tuple[CorrelationObservation, ...]
    rolling: tuple[CorrelationObservation, ...]
    anomalies: tuple[CorrelationAnomaly, ...]
