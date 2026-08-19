"""ROUND75 frozen research protocol tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.research.data_evidence import EvidenceStatus
from personal_alpha_terminal.research.locked_oos_protocol import (
    LockedOOSOpeningState,
    LockedOOSSealState,
    create_locked_oos_protocol,
    load_locked_oos_protocol,
    open_locked_oos,
    parse_locked_oos_protocol,
    persist_locked_oos_opening_audit,
    persist_locked_oos_protocol,
    protocol_status,
    record_locked_oos_evaluation,
    replay_identity,
    seal_locked_oos_protocol,
    validate_protocol_manifest,
    validate_replay_identity,
)

NOW = datetime(2024, 1, 3, 20, tzinfo=UTC)


def _draft():
    return create_locked_oos_protocol(
        dataset_id="dataset-1",
        dataset_hash="dataset-hash-1",
        dataset_vintage="vintage-2024-01",
        feature_schema_hash="feature-hash-1",
        model_id="CURRENT_PRODUCTION_QUANT",
        model_version="v1",
        model_hash="model-hash-1",
        config_hash="config-hash-1",
        train_start=date(2018, 1, 1),
        train_end=date(2020, 12, 31),
        validation_start=date(2021, 2, 1),
        validation_end=date(2021, 12, 31),
        locked_oos_start=date(2022, 2, 1),
        locked_oos_end=date(2023, 12, 31),
        purge_sessions=21,
        embargo_sessions=5,
        label_horizon_sessions=5,
        universe_semantics="historical membership by permanent security ID",
        benchmark_id="BENCHMARK:SP500",
        benchmark_semantics="POINT_IN_TIME_TOTAL_RETURN",
        transaction_costs_bps=10.0,
        slippage_bps=5.0,
        execution_price_policy="next legal session executable open",
        calendar_semantics="XNYS exchange calendar vintage v1",
        corporate_action_semantics="raw prices plus PIT action ledger, no double adjustment",
        dataset_snapshot_id="ROUND80-snapshot-1",
        factor_config_hash="factor-config-hash-1",
        portfolio_policy_hash="portfolio-policy-hash-1",
        risk_policy_hash="risk-policy-hash-1",
        cost_model_hash="cost-policy-hash-1",
        benchmark_policy_hash="benchmark-policy-hash-1",
        git_commit_sha="f87c9b550e9ff6bd8955f7b049552c27ec57066c",
        created_at=NOW,
    )


def _inputs(manifest):
    return {
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
        "dataset_snapshot_id": manifest.dataset_snapshot_id,
        "factor_config_hash": manifest.factor_config_hash,
        "portfolio_policy_hash": manifest.portfolio_policy_hash,
        "risk_policy_hash": manifest.risk_policy_hash,
        "cost_model_hash": manifest.cost_model_hash,
        "benchmark_policy_hash": manifest.benchmark_policy_hash,
        "git_commit_sha": manifest.git_commit_sha,
    }


def test_protocol_freezes_all_partitions_and_replay_identity() -> None:
    manifest = _draft()
    assert manifest.seal_state is LockedOOSSealState.DRAFT
    assert validate_protocol_manifest(manifest) == ("LOCKED_OOS_UNSEALED",)
    replayed = parse_locked_oos_protocol(manifest.document())
    assert replay_identity(manifest) == replay_identity(replayed)


def test_purge_must_cover_label_horizon_and_dates_must_not_overlap() -> None:
    with pytest.raises(ValueError, match="purge_sessions"):
        _draft_with(purge_sessions=2, label_horizon_sessions=5)
    with pytest.raises(ValueError, match="chronological"):
        _draft_with(validation_start=date(2020, 12, 1))


def _draft_with(**changes):
    values = _draft().document()
    values.update(
        {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in changes.items()
        }
    )
    values["seal_state"] = "DRAFT"
    values["sealed_at"] = None
    values["evaluation_count"] = 0
    values["evaluation_id"] = None
    values["opening_audit_hash"] = None
    values["evaluation_result_hash"] = None
    values["manifest_hash"] = ""
    return parse_locked_oos_protocol(values)


def test_seal_once_requires_certified_data_and_detects_tamper() -> None:
    with pytest.raises(ValueError, match="CERTIFIED_DATA"):
        seal_locked_oos_protocol(
            _draft(),
            data_certification_status=EvidenceStatus.BLOCKED_DATA_QUALITY,
        )
    sealed = seal_locked_oos_protocol(
        _draft(),
        data_certification_status=EvidenceStatus.PASS,
        sealed_at=NOW,
    )
    assert sealed.seal_state is LockedOOSSealState.SEALED
    assert validate_protocol_manifest(sealed) == ()
    tampered = dict(sealed.document())
    tampered["config_hash"] = "tampered"
    with pytest.raises(ValueError, match="manifest hash"):
        parse_locked_oos_protocol(tampered)
    with pytest.raises(ValueError, match="only once"):
        seal_locked_oos_protocol(sealed, data_certification_status=EvidenceStatus.PASS)


def test_blocked_open_attempt_is_auditable_and_does_not_consume_oos() -> None:
    sealed = seal_locked_oos_protocol(
        _draft(),
        data_certification_status=EvidenceStatus.PASS,
        sealed_at=NOW,
    )
    audit = open_locked_oos(
        sealed,
        evaluation_id="eval-blocked",
        replay_inputs=_inputs(sealed),
        data_certification_status=EvidenceStatus.BLOCKED_DATA_QUALITY,
        attempted_at=NOW,
    )
    assert audit.state is LockedOOSOpeningState.BLOCKED
    assert "LOCKED_OOS_DATA_CERTIFICATION_REQUIRED" in audit.blockers
    with pytest.raises(ValueError, match="OPENING_BLOCKED"):
        record_locked_oos_evaluation(sealed, audit, result_hash="result")


def test_open_evaluate_once_and_reject_post_hoc_or_repeat() -> None:
    sealed = seal_locked_oos_protocol(
        _draft(),
        data_certification_status=EvidenceStatus.PASS,
        sealed_at=NOW,
    )
    audit = open_locked_oos(
        sealed,
        evaluation_id="eval-1",
        replay_inputs=_inputs(sealed),
        data_certification_status=EvidenceStatus.PASS,
        attempted_at=NOW,
    )
    assert audit.state is LockedOOSOpeningState.OPENED
    evaluated = record_locked_oos_evaluation(sealed, audit, result_hash="result-hash")
    assert evaluated.seal_state is LockedOOSSealState.EVALUATED
    status = protocol_status(evaluated, data_certification_status=EvidenceStatus.PASS)
    assert status.status is EvidenceStatus.PASS
    repeated = open_locked_oos(
        evaluated,
        evaluation_id="eval-2",
        replay_inputs=_inputs(evaluated),
        data_certification_status=EvidenceStatus.PASS,
    )
    assert repeated.state is LockedOOSOpeningState.BLOCKED
    assert "LOCKED_OOS_ALREADY_EVALUATED" in repeated.blockers
    with pytest.raises(ValueError, match="POST_HOC"):
        record_locked_oos_evaluation(sealed, audit, result_hash="result-hash", post_hoc_tuning=True)


def test_replay_identity_rejects_dataset_model_feature_config_and_cost_changes() -> None:
    manifest = _draft()
    mismatched = _inputs(manifest)
    mismatched.update(
        {
            "dataset_hash": "changed",
            "model_hash": "changed",
            "feature_schema_hash": "changed",
            "config_hash": "changed",
            "transaction_costs_bps": 11.0,
            "dataset_snapshot_id": "changed",
        }
    )
    blockers = validate_replay_identity(manifest, mismatched)
    assert "LOCKED_OOS_DATASET_HASH_MISMATCH" in blockers
    assert "LOCKED_OOS_MODEL_HASH_MISMATCH" in blockers
    assert "LOCKED_OOS_FEATURE_SCHEMA_HASH_MISMATCH" in blockers
    assert "LOCKED_OOS_CONFIG_HASH_MISMATCH" in blockers
    assert "LOCKED_OOS_TRANSACTION_COSTS_BPS_MISMATCH" in blockers
    assert "LOCKED_OOS_DATASET_SNAPSHOT_ID_MISMATCH" in blockers


def test_legacy_unbound_protocol_cannot_be_sealed_or_relabelled_as_locked_oos() -> None:
    manifest = _draft_with(dataset_snapshot_id="LEGACY_UNBOUND")
    blockers = validate_protocol_manifest(manifest)
    assert "LOCKED_OOS_DATASET_SNAPSHOT_ID_UNBOUND" in blockers
    with pytest.raises(ValueError, match="cannot seal invalid"):
        seal_locked_oos_protocol(manifest, data_certification_status=EvidenceStatus.PASS)


def test_persisted_sealed_manifest_is_write_once(tmp_path: Path) -> None:
    sealed = seal_locked_oos_protocol(
        _draft(),
        data_certification_status=EvidenceStatus.PASS,
        sealed_at=NOW,
    )
    path = tmp_path / "locked-oos.json"
    persist_locked_oos_protocol(path, sealed)
    assert load_locked_oos_protocol(path).manifest_hash == sealed.manifest_hash
    with pytest.raises(FileExistsError):
        persist_locked_oos_protocol(path, sealed)


def test_opening_audit_is_persisted_write_once_even_when_blocked(tmp_path: Path) -> None:
    sealed = seal_locked_oos_protocol(
        _draft(),
        data_certification_status=EvidenceStatus.PASS,
        sealed_at=NOW,
    )
    audit = open_locked_oos(
        sealed,
        evaluation_id="blocked-audit",
        replay_inputs=_inputs(sealed),
        data_certification_status=EvidenceStatus.BLOCKED_DATA_QUALITY,
        attempted_at=NOW,
    )
    path = tmp_path / "opening-audit.json"
    persist_locked_oos_opening_audit(path, audit)
    assert "LOCKED_OOS_DATA_CERTIFICATION_REQUIRED" in path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        persist_locked_oos_opening_audit(path, audit)


def test_current_protocol_status_is_blocked_without_data_or_manifest() -> None:
    status = protocol_status(None, data_certification_status=EvidenceStatus.BLOCKED_DATA_QUALITY)
    assert status.status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert not status.promotion_allowed
    assert "CERTIFIED_DATA_FOUNDATION_REQUIRED" in status.blockers
    assert "LOCKED_OOS_MANIFEST_MISSING" in status.blockers
