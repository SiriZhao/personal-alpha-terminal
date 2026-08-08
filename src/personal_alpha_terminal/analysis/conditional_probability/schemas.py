from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.analysis.event_study.schemas import (
    EventDefinitionView,
    InstrumentOption,
)


@dataclass(frozen=True, slots=True)
class ProbabilityEstimate:
    target: InstrumentOption
    horizon_days: int
    sample_size: int
    success_count: int
    meets_minimum: bool
    probability: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    average_return: float | None
    raw_probability: float | None = None
    prior_alpha: float = 1.0
    prior_beta: float = 1.0


@dataclass(frozen=True, slots=True)
class ConditionalProbabilityStudy:
    run_id: int
    event_study_run_id: int
    condition: EventDefinitionView
    trigger: InstrumentOption
    start_date: date
    end_date: date
    outcome_direction: str
    outcome_threshold: float
    minimum_sample_size: int
    confidence_level: float
    event_count: int
    results: tuple[ProbabilityEstimate, ...]
