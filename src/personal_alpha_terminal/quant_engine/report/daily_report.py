from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DailyQuantReport:
    generated_at: datetime
    data_gate_status: str
    market_regime_label: str
    market_regime_is_calibrated: bool
    portfolio_health_score: float | None
    decision_count: int
    blockers: tuple[str, ...]
    sources: tuple[str, ...]


class DailyQuantReportBuilder:
    def build(
        self,
        *,
        generated_at: datetime,
        data_gate_status: str,
        market_regime_label: str,
        market_regime_is_calibrated: bool,
        portfolio_health_score: float | None,
        decision_count: int,
        blockers: tuple[str, ...],
        sources: tuple[str, ...],
    ) -> DailyQuantReport:
        if generated_at.tzinfo is None:
            raise ValueError("daily report timestamp must be timezone-aware")
        if data_gate_status == "BLOCKED" and decision_count:
            raise ValueError("a blocked data gate cannot publish decisions")
        if not market_regime_is_calibrated and "probability" in market_regime_label.lower():
            raise ValueError("uncalibrated market regime must be labeled as a score")
        if not sources and data_gate_status != "BLOCKED":
            raise ValueError("non-blocked daily report requires data sources")
        return DailyQuantReport(
            generated_at,
            data_gate_status,
            market_regime_label,
            market_regime_is_calibrated,
            portfolio_health_score,
            decision_count,
            blockers,
            sources,
        )
