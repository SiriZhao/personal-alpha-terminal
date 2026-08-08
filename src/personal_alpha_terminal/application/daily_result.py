from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast


class StageStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class DecisionReadiness(StrEnum):
    READY = "READY"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    status: StageStatus
    duration_seconds: float
    message: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class DataHealthItem:
    dataset: str
    expected_date: date | None
    latest_date: date | None
    age_days: int | None
    coverage: float | None
    missing_ratio: float | None
    source: str
    status: StageStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class FactorRow:
    symbol: str
    components: dict[str, float]
    composite: float
    rank: int
    expected_alpha: float
    confidence: float
    status: str


@dataclass(frozen=True, slots=True)
class ProbabilityRow:
    condition: str
    target: str
    sample_size: int
    hits: int | None
    conditional_probability: float | None
    base_probability: float | None
    lift: float | None
    average_return: float | None
    median_return: float | None
    return_std: float | None
    credible_interval: tuple[float, float] | None
    reliability: str
    oos_status: str
    status: str


@dataclass(frozen=True, slots=True)
class PortfolioPositionRow:
    symbol: str
    shares: float | None
    price: float | None
    current_weight: float
    target_weight: float | None
    delta_weight: float | None


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    status: str
    nav: float | None
    cash: float | None
    cash_weight: float | None
    invested_weight: float | None
    positions: tuple[PortfolioPositionRow, ...]


@dataclass(frozen=True, slots=True)
class RiskSummary:
    status: str
    expected_volatility: float | None
    target_volatility: float | None
    drawdown: float | None
    hhi: float | None
    turnover: float | None
    gross_exposure: float | None
    cash_target: float | None
    exposure_multiplier: float | None
    largest_target_weight: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionRow:
    recommendation_id: str
    symbol: str
    action: str
    current_weight: float
    target_weight: float
    delta_weight: float
    estimated_value: float
    estimated_quantity: int
    estimated_cost: float
    expected_alpha: float
    confidence: float
    risk_contribution: float
    reason: str
    data_quality: str
    model_version: str
    data_version: str
    earliest_execution_time: datetime
    expiry: datetime


@dataclass(frozen=True, slots=True)
class RejectedSignalRow:
    symbol: str
    rejected_by: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionLeg:
    sequence: int
    symbol: str
    action: str
    estimated_value: float
    estimated_quantity: int
    estimated_cost: float
    earliest_execution_time: datetime


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    status: str
    manual_execution_required: bool
    broker: str
    estimated_cash_before: float | None
    estimated_proceeds: float
    estimated_buys: float
    estimated_cash_after: float | None
    turnover: float | None
    estimated_cost: float
    legs: tuple[ExecutionLeg, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    name: str
    status: str
    observation_count: int
    period_return: float | None
    annualized_volatility: float | None
    note: str


@dataclass(frozen=True, slots=True)
class DailyQuantResult:
    run_id: str
    version: str
    started_at: datetime
    finished_at: datetime
    analysis_date: date
    trade_date: date
    market_session: str
    market_structure: str
    data_cutoff: datetime | None
    decision_readiness: DecisionReadiness
    llm_status: str
    stages: tuple[StageResult, ...]
    data_health: tuple[DataHealthItem, ...]
    market_regime: str
    market_regime_detail: str
    factors: tuple[FactorRow, ...]
    probabilities: tuple[ProbabilityRow, ...]
    candidates: tuple[FactorRow, ...]
    portfolio: PortfolioSummary
    risk: RiskSummary
    final_decisions: tuple[DecisionRow, ...]
    rejected_signals: tuple[RejectedSignalRow, ...]
    execution_plan: ExecutionPlan
    benchmarks: tuple[BenchmarkSummary, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance: dict[str, object]
    config_hash: str
    model_versions: tuple[str, ...]

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())

    @property
    def actionable(self) -> bool:
        return self.decision_readiness is DecisionReadiness.READY

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_value(asdict(self)))

    def persist(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"{self.analysis_date.isoformat()}_{self.run_id}.json"
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(output)
        return output


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value
