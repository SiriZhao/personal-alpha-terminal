"""ROUND26 P0: DecisionManifest -- the single immutable source of truth.

Every formal output (terminal, AI brief, action table, execution plan, risk
summary, portfolio target, run certificate) must derive from one immutable
DecisionManifest.  Renderers are forbidden from recomputing decision state.

Lifecycle:  RunIdentity (created at run start) -> DecisionManifest (sealed at
the end of the pipeline from real provenance) -> Artifacts -> final
run_certificate.json.  Evidence references use ``run:<run_id>``,
``decision:<decision_id>`` and ``decision-manifest:<semantic_hash16>``; the
literal ``UNKNOWN`` / ``N/A`` / ``FAKE`` / ``PLACEHOLDER`` never appears as a
formal evidence reference.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

MANIFEST_SCHEMA_VERSION = "decision-manifest-v1"


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Stable identity created at run start (before any artifact exists)."""

    run_id: str
    decision_id: str
    created_at: datetime

    def document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "created_at": self.created_at.isoformat(),
        }

    def evidence_ref(self) -> str:
        return f"run:{self.run_id}"

    def decision_ref(self) -> str:
        return f"decision:{self.decision_id}"

    @staticmethod
    def create(run_id: str, now: datetime | None = None) -> RunIdentity:
        created = (now or datetime.now(UTC)).astimezone(UTC)
        return RunIdentity(
            run_id=run_id,
            decision_id=f"decision-{run_id.removeprefix('daily-')}",
            created_at=created,
        )


@dataclass(frozen=True, slots=True)
class DecisionManifest:
    run_id: str
    decision_id: str
    analysis_date: str
    decision_cutoff: str
    trade_date: str
    market_data_snapshot_id: str
    market_data_hash: str
    universe_snapshot_id: str
    universe_hash: str
    portfolio_snapshot_id: str
    portfolio_hash: str
    config_hash: str
    feature_version: str
    factor_model_id: str
    alpha_model_id: str
    probability_model_id: str
    portfolio_model_id: str
    risk_model_id: str
    cost_model_id: str
    strategy_approval_id: str
    operational_policy_id: str
    random_seed: int
    solver_name: str
    solver_version: str
    formal_action_ids: tuple[str, ...]
    execution_plan_id: str
    created_at: str
    schema_version: str = MANIFEST_SCHEMA_VERSION
    semantic_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["semantic_hash"] = self.semantic_hash or compute_semantic_hash(self)
        return payload


# Fields whose values change run-to-run without affecting the decision itself
# (presentation timestamps, paths, run-local metadata).
_SEMANTIC_EXCLUDED = frozenset({"created_at", "semantic_hash", "execution_plan_id"})


def compute_semantic_hash(manifest: DecisionManifest) -> str:
    """Hash only decision-relevant fields, with stable ordering."""

    payload: dict[str, Any] = {}
    for key, value in asdict(manifest).items():
        if key in _SEMANTIC_EXCLUDED:
            continue
        payload[key] = value
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def seal_decision_manifest(
    *,
    identity: RunIdentity,
    decision_cutoff: datetime,
    analysis_date: Any,
    trade_date: Any,
    market_data_snapshot_id: str,
    market_data_hash: str,
    universe_snapshot_id: str,
    universe_hash: str,
    portfolio_snapshot_id: str,
    portfolio_hash: str,
    config_hash: str,
    feature_version: str,
    factor_model_id: str,
    alpha_model_id: str,
    probability_model_id: str,
    portfolio_model_id: str,
    risk_model_id: str,
    cost_model_id: str,
    strategy_approval_id: str,
    operational_policy_id: str,
    random_seed: int,
    solver_name: str,
    solver_version: str,
    formal_action_ids: tuple[str, ...],
    execution_plan_id: str,
) -> DecisionManifest:
    manifest = DecisionManifest(
        run_id=identity.run_id,
        decision_id=identity.decision_id,
        analysis_date=str(analysis_date),
        decision_cutoff=decision_cutoff.isoformat(),
        trade_date=str(trade_date),
        market_data_snapshot_id=market_data_snapshot_id,
        market_data_hash=market_data_hash,
        universe_snapshot_id=universe_snapshot_id,
        universe_hash=universe_hash,
        portfolio_snapshot_id=portfolio_snapshot_id,
        portfolio_hash=portfolio_hash,
        config_hash=config_hash,
        feature_version=feature_version,
        factor_model_id=factor_model_id,
        alpha_model_id=alpha_model_id,
        probability_model_id=probability_model_id,
        portfolio_model_id=portfolio_model_id,
        risk_model_id=risk_model_id,
        cost_model_id=cost_model_id,
        strategy_approval_id=strategy_approval_id,
        operational_policy_id=operational_policy_id,
        random_seed=random_seed,
        solver_name=solver_name,
        solver_version=solver_version,
        formal_action_ids=tuple(formal_action_ids),
        execution_plan_id=execution_plan_id,
        created_at=identity.created_at.isoformat(),
    )
    return DecisionManifest(
        **{**asdict(manifest), "semantic_hash": compute_semantic_hash(manifest)}
    )


def manifest_evidence_refs(manifest: DecisionManifest) -> tuple[str, ...]:
    return (
        f"run:{manifest.run_id}",
        f"decision:{manifest.decision_id}",
        f"decision-manifest:{manifest.semantic_hash[:16]}",
    )
