from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ReportDocument:
    report_type: str
    as_of_date: date
    subject_key: str | None
    title: str
    markdown: str
    data_sources: tuple[str, ...]
    methodology: tuple[str, ...]
    risk_factors: tuple[str, ...]
