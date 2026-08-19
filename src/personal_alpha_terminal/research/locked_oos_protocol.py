"""ROUND75 frozen research protocol and fail-closed locked-OOS lifecycle."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.research.data_evidence import EvidenceStatus


class LockedOOSSealState(StrEnum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    EVALUATED = "EVALUATED"


class LockedOOSOpeningState(StrEnum):
    OPENED = "OPENED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class LockedOOSProtocolManifest:
    """All identity and economic assumptions that define a frozen evaluation."""

    protocol_version: str
    dataset_id: str
    dataset_hash: str
    dataset_vintage: str
    feature_schema_hash: str
    model_id: str
    model_version: str
    model_hash: str
    config_hash: str
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    locked_oos_start: date
    locked_oos_end: date
    purge_sessions: int
    embargo_sessions: int
    label_horizon_sessions: int
    universe_semantics: str
    benchmark_id: str
    benchmark_semantics: str
    transaction_costs_bps: float
    slippage_bps: float
    execution_price_policy: str
    calendar_semantics: str
    corporate_action_semantics: str
    created_at: datetime
    seal_state: LockedOOSSealState = LockedOOSSealState.DRAFT
    sealed_at: datetime | None = None
    evaluation_count: int = 0
    evaluation_id: str | None = None
    opening_audit_hash: str | None = None
    evaluation_result_hash: str | None = None
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        _require_aware(self.created_at, "created_at")
        if self.sealed_at is not None:
            _require_aware(self.sealed_at, "sealed_at")
        for field_name in (
            "protocol_version",
            "dataset_id",
            "dataset_hash",
            "dataset_vintage",
            "feature_schema_hash",
            "model_id",
            "model_version",
            "model_hash",
            "config_hash",
            "universe_semantics",
            "benchmark_id",
            "benchmark_semantics",
            "execution_price_policy",
            "calendar_semantics",
            "corporate_action_semantics",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.train_start > self.train_end:
            raise ValueError("TRAIN interval is reversed")
        if self.validation_start > self.validation_end:
            raise ValueError("VALIDATION interval is reversed")
        if self.locked_oos_start > self.locked_oos_end:
            raise ValueError("LOCKED_OOS interval is reversed")
        if self.train_end >= self.validation_start or self.validation_end >= self.locked_oos_start:
            raise ValueError("research partitions overlap or are not chronological")
        if self.purge_sessions < 0 or self.embargo_sessions < 0 or self.label_horizon_sessions < 0:
            raise ValueError("purge, embargo and label horizon must be non-negative")
        if self.purge_sessions < self.label_horizon_sessions:
            raise ValueError("purge_sessions must cover label_horizon_sessions")
        if self.transaction_costs_bps < 0 or self.slippage_bps < 0:
            raise ValueError("cost and slippage assumptions must be non-negative")
        if self.evaluation_count not in {0, 1}:
            raise ValueError("locked OOS evaluation count must be zero or one")
        if self.seal_state is LockedOOSSealState.DRAFT:
            if self.sealed_at is not None or self.evaluation_count != 0:
                raise ValueError("DRAFT protocol cannot contain seal/evaluation state")
        else:
            if self.sealed_at is None:
                raise ValueError("SEALED/EVALUATED protocol requires sealed_at")
        if self.seal_state is LockedOOSSealState.EVALUATED:
            if self.evaluation_count != 1 or not self.evaluation_id or not self.evaluation_result_hash:
                raise ValueError("EVALUATED protocol requires exactly one result identity")
        if self.manifest_hash and self.manifest_hash != _manifest_hash(self):
            raise ValueError("locked OOS protocol manifest hash is invalid")

    def document(self) -> dict[str, object]:
        document = asdict(self)
        for field_name in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "locked_oos_start",
            "locked_oos_end",
        ):
            document[field_name] = getattr(self, field_name).isoformat()
        document["created_at"] = self.created_at.astimezone(UTC).isoformat()
        document["sealed_at"] = self.sealed_at.astimezone(UTC).isoformat() if self.sealed_at else None
        document["seal_state"] = self.seal_state.value
        return document


@dataclass(frozen=True, slots=True)
class LockedOOSOpeningAudit:
    evaluation_id: str
    attempted_at: datetime
    manifest_hash: str
    state: LockedOOSOpeningState
    replay_identity: str
    blockers: tuple[str, ...]
    audit_hash: str

    def document(self) -> dict[str, object]:
        return {
            **asdict(self),
            "attempted_at": self.attempted_at.astimezone(UTC).isoformat(),
            "state": self.state.value,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class LockedOOSProtocolStatus:
    status: EvidenceStatus
    manifest_hash: str | None
    seal_state: LockedOOSSealState | None
    blockers: tuple[str, ...]
    promotion_allowed: bool

    def document(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "manifest_hash": self.manifest_hash,
            "seal_state": self.seal_state.value if self.seal_state else None,
            "blockers": list(self.blockers),
            "promotion_allowed": self.promotion_allowed,
        }


def create_locked_oos_protocol(
    *,
    dataset_id: str,
    dataset_hash: str,
    dataset_vintage: str,
    feature_schema_hash: str,
    model_id: str,
    model_version: str,
    model_hash: str,
    config_hash: str,
    train_start: date,
    train_end: date,
    validation_start: date,
    validation_end: date,
    locked_oos_start: date,
    locked_oos_end: date,
    purge_sessions: int,
    embargo_sessions: int,
    label_horizon_sessions: int,
    universe_semantics: str,
    benchmark_id: str,
    benchmark_semantics: str,
    transaction_costs_bps: float,
    slippage_bps: float,
    execution_price_policy: str,
    calendar_semantics: str,
    corporate_action_semantics: str,
    created_at: datetime | None = None,
) -> LockedOOSProtocolManifest:
    base = LockedOOSProtocolManifest(
        protocol_version="ROUND75-LOCKED-OOS-PROTOCOL-v1",
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        dataset_vintage=dataset_vintage,
        feature_schema_hash=feature_schema_hash,
        model_id=model_id,
        model_version=model_version,
        model_hash=model_hash,
        config_hash=config_hash,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        locked_oos_start=locked_oos_start,
        locked_oos_end=locked_oos_end,
        purge_sessions=purge_sessions,
        embargo_sessions=embargo_sessions,
        label_horizon_sessions=label_horizon_sessions,
        universe_semantics=universe_semantics,
        benchmark_id=benchmark_id,
        benchmark_semantics=benchmark_semantics,
        transaction_costs_bps=transaction_costs_bps,
        slippage_bps=slippage_bps,
        execution_price_policy=execution_price_policy,
        calendar_semantics=calendar_semantics,
        corporate_action_semantics=corporate_action_semantics,
        created_at=(created_at or datetime.now(UTC)).astimezone(UTC),
    )
    return replace(base, manifest_hash=_manifest_hash(base))


def validate_protocol_manifest(manifest: LockedOOSProtocolManifest) -> tuple[str, ...]:
    blockers: list[str] = []
    try:
        _ = LockedOOSProtocolManifest(**asdict(manifest))
    except ValueError as exc:
        blockers.append(str(exc))
    if manifest.manifest_hash != _manifest_hash(manifest):
        blockers.append("LOCKED_OOS_MANIFEST_HASH_MISMATCH")
    if manifest.seal_state is LockedOOSSealState.DRAFT:
        blockers.append("LOCKED_OOS_UNSEALED")
    if manifest.seal_state is LockedOOSSealState.SEALED and manifest.evaluation_count != 0:
        blockers.append("LOCKED_OOS_SEAL_STATE_EVALUATION_MISMATCH")
    if manifest.seal_state is LockedOOSSealState.EVALUATED and manifest.evaluation_count != 1:
        blockers.append("LOCKED_OOS_EVALUATION_COUNT_NOT_ONE")
    return tuple(dict.fromkeys(blockers))


def seal_locked_oos_protocol(
    manifest: LockedOOSProtocolManifest,
    *,
    data_certification_status: EvidenceStatus | str,
    sealed_at: datetime | None = None,
) -> LockedOOSProtocolManifest:
    if manifest.seal_state is not LockedOOSSealState.DRAFT:
        raise ValueError("locked OOS protocol can be sealed only once")
    if EvidenceStatus(str(data_certification_status)) is not EvidenceStatus.PASS:
        raise ValueError("LOCKED_OOS_REQUIRES_CERTIFIED_DATA")
    blockers = validate_protocol_manifest(manifest)
    if blockers != ("LOCKED_OOS_UNSEALED",):
        raise ValueError("cannot seal invalid locked OOS protocol: " + ";".join(blockers))
    sealed_time = (sealed_at or datetime.now(UTC)).astimezone(UTC)
    sealed = replace(
        manifest,
        seal_state=LockedOOSSealState.SEALED,
        sealed_at=sealed_time,
        manifest_hash="",
    )
    return replace(sealed, manifest_hash=_manifest_hash(sealed))


def replay_identity(manifest: LockedOOSProtocolManifest) -> str:
    """Fingerprint every input assumption that must remain unchanged at replay."""

    return fingerprint(
        {
            "dataset_hash": manifest.dataset_hash,
            "dataset_vintage": manifest.dataset_vintage,
            "feature_schema_hash": manifest.feature_schema_hash,
            "model_id": manifest.model_id,
            "model_version": manifest.model_version,
            "model_hash": manifest.model_hash,
            "config_hash": manifest.config_hash,
            "train": [manifest.train_start, manifest.train_end],
            "validation": [manifest.validation_start, manifest.validation_end],
            "locked_oos": [manifest.locked_oos_start, manifest.locked_oos_end],
            "purge_sessions": manifest.purge_sessions,
            "embargo_sessions": manifest.embargo_sessions,
            "label_horizon_sessions": manifest.label_horizon_sessions,
            "universe_semantics": manifest.universe_semantics,
            "benchmark_id": manifest.benchmark_id,
            "benchmark_semantics": manifest.benchmark_semantics,
            "transaction_costs_bps": manifest.transaction_costs_bps,
            "slippage_bps": manifest.slippage_bps,
            "execution_price_policy": manifest.execution_price_policy,
            "calendar_semantics": manifest.calendar_semantics,
            "corporate_action_semantics": manifest.corporate_action_semantics,
        }
    )


def validate_replay_identity(
    manifest: LockedOOSProtocolManifest,
    identity: Mapping[str, object],
) -> tuple[str, ...]:
    expected = {
        "dataset_hash": manifest.dataset_hash,
        "dataset_vintage": manifest.dataset_vintage,
        "feature_schema_hash": manifest.feature_schema_hash,
        "model_id": manifest.model_id,
        "model_version": manifest.model_version,
        "model_hash": manifest.model_hash,
        "config_hash": manifest.config_hash,
        "universe_semantics": manifest.universe_semantics,
        "benchmark_id": manifest.benchmark_id,
        "benchmark_semantics": manifest.benchmark_semantics,
        "transaction_costs_bps": manifest.transaction_costs_bps,
        "slippage_bps": manifest.slippage_bps,
        "execution_price_policy": manifest.execution_price_policy,
        "calendar_semantics": manifest.calendar_semantics,
        "corporate_action_semantics": manifest.corporate_action_semantics,
    }
    blockers: list[str] = []
    for field_name, expected_value in expected.items():
        if identity.get(field_name) != expected_value:
            blockers.append("LOCKED_OOS_" + field_name.upper() + "_MISMATCH")
    return tuple(blockers)


def open_locked_oos(
    manifest: LockedOOSProtocolManifest,
    *,
    evaluation_id: str,
    replay_inputs: Mapping[str, object],
    data_certification_status: EvidenceStatus | str,
    attempted_at: datetime | None = None,
) -> LockedOOSOpeningAudit:
    """Record an auditable open attempt; blocked attempts never consume OOS."""

    when = (attempted_at or datetime.now(UTC)).astimezone(UTC)
    blockers = list(validate_protocol_manifest(manifest))
    if manifest.seal_state is not LockedOOSSealState.SEALED:
        blockers.append("LOCKED_OOS_NOT_READY_TO_OPEN")
    if EvidenceStatus(str(data_certification_status)) is not EvidenceStatus.PASS:
        blockers.append("LOCKED_OOS_DATA_CERTIFICATION_REQUIRED")
    blockers.extend(validate_replay_identity(manifest, replay_inputs))
    if manifest.evaluation_count != 0:
        blockers.append("LOCKED_OOS_ALREADY_EVALUATED")
    if not evaluation_id.strip():
        blockers.append("LOCKED_OOS_EVALUATION_ID_REQUIRED")
    unique_blockers = tuple(dict.fromkeys(blockers))
    state = LockedOOSOpeningState.OPENED if not unique_blockers else LockedOOSOpeningState.BLOCKED
    audit_payload = {
        "evaluation_id": evaluation_id,
        "attempted_at": when,
        "manifest_hash": manifest.manifest_hash,
        "state": state.value,
        "replay_identity": replay_identity(manifest),
        "blockers": unique_blockers,
    }
    return LockedOOSOpeningAudit(
        evaluation_id=evaluation_id,
        attempted_at=when,
        manifest_hash=manifest.manifest_hash,
        state=state,
        replay_identity=replay_identity(manifest),
        blockers=unique_blockers,
        audit_hash=fingerprint(audit_payload),
    )


def record_locked_oos_evaluation(
    manifest: LockedOOSProtocolManifest,
    opening: LockedOOSOpeningAudit,
    *,
    result_hash: str,
    post_hoc_tuning: bool = False,
) -> LockedOOSProtocolManifest:
    if opening.state is not LockedOOSOpeningState.OPENED:
        raise ValueError("LOCKED_OOS_OPENING_BLOCKED")
    if manifest.seal_state is not LockedOOSSealState.SEALED or manifest.evaluation_count != 0:
        raise ValueError("LOCKED_OOS_EVALUATION_NOT_ALLOWED")
    if opening.manifest_hash != manifest.manifest_hash:
        raise ValueError("LOCKED_OOS_OPENING_MANIFEST_MISMATCH")
    if post_hoc_tuning:
        raise ValueError("LOCKED_OOS_POST_HOC_TUNING_FORBIDDEN")
    if not result_hash.strip():
        raise ValueError("LOCKED_OOS_RESULT_HASH_REQUIRED")
    evaluated = replace(
        manifest,
        seal_state=LockedOOSSealState.EVALUATED,
        evaluation_count=1,
        evaluation_id=opening.evaluation_id,
        opening_audit_hash=opening.audit_hash,
        evaluation_result_hash=result_hash,
        manifest_hash="",
    )
    return replace(evaluated, manifest_hash=_manifest_hash(evaluated))


def protocol_status(
    manifest: LockedOOSProtocolManifest | None,
    *,
    data_certification_status: EvidenceStatus | str,
) -> LockedOOSProtocolStatus:
    blockers: list[str] = []
    status_value = EvidenceStatus(str(data_certification_status))
    if status_value is not EvidenceStatus.PASS:
        blockers.append("CERTIFIED_DATA_FOUNDATION_REQUIRED")
    if manifest is None:
        blockers.append("LOCKED_OOS_MANIFEST_MISSING")
        status = EvidenceStatus.BLOCKED_DATA_QUALITY if status_value is not EvidenceStatus.PASS else EvidenceStatus.BLOCKED_OOS
        return LockedOOSProtocolStatus(status, None, None, tuple(blockers), False)
    blockers.extend(validate_protocol_manifest(manifest))
    if manifest.seal_state is not LockedOOSSealState.EVALUATED:
        blockers.append("LOCKED_OOS_NOT_EVALUATED")
    status = EvidenceStatus.PASS if not blockers else (
        EvidenceStatus.BLOCKED_DATA_QUALITY if status_value is not EvidenceStatus.PASS else EvidenceStatus.BLOCKED_OOS
    )
    return LockedOOSProtocolStatus(
        status,
        manifest.manifest_hash,
        manifest.seal_state,
        tuple(dict.fromkeys(blockers)),
        status is EvidenceStatus.PASS,
    )


def parse_locked_oos_protocol(document: Mapping[str, object]) -> LockedOOSProtocolManifest:
    """Parse an on-disk manifest and let its constructor verify the sealed identity."""

    def text(name: str) -> str:
        value = document.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value

    def integer(name: str) -> int:
        value = document.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        return value

    def number(name: str) -> float:
        value = document.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        return float(value)

    manifest_hash_value = document.get("manifest_hash", "")
    if not isinstance(manifest_hash_value, str):
        raise ValueError("manifest_hash must be a string")

    return LockedOOSProtocolManifest(
        protocol_version=text("protocol_version"),
        dataset_id=text("dataset_id"),
        dataset_hash=text("dataset_hash"),
        dataset_vintage=text("dataset_vintage"),
        feature_schema_hash=text("feature_schema_hash"),
        model_id=text("model_id"),
        model_version=text("model_version"),
        model_hash=text("model_hash"),
        config_hash=text("config_hash"),
        train_start=date.fromisoformat(text("train_start")),
        train_end=date.fromisoformat(text("train_end")),
        validation_start=date.fromisoformat(text("validation_start")),
        validation_end=date.fromisoformat(text("validation_end")),
        locked_oos_start=date.fromisoformat(text("locked_oos_start")),
        locked_oos_end=date.fromisoformat(text("locked_oos_end")),
        purge_sessions=integer("purge_sessions"),
        embargo_sessions=integer("embargo_sessions"),
        label_horizon_sessions=integer("label_horizon_sessions"),
        universe_semantics=text("universe_semantics"),
        benchmark_id=text("benchmark_id"),
        benchmark_semantics=text("benchmark_semantics"),
        transaction_costs_bps=number("transaction_costs_bps"),
        slippage_bps=number("slippage_bps"),
        execution_price_policy=text("execution_price_policy"),
        calendar_semantics=text("calendar_semantics"),
        corporate_action_semantics=text("corporate_action_semantics"),
        created_at=_parse_datetime(text("created_at"), "created_at"),
        seal_state=LockedOOSSealState(text("seal_state")),
        sealed_at=(
            _parse_datetime(str(document["sealed_at"]), "sealed_at")
            if document.get("sealed_at") is not None
            else None
        ),
        evaluation_count=integer("evaluation_count"),
        evaluation_id=(str(document["evaluation_id"]) if document.get("evaluation_id") else None),
        opening_audit_hash=(
            str(document["opening_audit_hash"]) if document.get("opening_audit_hash") else None
        ),
        evaluation_result_hash=(
            str(document["evaluation_result_hash"])
            if document.get("evaluation_result_hash")
            else None
        ),
        manifest_hash=manifest_hash_value,
    )


def load_locked_oos_protocol(path: Path) -> LockedOOSProtocolManifest:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, Mapping):
        raise ValueError("locked OOS manifest must be a JSON object")
    return parse_locked_oos_protocol(cast(Mapping[str, object], document))


def persist_locked_oos_protocol(path: Path, manifest: LockedOOSProtocolManifest) -> None:
    """Write once; existing manifest files are never overwritten."""

    if manifest.seal_state is LockedOOSSealState.DRAFT:
        raise ValueError("only sealed/evaluated locked OOS manifests may be persisted")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest.document(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def persist_locked_oos_opening_audit(path: Path, audit: LockedOOSOpeningAudit) -> None:
    """Persist every allowed or blocked opening attempt as an immutable audit record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(audit.document(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _manifest_hash(manifest: LockedOOSProtocolManifest) -> str:
    payload = asdict(manifest)
    payload["manifest_hash"] = ""
    return fingerprint(payload)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _parse_datetime(value: str, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_aware(parsed, field_name)
    return parsed.astimezone(UTC)
