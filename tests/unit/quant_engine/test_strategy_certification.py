from dataclasses import replace
from datetime import UTC, date, datetime

from personal_alpha_terminal.quant_engine.strategy_certification import (
    StrategyApprovalIdentity,
    StrategyCertificationEvidence,
    StrategyCertificationStatus,
    approval_matches,
    certify_strategy,
    persist_approval_artifact,
)


def _evidence() -> StrategyCertificationEvidence:
    return StrategyCertificationEvidence(
        strategy_version="strategy:1", parameter_hash="params", data_version="pit-history-1",
        universe_version="universe-history-1", research_manifest_id="manifest-1",
        research_manifest_hash="manifest-hash-1", research_data_hash="data-hash-1",
        candidate_manifest_hash="candidate-hash-1", locked_oos_definition_hash="oos-hash-1",
        data_certification_state="CERTIFIED", train_end=date(2023, 12, 29),
        validation_end=date(2024, 12, 31), oos_start=date(2025, 1, 2),
        oos_end=date(2026, 6, 30), oos_sessions=375, walk_forward_folds=6,
        pit_valid=True, survivorship_controlled=True, corporate_actions_valid=True,
        future_rows=0, benchmark_same_pit_convention=True, net_sharpe=0.8,
        net_return=0.24, spy_net_return=0.16, qqq_net_return=0.18,
        max_drawdown=0.14, annual_turnover=2.0, max_position_weight=0.10,
        stability_score=0.75, commission_bps=1.0, spread_bps=2.0,
        slippage_bps=2.0, impact_bps=1.0,
    )


def test_complete_locked_oos_evidence_can_be_approved_reproducibly() -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    first = certify_strategy(_evidence(), created_at=now)
    second = certify_strategy(_evidence(), created_at=now)
    assert first.status is StrategyCertificationStatus.PRODUCTION_APPROVED
    assert first.artifact_id == second.artifact_id


def test_costs_and_benchmark_pit_are_mandatory() -> None:
    artifact = certify_strategy(
        replace(_evidence(), slippage_bps=0, benchmark_same_pit_convention=False)
    )
    assert artifact.status is StrategyCertificationStatus.REJECTED
    assert "TRANSACTION_COST_COMPONENT_MISSING" in artifact.blockers
    assert "BENCHMARK_PIT_CONVENTION_MISMATCH" in artifact.blockers


def test_future_rows_and_survivorship_failure_close_gate() -> None:
    artifact = certify_strategy(replace(_evidence(), future_rows=1, survivorship_controlled=False))
    assert artifact.status is StrategyCertificationStatus.NOT_CERTIFIABLE
    assert "PIT_OR_FUTURE_ROW_FAILURE" in artifact.blockers
    assert "SURVIVORSHIP_NOT_CONTROLLED" in artifact.blockers


def test_incomplete_survivorship_evidence_is_not_certifiable(tmp_path) -> None:
    artifact = certify_strategy(
        replace(
            _evidence(),
            data_certification_state="NOT_CERTIFIABLE",
            research_data_hash=None,
            train_end=None,
            validation_end=None,
            oos_start=None,
            oos_end=None,
            oos_sessions=0,
            walk_forward_folds=0,
            net_sharpe=None,
            net_return=None,
            spy_net_return=None,
            qqq_net_return=None,
            max_drawdown=None,
            annual_turnover=None,
            max_position_weight=None,
            stability_score=None,
        )
    )
    assert artifact.status is StrategyCertificationStatus.NOT_CERTIFIABLE
    assert "SURVIVORSHIP_DATA_INSUFFICIENT" in artifact.blockers
    try:
        persist_approval_artifact(artifact, tmp_path)
    except ValueError as error:
        assert "cannot produce an approval" in str(error)
    else:
        raise AssertionError("failed certification produced an approval artifact")


def test_approval_requires_exact_strategy_parameter_and_research_data_identity() -> None:
    artifact = certify_strategy(_evidence(), created_at=datetime(2026, 8, 11, tzinfo=UTC))
    identity = StrategyApprovalIdentity(
        "strategy:1", "params", "pit-history-1", "data-hash-1", "manifest-hash-1"
    )
    assert approval_matches(artifact, identity)
    assert not approval_matches(artifact, replace(identity, parameter_hash="params-v2"))
    assert not approval_matches(artifact, replace(identity, research_data_hash="changed"))


def test_certified_test_fixture_cannot_create_strategy_approval() -> None:
    artifact = certify_strategy(replace(_evidence(), research_data_use_scope="TEST_FIXTURE"))
    assert artifact.status is StrategyCertificationStatus.NOT_CERTIFIABLE
    assert "RESEARCH_DATA_NOT_PRODUCTION_ELIGIBLE" in artifact.blockers
