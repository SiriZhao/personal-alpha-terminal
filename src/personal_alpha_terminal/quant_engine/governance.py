from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from math import erf, isfinite, log, pi, sqrt

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import ExperimentRecord, ExperimentResultRecord


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    experiment_id: str
    research_question: str
    strategy_version: str
    data_snapshot: str
    universe_snapshot: str
    factor_versions: dict[str, str]
    parameter_fingerprint: str
    train_dates: tuple[date, date]
    validation_dates: tuple[date, date]
    embargo_sessions: int
    locked_test_dates: tuple[date, date]
    benchmark_versions: dict[str, str]
    cost_model_version: str
    code_commit: str

    def __post_init__(self) -> None:
        if not self.experiment_id.strip() or not self.research_question.strip():
            raise ValueError("experiment identity and research question are required")
        if self.embargo_sessions < 0:
            raise ValueError("embargo sessions cannot be negative")
        train_start, train_end = self.train_dates
        validation_start, validation_end = self.validation_dates
        test_start, test_end = self.locked_test_dates
        periods_are_ordered = (
            train_start
            <= train_end
            < validation_start
            <= validation_end
            < test_start
            <= test_end
        )
        if not periods_are_ordered:
            raise ValueError("experiment periods must be chronological and disjoint")

    @property
    def definition_hash(self) -> str:
        return sha256(
            json.dumps(asdict(self), sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class DataMiningRisk:
    observed_sharpe: float
    expected_max_sharpe: float
    deflated_sharpe_probability: float
    trial_count: int
    observations: int
    acceptable: bool


class ExperimentRegistry:
    """Append-only experiment registry; locked definitions/results are immutable."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, definition: ExperimentDefinition) -> ExperimentRecord:
        existing = self.session.scalars(
            select(ExperimentRecord)
            .where(ExperimentRecord.experiment_id == definition.experiment_id)
            .order_by(ExperimentRecord.version.desc())
        ).first()
        if existing is not None and existing.definition_hash == definition.definition_hash:
            return existing
        version = 1 if existing is None else existing.version + 1
        record = ExperimentRecord(
            experiment_id=definition.experiment_id,
            version=version,
            research_question=definition.research_question,
            strategy_version=definition.strategy_version,
            data_snapshot=definition.data_snapshot,
            universe_snapshot=definition.universe_snapshot,
            factor_versions=definition.factor_versions,
            parameter_fingerprint=definition.parameter_fingerprint,
            train_start=definition.train_dates[0],
            train_end=definition.train_dates[1],
            validation_start=definition.validation_dates[0],
            validation_end=definition.validation_dates[1],
            embargo_sessions=definition.embargo_sessions,
            locked_test_start=definition.locked_test_dates[0],
            locked_test_end=definition.locked_test_dates[1],
            benchmark_versions=definition.benchmark_versions,
            cost_model_version=definition.cost_model_version,
            code_commit=definition.code_commit,
            locked=False,
            locked_at=None,
            definition_hash=definition.definition_hash,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def lock(self, record: ExperimentRecord, *, now: datetime | None = None) -> None:
        if record.locked:
            return
        record.locked = True
        record.locked_at = now or datetime.now(UTC)
        self.session.flush()

    def record_result(
        self,
        record: ExperimentRecord,
        *,
        stage: str,
        metrics: dict[str, object],
        mining_risk: DataMiningRisk,
        status: str,
        evaluated_at: datetime,
    ) -> ExperimentResultRecord:
        if stage not in {"TRAIN", "VALIDATION", "LOCKED_TEST", "WALK_FORWARD"}:
            raise ValueError("unknown experiment stage")
        if stage == "LOCKED_TEST" and not record.locked:
            raise ValueError("locked test cannot be opened before the experiment is locked")
        payload = {"metrics": metrics, "mining_risk": asdict(mining_risk), "status": status}
        result_hash = sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        existing = self.session.scalar(
            select(ExperimentResultRecord).where(
                ExperimentResultRecord.experiment_record_id == record.id,
                ExperimentResultRecord.stage == stage,
            )
        )
        if existing is not None:
            if existing.result_hash != result_hash:
                raise ValueError("experiment result is immutable; create a new experiment version")
            return existing
        result = ExperimentResultRecord(
            experiment_record_id=record.id,
            stage=stage,
            result_hash=result_hash,
            metrics=metrics,
            data_mining_risk=asdict(mining_risk),
            status=status,
            evaluated_at=evaluated_at,
        )
        self.session.add(result)
        self.session.flush()
        return result


def purged_walk_forward_splits(
    observations: int,
    *,
    train_size: int,
    validation_size: int,
    test_size: int,
    embargo: int,
    step: int,
) -> tuple[tuple[slice, slice, slice], ...]:
    if min(train_size, validation_size, test_size, step) <= 0 or embargo < 0:
        raise ValueError("walk-forward sizes are invalid")
    splits: list[tuple[slice, slice, slice]] = []
    start = 0
    while True:
        train_end = start + train_size
        validation_start = train_end + embargo
        validation_end = validation_start + validation_size
        test_start = validation_end + embargo
        test_end = test_start + test_size
        if test_end > observations:
            break
        splits.append(
            (
                slice(start, train_end),
                slice(validation_start, validation_end),
                slice(test_start, test_end),
            )
        )
        start += step
    return tuple(splits)


def deflated_sharpe_risk(
    returns: tuple[float, ...],
    *,
    trial_count: int,
    annualization: int = 252,
    minimum_probability: float = 0.95,
) -> DataMiningRisk:
    if trial_count < 1 or len(returns) < 30:
        raise ValueError("deflated Sharpe requires at least one trial and 30 returns")
    values = np.asarray(returns, dtype=float)
    if np.any(~np.isfinite(values)) or float(values.std(ddof=1)) <= 0:
        raise ValueError("returns must be finite with positive variance")
    observed = float(values.mean() / values.std(ddof=1) * sqrt(annualization))
    # Bailey/Lopez de Prado-style expected maximum under independent trials.
    gamma = 0.5772156649015329
    if trial_count == 1:
        expected_max = 0.0
    else:
        expected_max = sqrt(2 * log(trial_count)) - (
            log(log(trial_count)) + log(4 * pi) - 2 * gamma
        ) / (2 * sqrt(2 * log(trial_count)))
        expected_max /= sqrt(len(values) / annualization)
    centered = values - values.mean()
    std = float(values.std(ddof=0))
    skew = float(np.mean((centered / std) ** 3))
    kurtosis = float(np.mean((centered / std) ** 4))
    daily_sharpe = observed / sqrt(annualization)
    denominator = sqrt(
        max(
            1e-12,
            (
                1
                - skew * daily_sharpe
                + ((kurtosis - 1) / 4) * daily_sharpe**2
            )
            / (len(values) - 1),
        )
    )
    z_score = (daily_sharpe - expected_max / sqrt(annualization)) / denominator
    probability = 0.5 * (1 + erf(z_score / sqrt(2)))
    return DataMiningRisk(
        observed_sharpe=observed,
        expected_max_sharpe=expected_max,
        deflated_sharpe_probability=probability,
        trial_count=trial_count,
        observations=len(values),
        acceptable=isfinite(probability) and probability >= minimum_probability,
    )


def parameter_perturbations(value: float) -> tuple[float, ...]:
    if not isfinite(value):
        raise ValueError("parameter must be finite")
    return tuple(value * multiplier for multiplier in (0.8, 0.9, 1.0, 1.1, 1.2))
