"""ROUND26 P0: DecisionManifest single-source-of-truth tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from personal_alpha_terminal.application.decision_manifest import (
    DecisionManifest,
    RunIdentity,
    compute_semantic_hash,
    manifest_evidence_refs,
    seal_decision_manifest,
)


def _seal() -> DecisionManifest:
    return seal_decision_manifest(
        identity=RunIdentity.create("daily-test123", now=datetime(2026, 8, 15, tzinfo=UTC)),
        decision_cutoff=datetime(2026, 8, 14, 20, 30, tzinfo=UTC),
        analysis_date=date(2026, 8, 14),
        trade_date=date(2026, 8, 15),
        market_data_snapshot_id="US-20260814",
        market_data_hash="d1",
        universe_snapshot_id="5",
        universe_hash="u1",
        portfolio_snapshot_id="p1",
        portfolio_hash="ph1",
        config_hash="c1",
        feature_version="v1",
        factor_model_id="USAdaptiveAlphaCoreV1:1.0.0:427671e52a53",
        alpha_model_id="USAdaptiveAlphaCoreV1:1.0.0:427671e52a53",
        probability_model_id="PROBABILITY_FALLBACK_CLASSICAL",
        portfolio_model_id="constrained-alpha-risk-v1",
        risk_model_id="r1",
        cost_model_id="cost1",
        strategy_approval_id="strategy-approval-x",
        operational_policy_id="operational-policy-y",
        random_seed=0,
        solver_name="SLSQP",
        solver_version="1.14.0",
        formal_action_ids=("rec:VSTS", "rec:ATEX"),
        execution_plan_id="manual-plan-daily-test123",
    )


def test_manifest_seal_and_hash_stability() -> None:
    manifest = _seal()
    assert manifest.semantic_hash == compute_semantic_hash(manifest)
    again = _seal()
    assert again.semantic_hash == manifest.semantic_hash


def test_semantic_hash_ignores_presentation_fields() -> None:
    manifest = _seal()
    later = replace(manifest, created_at="2099-01-01T00:00:00+00:00")
    assert compute_semantic_hash(later) == manifest.semantic_hash


def test_semantic_hash_changes_with_decision_inputs() -> None:
    manifest = _seal()
    changed = replace(manifest, config_hash="c2")
    assert compute_semantic_hash(changed) != manifest.semantic_hash
    changed_actions = replace(
        manifest, formal_action_ids=("rec:VSTS", "rec:ATEX", "rec:CNC")
    )
    assert compute_semantic_hash(changed_actions) != manifest.semantic_hash


def test_evidence_refs_are_never_unknown() -> None:
    manifest = _seal()
    refs = manifest_evidence_refs(manifest)
    assert refs[0].startswith("run:")
    assert refs[1].startswith("decision:")
    assert refs[2].startswith("decision-manifest:")
    for ref in refs:
        assert "UNKNOWN" not in ref
        assert "N/A" not in ref
        assert "FAKE" not in ref
        assert "PLACEHOLDER" not in ref


def test_run_identity_decision_id_is_stable() -> None:
    identity = RunIdentity.create("daily-abc123")
    assert identity.run_id == "daily-abc123"
    assert identity.decision_id == "decision-abc123"
