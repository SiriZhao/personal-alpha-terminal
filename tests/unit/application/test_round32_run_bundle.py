"""ROUND32: immutable production run bundle / replay / anti-leakage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.application.run_bundle import (
    REPLAY_NOT_POSSIBLE,
    REPLAY_PASS,
    ContentAddressedBlobStore,
    RunBundleStore,
    deserialize_alpha_signals,
    deserialize_authorization,
    deserialize_risk_budget,
    deserialize_risk_state,
    finalize_run_bundle,
    replay_run_bundle,
    serialize_alpha_signals,
    serialize_authorization,
    serialize_risk_budget,
    serialize_risk_state,
    stage_run_bundle,
    verify_bundle_integrity,
)
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    PortfolioRiskState,
    RiskBudget,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
)
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

_FIXTURE_SYMBOLS = ("A", "B", "C", "D")
_FIXTURE_NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)
_RUN_ID = "daily-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_DECISION_ID = "decision-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_LEGACY_RUN_ID = "daily-2420c68452d142298e6b42482341391f"


def _fixture_authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        datetime(2025, 11, 24, tzinfo=UTC).date(),
        _FIXTURE_NOW.date(),
        _FIXTURE_NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "fixture-adapter",
        ("source-a", "source-b"),
        _FIXTURE_NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        _FIXTURE_NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=_FIXTURE_NOW)


def _fixture_inputs() -> DailyQuantInput:
    rng = np.random.default_rng(11)
    market = rng.normal(0.0003, 0.009, 180)
    returns = pd.DataFrame(
        {
            symbol: 0.75 * market + rng.normal(0.0003, 0.006, 180)
            for symbol in _FIXTURE_SYMBOLS
        },
        index=pd.bdate_range("2025-11-24", periods=180),
    )
    benchmark = pd.Series(market, index=returns.index)
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            3_000_000 + index * 1_000_000,
            0.0,
            50_000_000 + index * 5_000_000,
        )
        for index, symbol in enumerate(_FIXTURE_SYMBOLS)
    )
    signals = tuple(
        AlphaSignal(
            symbol,
            _FIXTURE_NOW - timedelta(hours=1),
            "medium_term_momentum",
            0.01 + index * 0.001,
            20,
            1.0,
            0.8,
            0.8,
            True,
            200,
            0.8,
            0.7,
            40.0,
            _FIXTURE_NOW + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        for index, symbol in enumerate(_FIXTURE_SYMBOLS)
    )
    return DailyQuantInput(
        _fixture_authorization(),
        _FIXTURE_NOW,
        signals,
        returns,
        benchmark,
        metadata,
        {},
        1_000_000,
        PortfolioRiskState(-0.01, 0.12, 0.0, 0.0, 0.25, 0.25),
        None,
        True,
        "universe-v1",
        "CERTIFIED",
    )


def _fixture_constraints() -> PortfolioConstraints:
    return PortfolioConstraints(model_validation_id="locked-oos-fixture")


def _fixture_cost_model() -> TransactionCostModel:
    return TransactionCostModel(
        TransactionCostConfig(
            commission_bps=0.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            impact_coefficient_bps=0.0,
            minimum_fee=0.0,
            regulatory_fee_bps=0.0,
            maximum_adv_participation=1.0,
        )
    )


def _fixture_stress_config() -> StressRiskConfig:
    return StressRiskConfig(
        production_validated=True,
        validation_id="locked-oos-stress-fixture",
        maximum_cvar_loss=1.0,
        maximum_liquidation_days=10.0,
        maximum_correlation_spike_loss=1.0,
        maximum_gap_loss=1.0,
        maximum_stressed_volatility=5.0,
        maximum_benchmark_crash_loss=1.0,
        maximum_single_name_loss=1.0,
        maximum_sector_loss=1.0,
        warning_ratio=0.99,
    )


def _pipeline_output(tmp_path: Path):
    """Run the deterministic pipeline on the fixture and return its pieces."""

    constraints = _fixture_constraints()
    cost_model = _fixture_cost_model()
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(
            constraints=constraints,
            cost_model=cost_model,
            operational_mode=False,
        ),
        cost_model=cost_model,
        stress_config=_fixture_stress_config(),
        operational_mode=False,
    )
    inputs = _fixture_inputs()
    output = pipeline.run(inputs)
    assert output.status.value == "READY"
    assert output.target is not None
    assert output.risk is not None
    assert output.risk_budget is not None
    store = RunBundleStore(tmp_path / "evidence-bundles")
    receipt = stage_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_id=_DECISION_ID,
        created_at=_FIXTURE_NOW,
        analysis_date="2026-08-14",
        decision_cutoff=inputs.decision_time,
        trade_date="2026-08-17",
        inputs=inputs,
        risk=output.risk,
        target=output.target,
        constraints=constraints,
        cost_model=cost_model,
        risk_budget=output.risk_budget,
        operational_mode=False,
    )
    return store, receipt, inputs, output, constraints, cost_model


def test_blob_store_roundtrip_dedupe_and_immutability(tmp_path: Path) -> None:
    store = ContentAddressedBlobStore(tmp_path / "blobs")
    first = store.put_bytes(b"hello-bundle")
    second = store.put_bytes(b"hello-bundle")
    assert first == second
    assert store.read_bytes(first) == b"hello-bundle"
    assert store.verify(first)
    assert len(list(store.root.iterdir())) == 1
    array = np.arange(12.0).reshape(3, 4)
    digest = store.put_array(array)
    restored = store.read_array(digest)
    np.testing.assert_array_equal(restored, array)
    payload = {"z": 1, "a": [1, 2]}
    digest_json = store.put_json(payload)
    assert store.read_json(digest_json) == payload
    # Tampering is detected by the integrity check.
    target = store.root / first
    target.write_bytes(b"corrupted")
    assert not store.verify(first)


def test_serialization_roundtrips_are_symmetric() -> None:
    authorization = _fixture_authorization()
    rebuilt = deserialize_authorization(serialize_authorization(authorization))
    assert rebuilt.authorization_id == authorization.authorization_id
    assert rebuilt.request.purpose is authorization.request.purpose
    assert rebuilt.request.decision_time == authorization.request.decision_time
    assert rebuilt.decision.status is authorization.decision.status
    assert rebuilt.evidence is not None
    assert rebuilt.evidence.data_version == "data-v1"

    signals = _fixture_inputs().alpha_signals
    rebuilt_signals = deserialize_alpha_signals(serialize_alpha_signals(signals))
    assert len(rebuilt_signals) == len(signals)
    assert rebuilt_signals[0].symbol == "A"
    assert rebuilt_signals[0].expected_excess_return == pytest.approx(0.01)
    assert rebuilt_signals[0].validation_status is AlphaValidationStatus.PRODUCTION_APPROVED

    state = PortfolioRiskState(-0.02, 0.15, 0.9, 0.05, 0.3, 0.25)
    rebuilt_state = deserialize_risk_state(serialize_risk_state(state))
    assert rebuilt_state.current_drawdown == pytest.approx(-0.02)
    assert rebuilt_state.correlation_status.value == "VALID"

    budget = RiskBudget(0.8, 0.9, 0.95, True, ("fixture-reason",))
    rebuilt_budget = deserialize_risk_budget(serialize_risk_budget(budget))
    assert rebuilt_budget.gross_exposure_multiplier == pytest.approx(0.8)
    assert rebuilt_budget.allow_new_risk is True
    assert rebuilt_budget.reasons == ("fixture-reason",)


def test_stage_finalize_replay_passes_with_tolerance(tmp_path: Path) -> None:
    store, receipt, inputs, output, constraints, cost_model = _pipeline_output(tmp_path)
    assert receipt["status"] == "STAGED"
    manifest = store.load_manifest(_RUN_ID)
    assert manifest["status"] == "STAGED"
    assert len(manifest["blob_digests"]) >= 10

    sealed = finalize_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_manifest={"semantic_hash": "f" * 64},
    )
    assert sealed["status"] == "SEALED"
    assert sealed["decision_manifest_semantic_hash"] == "f" * 64

    integrity = verify_bundle_integrity(store=store, run_id=_RUN_ID)
    assert integrity["status"] == "INTEGRITY_PASS"
    assert integrity["verified_blobs"] == len(manifest["blob_digests"])

    report = replay_run_bundle(store=store, run_id=_RUN_ID)
    assert report.status == REPLAY_PASS
    metrics = {item.name: item.passed for item in report.metrics}
    assert all(metrics.values()), metrics
    assert report.decision_manifest_semantic_hash == "f" * 64
    assert report.replay_occurrence_id.startswith("replay-")


def test_replay_is_idempotent_and_never_writes_predictions(tmp_path: Path) -> None:
    store, _, _, _, _, _ = _pipeline_output(tmp_path)
    finalize_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_manifest={"semantic_hash": "f" * 64},
    )
    first = replay_run_bundle(store=store, run_id=_RUN_ID)
    second = replay_run_bundle(store=store, run_id=_RUN_ID)
    assert first.status == REPLAY_PASS
    assert second.status == REPLAY_PASS
    assert first.replay_occurrence_id != second.replay_occurrence_id
    occurrences = store.occurrences_path(_RUN_ID).read_text(encoding="utf-8").strip().splitlines()
    assert len(occurrences) == 2
    for line in occurrences:
        row = json.loads(line)
        assert row["schema_version"] == "replay-occurrence-v1"
        assert row["run_id"] == _RUN_ID
        assert row["status"] == REPLAY_PASS
    # Replay must never append predictions or outcomes anywhere.
    assert not (tmp_path / "evidence-bundles" / _RUN_ID / "predictions.jsonl").exists()
    assert not (tmp_path / "evidence-bundles" / _RUN_ID / "outcomes.jsonl").exists()


def test_replay_missing_blob_is_not_possible(tmp_path: Path) -> None:
    store, _, _, _, _, _ = _pipeline_output(tmp_path)
    finalize_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_manifest={"semantic_hash": "f" * 64},
    )
    manifest = store.load_manifest(_RUN_ID)
    covariance_digest = str(manifest["blob_digests"]["covariance"])
    (store.blobs.root / covariance_digest).unlink()
    report = replay_run_bundle(store=store, run_id=_RUN_ID)
    assert report.status == REPLAY_NOT_POSSIBLE
    assert "covariance" in report.detail or "original input" in report.detail


def test_finalize_is_immutable_and_idempotent(tmp_path: Path) -> None:
    store, _, _, _, _, _ = _pipeline_output(tmp_path)
    first = finalize_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_manifest={"semantic_hash": "f" * 64},
    )
    second = finalize_run_bundle(
        store=store,
        run_id=_RUN_ID,
        decision_manifest={"semantic_hash": "f" * 64},
    )
    assert second["status"] == "ALREADY_SEALED"
    manifest = store.load_manifest(_RUN_ID)
    assert manifest["decision_manifest_semantic_hash"] == "f" * 64
    assert manifest["bundle_hash"] == first["bundle_hash"]


def test_legacy_round27_run_has_no_bundle(tmp_path: Path) -> None:
    """ROUND27-era runs predate the bundle; their status must be explicit."""

    store = RunBundleStore(tmp_path / "evidence-bundles")
    with pytest.raises(FileNotFoundError):
        store.load_manifest(_LEGACY_RUN_ID)
    # Classify the legacy run explicitly: LEGACY_INPUT_INCOMPLETE, never a fake replay.
    assert _LEGACY_RUN_ID not in store.list_run_ids()


def test_replay_rejects_unsealed_bundle(tmp_path: Path) -> None:
    store, _, _, _, _, _ = _pipeline_output(tmp_path)
    report = replay_run_bundle(store=store, run_id=_RUN_ID)
    assert report.status == "REPLAY_NOT_POSSIBLE_BUNDLE_NOT_SEALED"
