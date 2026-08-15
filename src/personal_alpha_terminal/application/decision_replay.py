"""ROUND26 P0: Deterministic Decision Replay + Decision Drift Attribution.

Replay recomputes the decision semantic hash from the persisted run
certificate and compares it with the sealed DecisionManifest hash.  A replay
is PASS only when both hashes exist and match.

Decision diff compares two persisted run certificates and classifies the
drift between them (DATA_CHANGE / UNIVERSE_CHANGE / PORTFOLIO_CHANGE /
CONFIG_CHANGE / MODEL_CHANGE / POLICY_CHANGE / NONDETERMINISM_SUSPECTED).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personal_alpha_terminal.application.decision_manifest import (
    DecisionManifest,
    compute_semantic_hash,
)

REPLAY_PASS = "REPLAY_PASS"
REPLAY_FAIL = "REPLAY_FAIL"


@dataclass(frozen=True, slots=True)
class ReplayReport:
    status: str
    run_id: str
    manifest_hash: str
    recomputed_hash: str
    detail: str

    def document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "manifest_hash": self.manifest_hash,
            "recomputed_hash": self.recomputed_hash,
            "detail": self.detail,
        }


def _manifest_from_certificate(certificate: dict[str, Any]) -> DecisionManifest | None:
    raw = certificate.get("decision_manifest")
    if not isinstance(raw, dict):
        return None
    manifest = DecisionManifest(
        run_id=str(raw.get("run_id", "")),
        decision_id=str(raw.get("decision_id", "")),
        analysis_date=str(raw.get("analysis_date", "")),
        decision_cutoff=str(raw.get("decision_cutoff", "")),
        trade_date=str(raw.get("trade_date", "")),
        market_data_snapshot_id=str(raw.get("market_data_snapshot_id", "")),
        market_data_hash=str(raw.get("market_data_hash", "")),
        universe_snapshot_id=str(raw.get("universe_snapshot_id", "")),
        universe_hash=str(raw.get("universe_hash", "")),
        portfolio_snapshot_id=str(raw.get("portfolio_snapshot_id", "")),
        portfolio_hash=str(raw.get("portfolio_hash", "")),
        config_hash=str(raw.get("config_hash", "")),
        feature_version=str(raw.get("feature_version", "")),
        factor_model_id=str(raw.get("factor_model_id", "")),
        alpha_model_id=str(raw.get("alpha_model_id", "")),
        probability_model_id=str(raw.get("probability_model_id", "")),
        portfolio_model_id=str(raw.get("portfolio_model_id", "")),
        risk_model_id=str(raw.get("risk_model_id", "")),
        cost_model_id=str(raw.get("cost_model_id", "")),
        strategy_approval_id=str(raw.get("strategy_approval_id", "")),
        operational_policy_id=str(raw.get("operational_policy_id", "")),
        random_seed=int(raw.get("random_seed", 0)),
        solver_name=str(raw.get("solver_name", "")),
        solver_version=str(raw.get("solver_version", "")),
        formal_action_ids=tuple(str(item) for item in (raw.get("formal_action_ids") or [])),
        execution_plan_id=str(raw.get("execution_plan_id", "")),
        created_at=str(raw.get("created_at", "")),
        schema_version=str(raw.get("schema_version", "decision-manifest-v1")),
        semantic_hash=str(raw.get("semantic_hash", "")),
    )
    return manifest


def replay_decision(run_dir: Path) -> ReplayReport:
    certificate_path = run_dir / "run_certificate.json"
    if not certificate_path.exists():
        return ReplayReport(
            REPLAY_FAIL, run_dir.name, "", "", "run_certificate.json missing"
        )
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ReplayReport(REPLAY_FAIL, run_dir.name, "", "", f"unreadable: {error}")
    manifest = _manifest_from_certificate(certificate)
    if manifest is None:
        return ReplayReport(
            REPLAY_FAIL,
            str(certificate.get("run_id", run_dir.name)),
            "",
            "",
            "decision manifest missing from certificate",
        )
    recomputed = compute_semantic_hash(manifest)
    stored = manifest.semantic_hash
    status = REPLAY_PASS if stored == recomputed else REPLAY_FAIL
    detail = (
        "semantic hash recomputed from certificate inputs and matched"
        if status == REPLAY_PASS
        else "semantic hash mismatch between stored manifest and recomputed inputs"
    )
    return ReplayReport(status, manifest.run_id, stored, recomputed, detail)


@dataclass(frozen=True, slots=True)
class DecisionDiffReport:
    old_run: str
    new_run: str
    old_manifest_hash: str
    new_manifest_hash: str
    differences: dict[str, object]
    attribution: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return {
            "old_run": self.old_run,
            "new_run": self.new_run,
            "old_manifest_hash": self.old_manifest_hash,
            "new_manifest_hash": self.new_manifest_hash,
            "differences": dict(self.differences),
            "attribution": list(self.attribution),
        }


def _symbol_action_map(certificate: dict[str, Any]) -> dict[str, str]:
    rows = certificate.get("decision_recommendations") or []
    return {
        str(item.get("symbol")): str(item.get("action"))
        for item in rows
        if isinstance(item, dict) and item.get("symbol")
    }


def diff_decisions(old_run_dir: Path, new_run_dir: Path) -> DecisionDiffReport:
    def load(path: Path) -> dict[str, Any]:
        payload = json.loads((path / "run_certificate.json").read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    old_cert = load(old_run_dir)
    new_cert = load(new_run_dir)
    old_manifest = _manifest_from_certificate(old_cert)
    new_manifest = _manifest_from_certificate(new_cert)
    old_hash = old_manifest.semantic_hash if old_manifest else ""
    new_hash = new_manifest.semantic_hash if new_manifest else ""

    old_actions = _symbol_action_map(old_cert)
    new_actions = _symbol_action_map(new_cert)
    added = sorted(set(new_actions) - set(old_actions))
    removed = sorted(set(old_actions) - set(new_actions))
    changed = sorted(
        symbol
        for symbol in set(old_actions) & set(new_actions)
        if old_actions[symbol] != new_actions[symbol]
    )

    old_recs = {
        str(item.get("symbol")): item
        for item in (old_cert.get("decision_recommendations") or [])
        if isinstance(item, dict)
    }
    new_recs = {
        str(item.get("symbol")): item
        for item in (new_cert.get("decision_recommendations") or [])
        if isinstance(item, dict)
    }
    weight_changes = {
        symbol: {
            "old_target_weight": old_recs[symbol].get("target_weight"),
            "new_target_weight": new_recs[symbol].get("target_weight"),
        }
        for symbol in set(old_recs) & set(new_recs)
        if abs(
            float(old_recs[symbol].get("target_weight") or 0)
            - float(new_recs[symbol].get("target_weight") or 0)
        )
        > 1e-6
    }

    old_prov = old_cert.get("provenance") or {}
    new_prov = new_cert.get("provenance") or {}
    differences: dict[str, object] = {
        "market_data_changed": old_prov.get("data_hash") != new_prov.get("data_hash"),
        "portfolio_changed": old_prov.get("portfolio_snapshot_id")
        != new_prov.get("portfolio_snapshot_id"),
        "universe_changed": old_prov.get("universe_version")
        != new_prov.get("universe_version"),
        "config_changed": old_cert.get("config_hash") != new_cert.get("config_hash"),
        "model_changed": old_cert.get("model_versions") != new_cert.get("model_versions"),
        "policy_changed": old_cert.get("operational_policy_id")
        != new_cert.get("operational_policy_id"),
        "formal_actions_added": added,
        "formal_actions_removed": removed,
        "formal_actions_changed": changed,
        "target_weight_changes": weight_changes,
        "decision_counts_old": old_cert.get("decision_counts"),
        "decision_counts_new": new_cert.get("decision_counts"),
    }
    attribution: list[str] = []
    if differences["market_data_changed"]:
        attribution.append("DATA_CHANGE")
    if differences["universe_changed"]:
        attribution.append("UNIVERSE_CHANGE")
    if differences["portfolio_changed"]:
        attribution.append("PORTFOLIO_CHANGE")
    if differences["config_changed"]:
        attribution.append("CONFIG_CHANGE")
    if differences["model_changed"]:
        attribution.append("MODEL_CHANGE")
    if differences["policy_changed"]:
        attribution.append("POLICY_CHANGE")
    if not attribution and (added or removed or changed or weight_changes):
        attribution.append("NONDETERMINISM_SUSPECTED")
    if not attribution:
        attribution.append("NO_DECISION_DRIFT")
    return DecisionDiffReport(
        old_run=str(old_cert.get("run_id", old_run_dir.name)),
        new_run=str(new_cert.get("run_id", new_run_dir.name)),
        old_manifest_hash=old_hash,
        new_manifest_hash=new_hash,
        differences=differences,
        attribution=tuple(attribution),
    )
