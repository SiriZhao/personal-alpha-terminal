"""Reproducible, fail-closed strategy production certification.

This module evaluates supplied validation evidence.  It never manufactures
backtest observations and never promotes a strategy merely because live data is
available.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
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


@dataclass(frozen=True)
class StrategyCertificationEvidence:
    strategy_version: str
    parameter_hash: str
    data_version: str
    universe_version: str
    train_end: date
    validation_end: date
    oos_start: date
    oos_end: date
    oos_sessions: int
    walk_forward_folds: int
    pit_valid: bool
    survivorship_controlled: bool
    corporate_actions_valid: bool
    future_rows: int
    benchmark_same_pit_convention: bool
    net_sharpe: float
    net_return: float
    spy_net_return: float
    qqq_net_return: float
    max_drawdown: float
    annual_turnover: float
    max_position_weight: float
    stability_score: float
    commission_bps: float
    spread_bps: float
    slippage_bps: float
    impact_bps: float


@dataclass(frozen=True)
class StrategyCertificationArtifact:
    artifact_id: str
    status: str
    blockers: tuple[str, ...]
    policy: StrategyCertificationPolicy
    evidence: StrategyCertificationEvidence
    created_at: datetime

    def document(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        for key in ("train_end", "validation_end", "oos_start", "oos_end"):
            payload["evidence"][key] = getattr(self.evidence, key).isoformat()
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
    if not (evidence.train_end < evidence.validation_end < evidence.oos_start <= evidence.oos_end):
        blockers.append("INVALID_TEMPORAL_SPLIT")
    if evidence.oos_sessions < policy.min_oos_sessions:
        blockers.append("INSUFFICIENT_LOCKED_OOS_SESSIONS")
    if evidence.walk_forward_folds < policy.min_walk_forward_folds:
        blockers.append("INSUFFICIENT_WALK_FORWARD_FOLDS")
    if not evidence.pit_valid or evidence.future_rows != 0:
        blockers.append("PIT_OR_FUTURE_ROW_FAILURE")
    if not evidence.survivorship_controlled:
        blockers.append("SURVIVORSHIP_NOT_CONTROLLED")
    if not evidence.corporate_actions_valid:
        blockers.append("CORPORATE_ACTIONS_NOT_CERTIFIED")
    if not evidence.benchmark_same_pit_convention:
        blockers.append("BENCHMARK_PIT_CONVENTION_MISMATCH")
    if min(evidence.commission_bps, evidence.spread_bps, evidence.slippage_bps) <= 0:
        blockers.append("TRANSACTION_COST_COMPONENT_MISSING")
    if evidence.impact_bps < 0:
        blockers.append("INVALID_MARKET_IMPACT")
    if evidence.net_sharpe < policy.min_net_sharpe:
        blockers.append("NET_SHARPE_BELOW_THRESHOLD")
    if evidence.net_return <= max(evidence.spy_net_return, evidence.qqq_net_return):
        blockers.append("NO_AFTER_COST_BENCHMARK_ALPHA")
    if evidence.max_drawdown > policy.max_drawdown:
        blockers.append("DRAWDOWN_ABOVE_LIMIT")
    if evidence.annual_turnover > policy.max_annual_turnover:
        blockers.append("TURNOVER_ABOVE_LIMIT")
    if evidence.max_position_weight > policy.max_position_weight:
        blockers.append("CONCENTRATION_ABOVE_LIMIT")
    if evidence.stability_score < policy.min_stability_score:
        blockers.append("STABILITY_BELOW_THRESHOLD")

    identity = fingerprint({"policy": asdict(policy), "evidence": asdict(evidence)})
    return StrategyCertificationArtifact(
        artifact_id=f"strategy-cert-{identity}",
        status="PRODUCTION_APPROVED" if not blockers else "BLOCKED",
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
