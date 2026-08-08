from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    permanent_security_id: str
    fiscal_period_end: date
    filing_date: date
    publication_time: datetime
    available_time: datetime
    ingested_time: datetime
    revision_id: str
    source: str
    provider: str
    values: dict[str, float | None]

    def __post_init__(self) -> None:
        if any(
            value.tzinfo is None
            for value in (self.publication_time, self.available_time, self.ingested_time)
        ):
            raise ValueError("fundamental timestamps must be timezone-aware")
        if self.available_time < self.publication_time:
            raise ValueError("fundamental available_time cannot precede publication_time")
        if self.ingested_time < self.available_time:
            raise ValueError("fundamental ingested_time cannot precede available_time")
        if not self.revision_id.strip() or not self.source.strip() or not self.provider.strip():
            raise ValueError("fundamental vintage lineage is required")

    def value_as_of(self, field: str, decision_time: datetime) -> float | None:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        return self.values.get(field) if self.available_time <= decision_time else None
