"""ROUND76 production-parity replay contracts."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from personal_alpha_terminal.research.certified_data import current_data_certification
from personal_alpha_terminal.research.data_evidence import EvidenceStatus
from personal_alpha_terminal.research.locked_oos_protocol import (
    create_locked_oos_protocol,
    seal_locked_oos_protocol,
)
from personal_alpha_terminal.research.production_parity_replay import (
    HistoricalLLMEvidence,
    ProductionParityReplayEngine,
    ReplayAccounting,
    ReplayDecision,
    ReplayEvidenceClass,
    ReplayExecutionAssumption,
    ReplayOutcomeState,
    ReplayPortfolioState,
    ReplayVariant,
    persist_replay_artifact,
    validate_synchronized_variants,
)

NOW = datetime(2024, 1, 3, 20, tzinfo=UTC)


def _certified_data():
    from personal_alpha_terminal.research.certified_data import (
        CertifiedDataResult,
        CertifiedEvidenceClass,
        EvidenceClassCertification,
    )

    return CertifiedDataResult(
        overall_status=EvidenceStatus.PASS,
        package_hash="certified-package",
        classes=tuple(
            EvidenceClassCertification(item, EvidenceStatus.PASS, 1, (), "contract", "scope")
            for item in CertifiedEvidenceClass
        ),
        blockers=(),
        warnings=(),
        promotion_allowed=True,
    )


def _sealed_manifest():
    draft = create_locked_oos_protocol(
        dataset_id="data", dataset_hash="certified-package", dataset_vintage="v1", feature_schema_hash="features",
        model_id="CURRENT_PRODUCTION_QUANT", model_version="v1", model_hash="model", config_hash="config",
        train_start=date(2018, 1, 1), train_end=date(2020, 12, 31), validation_start=date(2021, 2, 1), validation_end=date(2021, 12, 31),
        locked_oos_start=date(2022, 2, 1), locked_oos_end=date(2023, 12, 31), purge_sessions=5, embargo_sessions=1, label_horizon_sessions=5,
        universe_semantics="historical permanent-id membership", benchmark_id="BENCHMARK:SPY", benchmark_semantics="POINT_IN_TIME_TOTAL_RETURN",
        transaction_costs_bps=10.0, slippage_bps=5.0, execution_price_policy="next legal executable open",
        calendar_semantics="XNYS", corporate_action_semantics="PIT actions", created_at=NOW,
    )
    return seal_locked_oos_protocol(draft, data_certification_status=EvidenceStatus.PASS, sealed_at=NOW)


def _decision(*, variant: ReplayVariant = ReplayVariant.PURE_QUANT, llm=(), probability: str | None = None):
    return ReplayDecision(
        decision_id="d-1", decision_time=NOW, evidence_cutoff=NOW - timedelta(minutes=1),
        universe_id="US-HIST", universe_hash="universe-hash", model_hash="model", config_hash="config",
        requested_variant=variant,
        portfolio_before=ReplayPortfolioState(0.2, {"AAA": 0.8}, {"AAA": 0.8}, "ledger-before"),
        target_weights={"AAA": 0.8},
        execution=ReplayExecutionAssumption(date(2024, 1, 4), NOW + timedelta(days=1), 101.0, 1_000.0, "TRADABLE", date(2024, 1, 4), "next legal executable open"),
        transaction_cost_bps=10.0, slippage_bps=5.0,
        security_identity_valid=True, pit_universe_member=True, prices_actions_visible=True, fundamentals_filings_visible=True, news_events_visible=True,
        evidence_hashes=("price", "identity", "benchmark"), probability_evidence_hash=probability, llm_evidence=llm,
    )


def _simulate(decision: ReplayDecision, variant: ReplayVariant) -> ReplayAccounting:
    assert decision.requested_variant is not None
    assert variant in ReplayVariant
    return ReplayAccounting(
        cash=0.2, target_weights=decision.target_weights, actual_weights=decision.target_weights, turnover=0.1,
        transaction_cost=0.001, slippage_cost=0.0005, realized_pnl=0.0, unrealized_pnl=0.01,
        portfolio_return=0.01, benchmark_return=0.008, concentration=0.8, gross_exposure=0.8,
        risk_constraints_satisfied=True, ledger_hash="ledger-after",
    )


def test_current_data_gate_blocks_economic_replay_before_simulator_runs() -> None:
    called = False

    def simulator(decision: ReplayDecision, variant: ReplayVariant) -> ReplayAccounting:
        nonlocal called
        called = True
        return _simulate(decision, variant)

    result = ProductionParityReplayEngine().run(
        (_decision(),), data_certification=current_data_certification(), locked_oos_manifest=None, simulate_execution=simulator
    )
    assert result.status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert not result.artifacts
    assert not called


def test_valid_fixture_replay_persists_complete_immutable_artifact(tmp_path: Path) -> None:
    result = ProductionParityReplayEngine().run(
        (_decision(),), data_certification=_certified_data(), locked_oos_manifest=_sealed_manifest(), simulate_execution=_simulate,
        evidence_class=ReplayEvidenceClass.FIXTURE_SUPPLEMENTARY,
    )
    assert result.status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert "CERTIFIED_HISTORICAL_REPLAY_ARTIFACTS_REQUIRED" in result.blockers
    artifact = result.artifacts[0]
    assert artifact.accounting is not None
    assert artifact.outcome_state is ReplayOutcomeState.SIMULATED
    assert artifact.evidence_class is ReplayEvidenceClass.FIXTURE_SUPPLEMENTARY
    path = tmp_path / "artifact.json"
    persist_replay_artifact(path, artifact)
    with pytest.raises(FileExistsError):
        persist_replay_artifact(path, artifact)


def test_future_llm_evidence_blocks_hindsight_and_uses_quant_fail_soft() -> None:
    future = HistoricalLLMEvidence("source", "news-1", NOW + timedelta(seconds=1), "provider URL hash")
    decision = _decision(variant=ReplayVariant.QUANT_PLUS_LLM, llm=(future,))
    result = ProductionParityReplayEngine().run(
        (decision,), data_certification=_certified_data(), locked_oos_manifest=_sealed_manifest(), simulate_execution=_simulate
    )
    artifact = result.artifacts[0]
    assert artifact.outcome_state is ReplayOutcomeState.BLOCKED
    assert "LLM_EVIDENCE_AFTER_DECISION_CUTOFF" in artifact.blockers


def test_missing_historical_llm_evidence_falls_back_to_quant_without_hindsight() -> None:
    decision = _decision(variant=ReplayVariant.QUANT_PLUS_LLM)
    result = ProductionParityReplayEngine().run(
        (decision,), data_certification=_certified_data(), locked_oos_manifest=_sealed_manifest(), simulate_execution=_simulate
    )
    artifact = result.artifacts[0]
    assert artifact.outcome_state is ReplayOutcomeState.FALLBACK_PURE_QUANT
    assert artifact.effective_variant is ReplayVariant.PURE_QUANT
    assert "LLM_HISTORICAL_EVIDENCE_MISSING_QUANT_FAIL_SOFT" in artifact.blockers


def test_same_session_execution_and_invalid_tradability_are_rejected() -> None:
    with pytest.raises(ValueError, match="next legal session"):
        _decision_with_execution(date(2024, 1, 3), NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="TRADABLE"):
        ReplayExecutionAssumption(date(2024, 1, 4), NOW + timedelta(days=1), 100, 1_000, "HALTED", date(2024, 1, 4), "next open")


def _decision_with_execution(session: date, execution_time: datetime) -> ReplayDecision:
    base = _decision()
    return ReplayDecision(
        decision_id=base.decision_id, decision_time=base.decision_time, evidence_cutoff=base.evidence_cutoff,
        universe_id=base.universe_id, universe_hash=base.universe_hash, model_hash=base.model_hash, config_hash=base.config_hash,
        requested_variant=base.requested_variant, portfolio_before=base.portfolio_before, target_weights=base.target_weights,
        execution=ReplayExecutionAssumption(session, execution_time, 100, 1_000, "TRADABLE", session, "next open"),
        transaction_cost_bps=base.transaction_cost_bps, slippage_bps=base.slippage_bps,
        security_identity_valid=True, pit_universe_member=True, prices_actions_visible=True, fundamentals_filings_visible=True, news_events_visible=True,
        evidence_hashes=base.evidence_hashes,
    )


def test_synchronized_variants_reject_cost_or_universe_mismatch() -> None:
    pure = ProductionParityReplayEngine().run(
        (_decision(),), data_certification=_certified_data(), locked_oos_manifest=_sealed_manifest(), simulate_execution=_simulate
    ).artifacts[0]
    changed = ProductionParityReplayEngine().run(
        (_decision(variant=ReplayVariant.ALPHA_ENGINE3_CHALLENGER),), data_certification=_certified_data(), locked_oos_manifest=_sealed_manifest(), simulate_execution=_simulate
    ).artifacts[0]
    altered = replace(changed, transaction_cost_bps=11.0)
    assert validate_synchronized_variants((pure, altered))


def test_replay_rejects_sealed_dataset_model_config_and_cost_identity_mismatch() -> None:
    decision = _decision()
    mismatched = ReplayDecision(
        decision_id=decision.decision_id,
        decision_time=decision.decision_time,
        evidence_cutoff=decision.evidence_cutoff,
        universe_id=decision.universe_id,
        universe_hash=decision.universe_hash,
        model_hash="different-model",
        config_hash="different-config",
        requested_variant=decision.requested_variant,
        portfolio_before=decision.portfolio_before,
        target_weights=decision.target_weights,
        execution=decision.execution,
        transaction_cost_bps=11.0,
        slippage_bps=6.0,
        security_identity_valid=True,
        pit_universe_member=True,
        prices_actions_visible=True,
        fundamentals_filings_visible=True,
        news_events_visible=True,
        evidence_hashes=decision.evidence_hashes,
    )
    result = ProductionParityReplayEngine().run(
        (mismatched,),
        data_certification=_certified_data(),
        locked_oos_manifest=_sealed_manifest(),
        simulate_execution=_simulate,
    )
    assert result.status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert "LOCKED_OOS_MODEL_HASH_MISMATCH" in result.artifacts[0].blockers
    assert "LOCKED_OOS_CONFIG_HASH_MISMATCH" in result.artifacts[0].blockers
    assert "LOCKED_OOS_TRANSACTION_COSTS_MISMATCH" in result.artifacts[0].blockers
    assert "LOCKED_OOS_SLIPPAGE_MISMATCH" in result.artifacts[0].blockers
