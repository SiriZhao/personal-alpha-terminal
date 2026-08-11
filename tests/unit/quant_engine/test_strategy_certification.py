from dataclasses import replace
from datetime import UTC, date, datetime

from personal_alpha_terminal.quant_engine.strategy_certification import (
    StrategyCertificationEvidence,
    certify_strategy,
)


def _evidence() -> StrategyCertificationEvidence:
    return StrategyCertificationEvidence(
        strategy_version="strategy:1", parameter_hash="params", data_version="pit-history-1",
        universe_version="universe-history-1", train_end=date(2023, 12, 29),
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
    assert first.status == "PRODUCTION_APPROVED"
    assert first.artifact_id == second.artifact_id


def test_costs_and_benchmark_pit_are_mandatory() -> None:
    artifact = certify_strategy(
        replace(_evidence(), slippage_bps=0, benchmark_same_pit_convention=False)
    )
    assert artifact.status == "BLOCKED"
    assert "TRANSACTION_COST_COMPONENT_MISSING" in artifact.blockers
    assert "BENCHMARK_PIT_CONVENTION_MISMATCH" in artifact.blockers


def test_future_rows_and_survivorship_failure_close_gate() -> None:
    artifact = certify_strategy(replace(_evidence(), future_rows=1, survivorship_controlled=False))
    assert artifact.status == "BLOCKED"
    assert "PIT_OR_FUTURE_ROW_FAILURE" in artifact.blockers
    assert "SURVIVORSHIP_NOT_CONTROLLED" in artifact.blockers
