from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from personal_alpha_terminal.core.fingerprints import fingerprint


class ApprovalState(StrEnum):
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class PortfolioValidationIdentity:
    alpha_model_version: str
    alpha_data_version: str
    strategy_parameter_hash: str
    portfolio_constraint_hash: str
    risk_model_hash: str
    cost_model_hash: str
    runtime_config_hash: str
    benchmark_definition: str


@dataclass(frozen=True, slots=True)
class PortfolioValidationArtifact:
    validation_id: str
    locked_oos_evidence_id: str
    identity: PortfolioValidationIdentity
    validation_start: date
    validation_end: date
    embargo_sessions: int
    walk_forward_configuration: str
    source_git_commit: str
    created_at: datetime
    approval_state: ApprovalState
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationIdentity:
    alpha_model_version: str
    alpha_data_version: str
    strategy_parameter_hash: str


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationArtifact:
    calibration_id: str
    identity: ProbabilityCalibrationIdentity
    method: str
    calibration_version: str
    train_start: date
    train_end: date
    calibration_start: date
    calibration_end: date
    oos_start: date
    oos_end: date
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    sample_count: int
    reliability_bins: tuple[tuple[float, float, int], ...]
    locked_oos: bool
    created_at: datetime
    approval_state: ApprovalState
    artifact_hash: str


