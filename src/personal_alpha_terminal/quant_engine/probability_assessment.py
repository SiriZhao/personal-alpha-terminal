"""Immutable research assessment for the production probability fallback.

This artifact records what was actually established by the locked temporal A/B
research.  It is deliberately separate from ``ProbabilityOverlayArtifact``:
an assessment can explain why Classical Alpha remains active, but only a fully
approved overlay artifact can change expected return or portfolio weights.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


@dataclass(frozen=True, slots=True)
class ProbabilityResearchAssessment:
    assessment_id: str
    model_version: str
    strategy_id: str
    strategy_version: str
    strategy_parameter_hash: str
    data_version: str
    feature_fingerprint: str
    training_window: tuple[date, date]
    validation_window: tuple[date, date]
    locked_oos_window: tuple[date, date]
    pit_cutoff_convention: str
    brier_score: float
    baseline_brier_score: float
    log_loss: float
    expected_calibration_error: float
    reliability_bins: tuple[tuple[float, float, int], ...]
    benchmark_relative_outcome_definition: str
    roc_auc: float
    classical_net_return: float
    probability_net_return: float
    classical_sharpe: float
    probability_sharpe: float
    classical_max_drawdown: float
    probability_max_drawdown: float
    classical_turnover: float
    probability_turnover: float
    classical_cost: float
    probability_cost: float
    target_change_count: int
    walk_forward_rebalance_dates: int
    source_artifact_hash: str
    source_path: str
    verdict: str
    production_influence: float
    blockers: tuple[str, ...]
    created_at: datetime
    artifact_hash: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("probability assessment created_at must be timezone-aware")
        if self.production_influence != 0.0:
            raise ValueError("research assessment cannot grant production influence")
        if self.verdict != "NO_INCREMENTAL_ALPHA":
            raise ValueError("non-approved assessment verdict must be NO_INCREMENTAL_ALPHA")
        if not self.blockers:
            raise ValueError("non-approved probability assessment requires blockers")

    def material(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("artifact_hash")
        return payload

    def verify_hash(self) -> bool:
        return fingerprint(self.material()) == self.artifact_hash

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


class ProbabilityAssessmentRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def latest_for_strategy(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        strategy_parameter_hash: str,
        decision_time: datetime,
    ) -> ProbabilityResearchAssessment | None:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        directory = self.root / "probability_assessment"
        matches = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else ():
            artifact = _load(path)
            if (
                artifact.strategy_id == strategy_id
                and artifact.strategy_version == strategy_version
                and artifact.strategy_parameter_hash == strategy_parameter_hash
                and artifact.created_at <= decision_time
            ):
                matches.append(artifact)
        return max(matches, key=lambda item: item.created_at) if matches else None

    def write(self, artifact: ProbabilityResearchAssessment) -> Path:
        directory = self.root / "probability_assessment"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{artifact.assessment_id}.json"
        rendered = json.dumps(artifact.document(), indent=2, sort_keys=True)
        if path.exists():
            if path.read_text(encoding="utf-8") != rendered:
                raise ValueError("refusing to overwrite immutable probability assessment")
            return path
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
        return path


def build_round4_probability_assessment(
    source: Path,
    *,
    strategy_parameter_hash: str,
    created_at: datetime | None = None,
) -> ProbabilityResearchAssessment:
    """Convert the real ROUND 4 research output into a non-promoting artifact."""

    raw = source.read_bytes()
    payload = cast(dict[str, Any], json.loads(raw))
    calibration = cast(dict[str, Any], payload["calibration"])
    identity = cast(dict[str, Any], calibration["identity"])
    ab = cast(dict[str, Any], payload["portfolio_ab"])
    walk = cast(dict[str, Any], payload["walk_forward"])
    bins = tuple(
        (
            float(item["predicted"]),
            float(item["actual"]),
            int(item["count"]),
        )
        for item in cast(list[dict[str, Any]], calibration["reliability_buckets"])
    )
    blockers = [
        "HISTORICAL_PIT_LIMITED",
        "TARGET_WEIGHT_INCREMENTAL_VALUE_NOT_DEMONSTRATED",
        "REQUIRED_AB_METRICS_INCOMPLETE:SORTINO,INFORMATION_RATIO,SPY_ALPHA,QQQ_ALPHA,SLIPPAGE,REGIME_STABILITY",
    ]
    if float(calibration["brier_score"]) >= float(calibration["baseline_brier_score"]):
        blockers.append("BRIER_NOT_BETTER_THAN_BASE_RATE")
    if float(calibration["roc_auc"]) < 0.55:
        blockers.append("DISCRIMINATION_BELOW_FIXED_GATE")
    if float(ab["probability_net_return"]) <= float(ab["classical_net_return"]):
        blockers.append("AFTER_COST_OOS_NOT_IMPROVED")
    if int(ab["probability_target_change_count"]) <= 0:
        blockers.append("TARGET_WEIGHT_CHANGE_COUNT_ZERO")
    assessment_identity = fingerprint(
        {
            "source_calibration_hash": str(calibration["artifact_hash"]),
            "strategy_parameter_hash": strategy_parameter_hash,
        }
    )

    assessment = ProbabilityResearchAssessment(
        assessment_id=f"round4-probability-{assessment_identity[:20]}",
        model_version=str(identity["model_id"]),
        strategy_id=str(identity["strategy_id"]),
        strategy_version=str(identity["strategy_version"]),
        strategy_parameter_hash=strategy_parameter_hash,
        data_version=str(identity["data_version"]),
        feature_fingerprint=str(identity["feature_schema_hash"]),
        training_window=_date_window(calibration["training_period"]),
        validation_window=_date_window(calibration["calibration_period"]),
        locked_oos_window=_date_window(calibration["oos_period"]),
        pit_cutoff_convention=(
            "features and outcomes available no later than each decision cutoff"
        ),
        brier_score=float(calibration["brier_score"]),
        baseline_brier_score=float(calibration["baseline_brier_score"]),
        log_loss=float(calibration["log_loss"]),
        expected_calibration_error=float(calibration["expected_calibration_error"]),
        reliability_bins=bins,
        benchmark_relative_outcome_definition=(
            f"{int(identity['holding_horizon'])}-session forward return relative to "
            f"{identity['benchmark']}; after configured transaction costs"
        ),
        roc_auc=float(calibration["roc_auc"]),
        classical_net_return=float(ab["classical_net_return"]),
        probability_net_return=float(ab["probability_net_return"]),
        classical_sharpe=float(ab["classical_sharpe"]),
        probability_sharpe=float(ab["probability_sharpe"]),
        classical_max_drawdown=float(ab["classical_drawdown"]),
        probability_max_drawdown=float(ab["probability_drawdown"]),
        classical_turnover=float(ab["turnover_classical"]),
        probability_turnover=float(ab["turnover_probability"]),
        classical_cost=float(ab["total_cost_classical"]),
        probability_cost=float(ab["total_cost_probability"]),
        target_change_count=int(ab["probability_target_change_count"]),
        walk_forward_rebalance_dates=int(walk["rebalance_dates"]),
        source_artifact_hash=fingerprint(json.loads(raw)),
        source_path=source.as_posix(),
        verdict="NO_INCREMENTAL_ALPHA",
        production_influence=0.0,
        blockers=tuple(dict.fromkeys(blockers)),
        created_at=created_at or datetime.fromisoformat(str(payload["created_at"])),
        artifact_hash="PENDING",
    )
    return replace(assessment, artifact_hash=fingerprint(assessment.material()))


def _date_window(value: object) -> tuple[date, date]:
    values = cast(list[str], value)
    if len(values) != 2:
        raise ValueError("probability temporal window must contain exactly two dates")
    return date.fromisoformat(values[0]), date.fromisoformat(values[1])


def _load(path: Path) -> ProbabilityResearchAssessment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("training_window", "validation_window", "locked_oos_window"):
        payload[key] = tuple(date.fromisoformat(item) for item in payload[key])
    payload["reliability_bins"] = tuple(tuple(item) for item in payload["reliability_bins"])
    payload["blockers"] = tuple(payload["blockers"])
    payload["created_at"] = datetime.fromisoformat(payload["created_at"])
    artifact = ProbabilityResearchAssessment(**payload)
    if not artifact.verify_hash():
        raise ValueError(f"probability assessment hash mismatch: {path}")
    return artifact
