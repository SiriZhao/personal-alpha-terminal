"""Reproducible, fail-closed strategy production certification.

This module evaluates supplied validation evidence.  It never manufactures
backtest observations and never promotes a strategy merely because live data is
available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from personal_alpha_terminal.core.fingerprints import fingerprint


@dataclass(frozen=True)
class StrategyCertificationPolicy:
    min_oos_sessions: int = 252
    min_walk_forward_folds: int = 4
    min_net_sharpe: float = 0.50
    min_stability_score: float = 0.60
    max_drawdown: float = 0.25
    max_annual_turnover: float = 4.0
    max_position_weight: float = 0.15


class StrategyCertificationStatus(StrEnum):
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True)
class StrategyCertificationEvidence:
    strategy_version: str
    parameter_hash: str
    data_version: str
    universe_version: str
    research_manifest_id: str
    research_manifest_hash: str
    research_data_hash: str | None
    candidate_manifest_hash: str
    locked_oos_definition_hash: str
    data_certification_state: str
    train_end: date | None
    validation_end: date | None
    oos_start: date | None
    oos_end: date | None
    oos_sessions: int
    walk_forward_folds: int
    pit_valid: bool
    survivorship_controlled: bool
    corporate_actions_valid: bool
    future_rows: int
    benchmark_same_pit_convention: bool
    net_sharpe: float | None
    net_return: float | None
    spy_net_return: float | None
    qqq_net_return: float | None
    max_drawdown: float | None
    annual_turnover: float | None
    max_position_weight: float | None
    stability_score: float | None
    commission_bps: float
    spread_bps: float
    slippage_bps: float
    impact_bps: float


@dataclass(frozen=True)
class StrategyCertificationArtifact:
    artifact_id: str
    status: StrategyCertificationStatus
    blockers: tuple[str, ...]
    policy: StrategyCertificationPolicy
    evidence: StrategyCertificationEvidence
    created_at: datetime

    def document(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        for key in ("train_end", "validation_end", "oos_start", "oos_end"):
            value = getattr(self.evidence, key)
            payload["evidence"][key] = value.isoformat() if value is not None else None
        payload["blockers"] = list(self.blockers)
        return payload


def certify_strategy(
    evidence: StrategyCertificationEvidence,
    policy: StrategyCertificationPolicy | None = None,
    *,
    created_at: datetime | None = None,
) -> StrategyCertificationArtifact:
    """Evaluate real validation evidence against immutable production gates."""

    policy = policy or StrategyCertificationPolicy()
    blockers: list[str] = []
    lineage = (
        evidence.strategy_version,
        evidence.parameter_hash,
        evidence.data_version,
        evidence.universe_version,
        evidence.research_manifest_id,
        evidence.research_manifest_hash,
        evidence.candidate_manifest_hash,
        evidence.locked_oos_definition_hash,
    )
    not_certifiable = False
    if not all(item.strip() for item in lineage):
        blockers.append("RESEARCH_LINEAGE_INCOMPLETE")
        not_certifiable = True
    if evidence.data_certification_state != "CERTIFIED":
        blockers.append("SURVIVORSHIP_DATA_INSUFFICIENT")
        not_certifiable = True
    if not evidence.research_data_hash:
        blockers.append("RESEARCH_DATA_CONTENT_HASH_MISSING")
        not_certifiable = True
    periods = (
        evidence.train_end,
        evidence.validation_end,
        evidence.oos_start,
        evidence.oos_end,
    )
    if any(item is None for item in periods):
        blockers.append("LOCKED_OOS_NOT_RUN")
        not_certifiable = True
    else:
        train_end = evidence.train_end
        validation_end = evidence.validation_end
        oos_start = evidence.oos_start
        oos_end = evidence.oos_end
        assert train_end is not None
        assert validation_end is not None
        assert oos_start is not None
        assert oos_end is not None
        if not (train_end < validation_end < oos_start <= oos_end):
            blockers.append("INVALID_TEMPORAL_SPLIT")
    if evidence.oos_sessions < policy.min_oos_sessions:
        blockers.append("INSUFFICIENT_LOCKED_OOS_SESSIONS")
    if evidence.walk_forward_folds < policy.min_walk_forward_folds:
        blockers.append("INSUFFICIENT_WALK_FORWARD_FOLDS")
    if not evidence.pit_valid or evidence.future_rows != 0:
        blockers.append("PIT_OR_FUTURE_ROW_FAILURE")
        not_certifiable = True
    if not evidence.survivorship_controlled:
        blockers.append("SURVIVORSHIP_NOT_CONTROLLED")
        not_certifiable = True
    if not evidence.corporate_actions_valid:
        blockers.append("CORPORATE_ACTIONS_NOT_CERTIFIED")
        not_certifiable = True
    if not evidence.benchmark_same_pit_convention:
        blockers.append("BENCHMARK_PIT_CONVENTION_MISMATCH")
    if min(evidence.commission_bps, evidence.spread_bps, evidence.slippage_bps) <= 0:
        blockers.append("TRANSACTION_COST_COMPONENT_MISSING")
    if evidence.impact_bps < 0:
        blockers.append("INVALID_MARKET_IMPACT")
    metrics = (
        evidence.net_sharpe,
        evidence.net_return,
        evidence.spy_net_return,
        evidence.qqq_net_return,
        evidence.max_drawdown,
        evidence.annual_turnover,
        evidence.max_position_weight,
        evidence.stability_score,
    )
    if any(item is None for item in metrics):
        blockers.append("OOS_AFTER_COST_METRICS_NOT_AVAILABLE")
        not_certifiable = True
    else:
        assert evidence.net_sharpe is not None
        assert evidence.net_return is not None
        assert evidence.spy_net_return is not None
        assert evidence.qqq_net_return is not None
        assert evidence.max_drawdown is not None
        assert evidence.annual_turnover is not None
        assert evidence.max_position_weight is not None
        assert evidence.stability_score is not None
        if evidence.net_sharpe < policy.min_net_sharpe:
            blockers.append("OOS_ALPHA_INSUFFICIENT")
        if evidence.net_return <= max(evidence.spy_net_return, evidence.qqq_net_return):
            blockers.append("AFTER_COST_ALPHA_NEGATIVE")
        if evidence.max_drawdown > policy.max_drawdown:
            blockers.append("DRAWDOWN_EXCESSIVE")
        if evidence.annual_turnover > policy.max_annual_turnover:
            blockers.append("TURNOVER_EXCESSIVE")
        if evidence.max_position_weight > policy.max_position_weight:
            blockers.append("CONCENTRATION_EXCESSIVE")
        if evidence.stability_score < policy.min_stability_score:
            blockers.append("IC_UNSTABLE")

    identity = fingerprint({"policy": asdict(policy), "evidence": asdict(evidence)})
    status = (
        StrategyCertificationStatus.NOT_CERTIFIABLE
        if not_certifiable
        else StrategyCertificationStatus.REJECTED
        if blockers
        else StrategyCertificationStatus.PRODUCTION_APPROVED
    )
    return StrategyCertificationArtifact(
        artifact_id=f"strategy-cert-{identity}",
        status=status,
        blockers=tuple(blockers),
        policy=policy,
        evidence=evidence,
        created_at=created_at or datetime.now(UTC),
    )


def persist_certification_artifact(
    artifact: StrategyCertificationArtifact, output_dir: Path
) -> Path:
    """Persist an immutable artifact; refuse conflicting overwrites."""

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{artifact.artifact_id}.json"
    rendered = json.dumps(artifact.document(), ensure_ascii=False, indent=2, sort_keys=True)
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable artifact: {target}")
    target.write_text(rendered, encoding="utf-8")
    return target


@dataclass(frozen=True, slots=True)
class StrategyApprovalIdentity:
    strategy_version: str
    parameter_hash: str
    data_version: str
    research_data_hash: str
    research_manifest_hash: str


def persist_approval_artifact(
    artifact: StrategyCertificationArtifact, output_dir: Path
) -> Path:
    """Write an approval only after every certification gate has passed."""

    if artifact.status is not StrategyCertificationStatus.PRODUCTION_APPROVED:
        raise ValueError("failed or uncertifiable research cannot produce an approval artifact")
    evidence = artifact.evidence
    assert evidence.research_data_hash is not None
    identity = StrategyApprovalIdentity(
        strategy_version=evidence.strategy_version,
        parameter_hash=evidence.parameter_hash,
        data_version=evidence.data_version,
        research_data_hash=evidence.research_data_hash,
        research_manifest_hash=evidence.research_manifest_hash,
    )
    payload = {
        "artifact_id": artifact.artifact_id,
        "status": artifact.status,
        "identity": identity,
        "certification_hash": fingerprint(artifact.document()),
        "approved_at": artifact.created_at,
    }
    rendered = json.dumps(payload, default=str, ensure_ascii=False, indent=2, sort_keys=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{artifact.artifact_id}.json"
    if target.exists():
        raise FileExistsError(f"immutable approval artifact already exists: {target}")
    target.write_text(rendered, encoding="utf-8")
    return target


def approval_matches(
    artifact: StrategyCertificationArtifact, identity: StrategyApprovalIdentity
) -> bool:
    evidence = artifact.evidence
    return (
        artifact.status is StrategyCertificationStatus.PRODUCTION_APPROVED
        and evidence.strategy_version == identity.strategy_version
        and evidence.parameter_hash == identity.parameter_hash
        and evidence.data_version == identity.data_version
        and evidence.research_data_hash == identity.research_data_hash
        and evidence.research_manifest_hash == identity.research_manifest_hash
    )
