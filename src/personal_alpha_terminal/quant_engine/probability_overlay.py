"""Strictly gated probability residual overlay for production expected returns.

The overlay is additive because it estimates an out-of-sample residual return
conditional on the current information set.  A probability value by itself is
never multiplied into alpha and never activates the overlay.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path

from personal_alpha_terminal.quant_engine.alpha import AlphaSignal


class ProbabilityOverlayState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VALIDATING = "VALIDATING"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class ProbabilityOverlayIdentity:
    strategy_version: str
    strategy_parameter_hash: str
    research_data_version: str
    research_data_hash: str
    universe_version: str
    probability_model_version: str
    calibration_version: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in asdict(self).values()):
            raise ValueError("probability overlay identity is incomplete")


@dataclass(frozen=True, slots=True)
class OverlayPerformanceMetrics:
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float
    hit_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    benchmark_alpha: float
    information_ratio: float
    transaction_cost: float


@dataclass(frozen=True, slots=True)
class ProbabilityOverlayArtifact:
    artifact_id: str
    identity: ProbabilityOverlayIdentity
    state: ProbabilityOverlayState
    mechanism: str
    shrinkage_coefficient: float
    maximum_absolute_adjustment: float
    minimum_condition_sample: int
    condition_whitelist: tuple[str, ...]
    multiple_testing_method: str
    train_start: date | None
    train_end: date | None
    validation_start: date | None
    validation_end: date | None
    oos_start: date | None
    oos_end: date | None
    embargo_sessions: int
    walk_forward_folds: int
    locked_oos_sessions: int
    brier_score: float | None
    baseline_brier_score: float | None
    log_loss: float | None
    expected_calibration_error: float | None
    calibration_slope: float | None
    calibration_intercept: float | None
    base_metrics: OverlayPerformanceMetrics | None
    overlay_metrics: OverlayPerformanceMetrics | None
    costs_included: bool
    benchmark: str
    locked_oos: bool
    residual_return_net_of_costs: bool
    created_at: datetime
    available_at: datetime
    blockers: tuple[str, ...]
    artifact_hash: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("probability overlay timestamps must be timezone-aware")
        if not 0 <= self.shrinkage_coefficient <= 1:
            raise ValueError("overlay shrinkage coefficient must be in [0, 1]")
        if self.maximum_absolute_adjustment <= 0 or self.minimum_condition_sample < 30:
            raise ValueError("overlay adjustment/sample safeguards are invalid")
        if self.embargo_sessions < 0 or self.walk_forward_folds < 0:
            raise ValueError("overlay temporal safeguards are invalid")
        if not self.artifact_id or not self.mechanism or not self.benchmark:
            raise ValueError("probability overlay lineage is incomplete")

    @property
    def production_approved(self) -> bool:
        return self.state is ProbabilityOverlayState.PRODUCTION_APPROVED

    def material(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("artifact_hash")
        return payload

    def verify_hash(self) -> bool:
        return _fingerprint(self.material()) == self.artifact_hash

    def document(self) -> dict[str, object]:
        rendered = json.dumps(asdict(self), default=str, sort_keys=True)
        payload: dict[str, object] = json.loads(rendered)
        return payload


@dataclass(frozen=True, slots=True)
class ConditionalProbabilityEvidence:
    symbol: str
    condition_id: str
    as_of: datetime
    available_at: datetime
    sample_size: int
    wins: int
    losses: int
    raw_probability: float
    prior_probability: float
    posterior_probability: float
    credible_interval: tuple[float, float]
    expected_residual_return: float
    calibration_state: str
    model_version: str
    data_version: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("probability evidence timestamps must be timezone-aware")
        if self.sample_size != self.wins + self.losses:
            raise ValueError("probability wins/losses must equal sample_size")
        probabilities = (
            self.raw_probability,
            self.prior_probability,
            self.posterior_probability,
            *self.credible_interval,
        )
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("probability evidence values must be in [0, 1]")
        if not isfinite(self.expected_residual_return):
            raise ValueError("probability residual return must be finite")

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "condition_id": self.condition_id,
            "as_of": self.as_of.isoformat(),
            "available_at": self.available_at.isoformat(),
            "sample_size": self.sample_size,
            "wins": self.wins,
            "losses": self.losses,
            "raw_probability": self.raw_probability,
            "prior_probability": self.prior_probability,
            "posterior_probability": self.posterior_probability,
            "credible_interval": list(self.credible_interval),
            "expected_residual_return": self.expected_residual_return,
            "calibration_state": self.calibration_state,
            "model_version": self.model_version,
            "data_version": self.data_version,
        }


@dataclass(frozen=True, slots=True)
class ProbabilityOverlayEffect:
    symbol: str
    condition_id: str
    base_expected_excess_return: float
    probability_adjustment: float
    adjusted_expected_excess_return: float
    posterior_probability: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class ProbabilityOverlayApplication:
    signals: tuple[AlphaSignal, ...]
    active: bool
    state: ProbabilityOverlayState
    reason: str
    artifact_id: str
    effects: tuple[ProbabilityOverlayEffect, ...] = ()


@dataclass(frozen=True, slots=True)
class OverlayApprovalPolicy:
    minimum_locked_oos_sessions: int = 252
    minimum_walk_forward_folds: int = 4
    maximum_ece: float = 0.05
    minimum_calibration_slope: float = 0.8
    maximum_calibration_slope: float = 1.2
    maximum_absolute_calibration_intercept: float = 0.10
    minimum_net_sharpe_improvement: float = 0.0
    minimum_net_alpha_improvement: float = 0.0
    maximum_drawdown_deterioration: float = 0.02


def build_probability_overlay_artifact(
    *,
    artifact_id: str,
    identity: ProbabilityOverlayIdentity,
    requested_state: ProbabilityOverlayState,
    mechanism: str,
    shrinkage_coefficient: float,
    maximum_absolute_adjustment: float,
    minimum_condition_sample: int,
    condition_whitelist: tuple[str, ...],
    multiple_testing_method: str,
    train_start: date | None,
    train_end: date | None,
    validation_start: date | None,
    validation_end: date | None,
    oos_start: date | None,
    oos_end: date | None,
    embargo_sessions: int,
    walk_forward_folds: int,
    locked_oos_sessions: int,
    brier_score: float | None,
    baseline_brier_score: float | None,
    log_loss: float | None,
    expected_calibration_error: float | None,
    calibration_slope: float | None,
    calibration_intercept: float | None,
    base_metrics: OverlayPerformanceMetrics | None,
    overlay_metrics: OverlayPerformanceMetrics | None,
    costs_included: bool,
    benchmark: str,
    locked_oos: bool,
    residual_return_net_of_costs: bool,
    created_at: datetime,
    available_at: datetime,
    upstream_research_certified: bool,
    upstream_blockers: tuple[str, ...] = (),
    policy: OverlayApprovalPolicy | None = None,
) -> ProbabilityOverlayArtifact:
    """Evaluate the formal approval gates and return a content-addressed artifact."""

    configured = policy or OverlayApprovalPolicy()
    blockers = list(upstream_blockers)
    if not upstream_research_certified:
        blockers.append("RESEARCH_DATA_NOT_CERTIFIED")
    if (
        train_start is None
        or train_end is None
        or validation_start is None
        or validation_end is None
        or oos_start is None
        or oos_end is None
    ):
        blockers.append("TEMPORAL_SPLIT_INCOMPLETE")
    elif not (
        train_start <= train_end < validation_start <= validation_end < oos_start <= oos_end
    ):
        blockers.append("TRAIN_VALIDATION_OOS_NOT_DISJOINT")
    if not locked_oos or locked_oos_sessions < configured.minimum_locked_oos_sessions:
        blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
    if walk_forward_folds < configured.minimum_walk_forward_folds:
        blockers.append("WALK_FORWARD_FOLDS_INSUFFICIENT")
    if not costs_included or not residual_return_net_of_costs:
        blockers.append("AFTER_COST_EVIDENCE_MISSING")
    if not condition_whitelist:
        blockers.append("CONDITION_WHITELIST_EMPTY")
    if multiple_testing_method.strip().upper() in {"", "NONE", "NOT_APPLIED"}:
        blockers.append("MULTIPLE_TESTING_CONTROL_MISSING")
    if None in (
        brier_score,
        baseline_brier_score,
        log_loss,
        expected_calibration_error,
        calibration_slope,
        calibration_intercept,
    ):
        blockers.append("CALIBRATION_METRICS_INCOMPLETE")
    else:
        assert brier_score is not None
        assert baseline_brier_score is not None
        assert expected_calibration_error is not None
        assert calibration_slope is not None
        assert calibration_intercept is not None
        if brier_score >= baseline_brier_score:
            blockers.append("BRIER_NOT_BETTER_THAN_BASE_RATE")
        if expected_calibration_error > configured.maximum_ece:
            blockers.append("ECE_EXCESSIVE")
        if not (
            configured.minimum_calibration_slope
            <= calibration_slope
            <= configured.maximum_calibration_slope
        ):
            blockers.append("CALIBRATION_SLOPE_OUT_OF_RANGE")
        if abs(calibration_intercept) > configured.maximum_absolute_calibration_intercept:
            blockers.append("CALIBRATION_INTERCEPT_OUT_OF_RANGE")
    if base_metrics is None or overlay_metrics is None:
        blockers.append("BASE_OVERLAY_OOS_COMPARISON_MISSING")
    else:
        if (
            overlay_metrics.sharpe - base_metrics.sharpe
            <= configured.minimum_net_sharpe_improvement
        ):
            blockers.append("NET_OOS_SHARPE_NOT_IMPROVED")
        if (
            overlay_metrics.benchmark_alpha - base_metrics.benchmark_alpha
            <= configured.minimum_net_alpha_improvement
        ):
            blockers.append("NET_OOS_BENCHMARK_ALPHA_NOT_IMPROVED")
        if overlay_metrics.max_drawdown > (
            base_metrics.max_drawdown + configured.maximum_drawdown_deterioration
        ):
            blockers.append("MAX_DRAWDOWN_DETERIORATED")
    state = requested_state
    if requested_state is ProbabilityOverlayState.PRODUCTION_APPROVED and blockers:
        state = (
            ProbabilityOverlayState.RESEARCH_ONLY
            if not upstream_research_certified
            else ProbabilityOverlayState.REJECTED
        )
    material: dict[str, object] = {
        "artifact_id": artifact_id,
        "identity": asdict(identity),
        "state": state,
        "mechanism": mechanism,
        "shrinkage_coefficient": shrinkage_coefficient,
        "maximum_absolute_adjustment": maximum_absolute_adjustment,
        "minimum_condition_sample": minimum_condition_sample,
        "condition_whitelist": condition_whitelist,
        "multiple_testing_method": multiple_testing_method,
        "train_start": train_start,
        "train_end": train_end,
        "validation_start": validation_start,
        "validation_end": validation_end,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "embargo_sessions": embargo_sessions,
        "walk_forward_folds": walk_forward_folds,
        "locked_oos_sessions": locked_oos_sessions,
        "brier_score": brier_score,
        "baseline_brier_score": baseline_brier_score,
        "log_loss": log_loss,
        "expected_calibration_error": expected_calibration_error,
        "calibration_slope": calibration_slope,
        "calibration_intercept": calibration_intercept,
        "base_metrics": asdict(base_metrics) if base_metrics else None,
        "overlay_metrics": asdict(overlay_metrics) if overlay_metrics else None,
        "costs_included": costs_included,
        "benchmark": benchmark,
        "locked_oos": locked_oos,
        "residual_return_net_of_costs": residual_return_net_of_costs,
        "created_at": created_at,
        "available_at": available_at,
        "blockers": tuple(dict.fromkeys(blockers)),
    }
    return ProbabilityOverlayArtifact(
        artifact_id=artifact_id,
        identity=identity,
        state=state,
        mechanism=mechanism,
        shrinkage_coefficient=shrinkage_coefficient,
        maximum_absolute_adjustment=maximum_absolute_adjustment,
        minimum_condition_sample=minimum_condition_sample,
        condition_whitelist=condition_whitelist,
        multiple_testing_method=multiple_testing_method,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        oos_start=oos_start,
        oos_end=oos_end,
        embargo_sessions=embargo_sessions,
        walk_forward_folds=walk_forward_folds,
        locked_oos_sessions=locked_oos_sessions,
        brier_score=brier_score,
        baseline_brier_score=baseline_brier_score,
        log_loss=log_loss,
        expected_calibration_error=expected_calibration_error,
        calibration_slope=calibration_slope,
        calibration_intercept=calibration_intercept,
        base_metrics=base_metrics,
        overlay_metrics=overlay_metrics,
        costs_included=costs_included,
        benchmark=benchmark,
        locked_oos=locked_oos,
        residual_return_net_of_costs=residual_return_net_of_costs,
        created_at=created_at,
        available_at=available_at,
        blockers=tuple(dict.fromkeys(blockers)),
        artifact_hash=_fingerprint(material),
    )


def apply_probability_overlay(
    signals: tuple[AlphaSignal, ...],
    evidence: tuple[ConditionalProbabilityEvidence, ...],
    *,
    artifact: ProbabilityOverlayArtifact | None,
    expected_identity: ProbabilityOverlayIdentity,
    decision_time: datetime,
) -> ProbabilityOverlayApplication:
    """Apply only an exact, intact and OOS-approved additive residual overlay."""

    if decision_time.tzinfo is None:
        raise ValueError("overlay decision_time must be timezone-aware")
    if artifact is None:
        return _fallback(signals, "PROBABILITY_FALLBACK_CLASSICAL")
    if not artifact.verify_hash():
        return _fallback(signals, "PROBABILITY_ARTIFACT_HASH_MISMATCH", artifact=artifact)
    if artifact.identity != expected_identity:
        return _fallback(signals, "PROBABILITY_ARTIFACT_IDENTITY_MISMATCH", artifact=artifact)
    if artifact.available_at > decision_time:
        return _fallback(signals, "PROBABILITY_ARTIFACT_NOT_YET_AVAILABLE", artifact=artifact)
    if not artifact.production_approved:
        return _fallback(
            signals,
            "PROBABILITY_OVERLAY_NOT_PRODUCTION_APPROVED",
            artifact=artifact,
        )
    if artifact.blockers:
        return _fallback(signals, "PROBABILITY_ARTIFACT_HAS_BLOCKERS", artifact=artifact)
    by_symbol = {item.symbol: item for item in evidence}
    effects: list[ProbabilityOverlayEffect] = []
    adjusted: list[AlphaSignal] = []
    for signal in signals:
        item = by_symbol.get(signal.symbol)
        if item is None:
            return _fallback(signals, "PROBABILITY_EVIDENCE_INCOMPLETE", artifact=artifact)
        if item.available_at > decision_time or item.as_of > decision_time:
            return _fallback(signals, "FUTURE_PROBABILITY_EVIDENCE_NOT_ALLOWED", artifact=artifact)
        if item.condition_id not in artifact.condition_whitelist:
            return _fallback(signals, "PROBABILITY_CONDITION_NOT_APPROVED", artifact=artifact)
        if item.sample_size < artifact.minimum_condition_sample:
            return _fallback(signals, "PROBABILITY_SAMPLE_INSUFFICIENT", artifact=artifact)
        if item.calibration_state != "CALIBRATED_LOCKED_OOS":
            return _fallback(signals, "PROBABILITY_EVIDENCE_NOT_CALIBRATED_OOS", artifact=artifact)
        if item.model_version != artifact.identity.probability_model_version:
            return _fallback(signals, "PROBABILITY_MODEL_VERSION_MISMATCH", artifact=artifact)
        if item.data_version != artifact.identity.research_data_version:
            return _fallback(signals, "PROBABILITY_DATA_VERSION_MISMATCH", artifact=artifact)
        raw_adjustment = artifact.shrinkage_coefficient * item.expected_residual_return
        adjustment = max(
            -artifact.maximum_absolute_adjustment,
            min(artifact.maximum_absolute_adjustment, raw_adjustment),
        )
        expected = signal.expected_excess_return + adjustment
        effects.append(
            ProbabilityOverlayEffect(
                signal.symbol,
                item.condition_id,
                signal.expected_excess_return,
                adjustment,
                expected,
                item.posterior_probability,
                item.sample_size,
            )
        )
        adjusted.append(
            replace(
                signal,
                expected_excess_return=expected,
                confidence=item.posterior_probability,
                confidence_calibrated=True,
                calibration_id=artifact.artifact_id,
                model_version=(
                    f"{signal.model_version}+probability:{artifact.identity.probability_model_version}"
                ),
            )
        )
    return ProbabilityOverlayApplication(
        signals=tuple(adjusted),
        active=True,
        state=artifact.state,
        reason="APPROVED_NET_RESIDUAL_OVERLAY_APPLIED",
        artifact_id=artifact.artifact_id,
        effects=tuple(effects),
    )


class ProbabilityOverlayRegistry:
    """Read immutable overlay artifacts; malformed or mismatched files fail closed."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def matching(self, identity: ProbabilityOverlayIdentity) -> ProbabilityOverlayArtifact | None:
        directory = self.root / "probability_overlay"
        for path in sorted(directory.glob("*.json")) if directory.exists() else ():
            artifact = _load_artifact(path)
            if artifact.production_approved and artifact.identity == identity:
                return artifact
        return None

    def matching_inputs(
        self,
        *,
        strategy_version: str,
        strategy_parameter_hash: str,
        research_data_version: str,
        research_data_hash: str,
        universe_version: str,
        decision_time: datetime,
    ) -> ProbabilityOverlayArtifact | None:
        """Return one exact available approval; ambiguity fails closed."""

        directory = self.root / "probability_overlay"
        matches: list[ProbabilityOverlayArtifact] = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else ():
            artifact = _load_artifact(path)
            identity = artifact.identity
            if (
                artifact.production_approved
                and artifact.available_at <= decision_time
                and identity.strategy_version == strategy_version
                and identity.strategy_parameter_hash == strategy_parameter_hash
                and identity.research_data_version == research_data_version
                and identity.research_data_hash == research_data_hash
                and identity.universe_version == universe_version
            ):
                matches.append(artifact)
        return matches[0] if len(matches) == 1 else None

    def assessed_inputs(
        self,
        *,
        strategy_version: str,
        strategy_parameter_hash: str,
        research_data_version: str,
        research_data_hash: str,
        universe_version: str,
        decision_time: datetime,
    ) -> ProbabilityOverlayArtifact | None:
        """Return one exact artifact even when its honest verdict is fallback."""

        directory = self.root / "probability_overlay"
        matches: list[ProbabilityOverlayArtifact] = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else ():
            artifact = _load_artifact(path)
            identity = artifact.identity
            if (
                artifact.available_at <= decision_time
                and identity.strategy_version == strategy_version
                and identity.strategy_parameter_hash == strategy_parameter_hash
                and identity.research_data_version == research_data_version
                and identity.research_data_hash == research_data_hash
                and identity.universe_version == universe_version
            ):
                matches.append(artifact)
        return matches[0] if len(matches) == 1 else None

    def evidence(
        self,
        artifact: ProbabilityOverlayArtifact,
        *,
        decision_time: datetime,
    ) -> tuple[ConditionalProbabilityEvidence, ...]:
        path = self.root / "probability_overlay" / "evidence" / f"{artifact.artifact_id}.json"
        if not path.exists():
            return ()
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValueError("probability evidence rows are malformed")
        if payload.get("artifact_id") != artifact.artifact_id:
            raise ValueError("probability evidence artifact binding mismatch")
        expected_hash = _fingerprint(rows)
        if payload.get("content_hash") != expected_hash:
            raise ValueError("probability evidence content hash mismatch")
        loaded = tuple(_load_evidence_row(item) for item in rows)
        if any(item.available_at > decision_time or item.as_of > decision_time for item in loaded):
            raise ValueError("future probability evidence is not available at decision time")
        return loaded