class ValidationArtifactRegistry:
    """Immutable file registry. An ID is returned only after exact fingerprint match."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def produce_portfolio_approval(
        self,
        *,
        validation_id: str,
        locked_oos_evidence_id: str,
        identity: PortfolioValidationIdentity,
        validation_start: date,
        validation_end: date,
        embargo_sessions: int,
        walk_forward_configuration: str,
        source_git_commit: str,
        created_at: datetime,
    ) -> PortfolioValidationArtifact:
        if created_at.tzinfo is None:
            raise ValueError("validation created_at must be timezone-aware")
        if validation_start > validation_end or embargo_sessions < 0:
            raise ValueError("validation period/embargo is invalid")
        required = (
            validation_id,
            locked_oos_evidence_id,
            source_git_commit,
            walk_forward_configuration,
            *asdict(identity).values(),
        )
        if any(not str(item).strip() for item in required):
            raise ValueError("portfolio validation lineage is incomplete")
        payload = {
            "validation_id": validation_id,
            "locked_oos_evidence_id": locked_oos_evidence_id,
            "identity": asdict(identity),
            "validation_start": validation_start,
            "validation_end": validation_end,
            "embargo_sessions": embargo_sessions,
            "walk_forward_configuration": walk_forward_configuration,
            "source_git_commit": source_git_commit,
            "created_at": created_at,
            "approval_state": ApprovalState.APPROVED,
        }
        artifact = PortfolioValidationArtifact(
            validation_id=validation_id,
            locked_oos_evidence_id=locked_oos_evidence_id,
            identity=identity,
            validation_start=validation_start,
            validation_end=validation_end,
            embargo_sessions=embargo_sessions,
            walk_forward_configuration=walk_forward_configuration,
            source_git_commit=source_git_commit,
            created_at=created_at,
            approval_state=ApprovalState.APPROVED,
            artifact_hash=fingerprint(_serialized_payload(payload)),
        )
        self._write("portfolio", validation_id, artifact)
        return artifact

    def matching_portfolio_approval(
        self, identity: PortfolioValidationIdentity
    ) -> PortfolioValidationArtifact | None:
        for path in self._paths("portfolio"):
            artifact = self._load_portfolio(path)
            if artifact.approval_state is ApprovalState.APPROVED and artifact.identity == identity:
                return artifact
        return None

    def produce_probability_calibration(
        self,
        *,
        calibration_id: str,
        identity: ProbabilityCalibrationIdentity,
        method: str,
        calibration_version: str,
        train_start: date,
        train_end: date,
        calibration_start: date,
        calibration_end: date,
        oos_start: date,
        oos_end: date,
        brier_score: float,
        log_loss: float,
        expected_calibration_error: float,
        sample_count: int,
        reliability_bins: tuple[tuple[float, float, int], ...],
        created_at: datetime,
    ) -> ProbabilityCalibrationArtifact:
        if created_at.tzinfo is None or sample_count < 1:
            raise ValueError("calibration timestamp/sample count is invalid")
        if not (
            train_start
            <= train_end
            < calibration_start
            <= calibration_end
            < oos_start
            <= oos_end
        ):
            raise ValueError("calibration windows must be chronological and disjoint")
        if any(value < 0 for value in (brier_score, log_loss, expected_calibration_error)):
            raise ValueError("calibration metrics must be non-negative")
        payload = {
            "calibration_id": calibration_id,
            "identity": asdict(identity),
            "method": method,
            "calibration_version": calibration_version,
            "train_start": train_start,
            "train_end": train_end,
            "calibration_start": calibration_start,
            "calibration_end": calibration_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
            "brier_score": brier_score,
            "log_loss": log_loss,
            "expected_calibration_error": expected_calibration_error,
            "sample_count": sample_count,
            "reliability_bins": reliability_bins,
            "locked_oos": True,
            "created_at": created_at,
            "approval_state": ApprovalState.APPROVED,
        }
        artifact = ProbabilityCalibrationArtifact(
            calibration_id=calibration_id,
            identity=identity,
            method=method,
            calibration_version=calibration_version,
            train_start=train_start,
            train_end=train_end,
            calibration_start=calibration_start,
            calibration_end=calibration_end,
            oos_start=oos_start,
            oos_end=oos_end,
            brier_score=brier_score,
            log_loss=log_loss,
            expected_calibration_error=expected_calibration_error,
            sample_count=sample_count,
            reliability_bins=reliability_bins,
            locked_oos=True,
            created_at=created_at,
            approval_state=ApprovalState.APPROVED,
            artifact_hash=fingerprint(_serialized_payload(payload)),
        )
        self._write("probability", calibration_id, artifact)
        return artifact

    def matching_probability_calibration(
        self, identity: ProbabilityCalibrationIdentity
    ) -> ProbabilityCalibrationArtifact | None:
        for path in self._paths("probability"):
            artifact = self._load_probability(path)
            if (
                artifact.approval_state is ApprovalState.APPROVED
                and artifact.locked_oos
                and artifact.identity == identity
            ):
                return artifact
        return None

    def _paths(self, kind: str) -> tuple[Path, ...]:
        directory = self.root / kind
        return tuple(sorted(directory.glob("*.json"))) if directory.exists() else ()

    def _write(
        self,
        kind: str,
        identity: str,
        artifact: PortfolioValidationArtifact | ProbabilityCalibrationArtifact,
    ) -> None:
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{identity}.json"
        if path.exists():
            raise ValueError(f"immutable validation artifact already exists: {identity}")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(artifact), default=str, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _load_portfolio(path: Path) -> PortfolioValidationArtifact:
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = PortfolioValidationIdentity(**payload.pop("identity"))
        expected = payload.pop("artifact_hash")
        material = {**payload, "identity": asdict(identity)}
        if fingerprint(material) != expected:
            raise ValueError(f"portfolio validation artifact hash mismatch: {path}")
        payload["validation_start"] = date.fromisoformat(payload["validation_start"])
        payload["validation_end"] = date.fromisoformat(payload["validation_end"])
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["approval_state"] = ApprovalState(payload["approval_state"])
        return PortfolioValidationArtifact(
            **payload,
            identity=identity,
            artifact_hash=expected,
        )

    @staticmethod
    def _load_probability(path: Path) -> ProbabilityCalibrationArtifact:
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = ProbabilityCalibrationIdentity(**payload.pop("identity"))
        expected = payload.pop("artifact_hash")
        material = {**payload, "identity": asdict(identity)}
        if fingerprint(material) != expected:
            raise ValueError(f"probability calibration artifact hash mismatch: {path}")
        for key in (
            "train_start", "train_end", "calibration_start", "calibration_end",
            "oos_start", "oos_end",
        ):
            payload[key] = date.fromisoformat(payload[key])
        payload["reliability_bins"] = tuple(tuple(item) for item in payload["reliability_bins"])
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["approval_state"] = ApprovalState(payload["approval_state"])
        return ProbabilityCalibrationArtifact(
            **payload,
            identity=identity,
            artifact_hash=expected,
        )


def _serialized_payload(payload: object) -> object:
    return json.loads(json.dumps(payload, default=str, sort_keys=True))