def write_probability_overlay_artifact(
    artifact: ProbabilityOverlayArtifact,
    root: Path,
) -> Path:
    directory = root / "probability_overlay"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{artifact.artifact_id}.json"
    rendered = json.dumps(artifact.document(), indent=2, sort_keys=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError("refusing to overwrite immutable probability overlay artifact")
        return path
    path.write_text(rendered, encoding="utf-8")
    return path


def write_probability_evidence(
    artifact: ProbabilityOverlayArtifact,
    evidence: tuple[ConditionalProbabilityEvidence, ...],
    root: Path,
) -> Path:
    """Persist an immutable evidence batch bound to one approved overlay artifact."""

    rows = [item.document() for item in sorted(evidence, key=lambda item: item.symbol)]
    document = {
        "artifact_id": artifact.artifact_id,
        "content_hash": _fingerprint(rows),
        "rows": rows,
    }
    directory = root / "probability_overlay" / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{artifact.artifact_id}.json"
    rendered = json.dumps(document, indent=2, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise ValueError("refusing to overwrite immutable probability evidence")
    path.write_text(rendered, encoding="utf-8")
    return path


def _fallback(
    signals: tuple[AlphaSignal, ...],
    reason: str,
    *,
    artifact: ProbabilityOverlayArtifact | None = None,
) -> ProbabilityOverlayApplication:
    return ProbabilityOverlayApplication(
        signals=signals,
        active=False,
        state=(artifact.state if artifact else ProbabilityOverlayState.RESEARCH_ONLY),
        reason=reason,
        artifact_id=(artifact.artifact_id if artifact else "OPTIONAL_UNAVAILABLE"),
    )


def _load_artifact(path: Path) -> ProbabilityOverlayArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    identity = ProbabilityOverlayIdentity(**payload.pop("identity"))
    for key in (
        "train_start",
        "train_end",
        "validation_start",
        "validation_end",
        "oos_start",
        "oos_end",
    ):
        payload[key] = date.fromisoformat(payload[key]) if payload[key] else None
    for key in ("created_at", "available_at"):
        payload[key] = datetime.fromisoformat(payload[key])
    payload["state"] = ProbabilityOverlayState(payload["state"])
    payload["condition_whitelist"] = tuple(payload["condition_whitelist"])
    payload["blockers"] = tuple(payload["blockers"])
    for key in ("base_metrics", "overlay_metrics"):
        payload[key] = OverlayPerformanceMetrics(**payload[key]) if payload[key] else None
    artifact = ProbabilityOverlayArtifact(identity=identity, **payload)
    if not artifact.verify_hash():
        raise ValueError(f"probability overlay artifact hash mismatch: {path}")
    return artifact


def _load_evidence_row(payload: object) -> ConditionalProbabilityEvidence:
    if not isinstance(payload, dict):
        raise ValueError("probability evidence row is malformed")
    values = dict(payload)
    values["as_of"] = datetime.fromisoformat(str(values["as_of"]))
    values["available_at"] = datetime.fromisoformat(str(values["available_at"]))
    interval = values["credible_interval"]
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError("probability credible interval is malformed")
    values["credible_interval"] = (float(interval[0]), float(interval[1]))
    return ConditionalProbabilityEvidence(**values)


def _fingerprint(payload: object) -> str:
    rendered = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode()).hexdigest()
