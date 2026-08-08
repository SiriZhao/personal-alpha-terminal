from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.research import (
    GateStatus,
    ResearchDataBlockedError,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


def _request(purpose: ResearchPurpose = ResearchPurpose.REBALANCE) -> ResearchDataRequest:
    return ResearchDataRequest(
        purpose=purpose,
        market="US",
        asset_type="stock",
        start_date=date(2010, 1, 1),
        end_date=date(2026, 7, 31),
        decision_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="us-2026-07-31",
    )


def _evidence() -> ResearchDataEvidence:
    return ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="licensed_primary",
        provider="primary_adapter",
        source_ids=("quality:42", "snapshot:99"),
        latest_available_time=datetime(2026, 7, 31, 23, tzinfo=UTC),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="us-2026-07-31",
        universe_available_time=datetime(2026, 7, 31, 22, tzinfo=UTC),
        corporate_actions_complete=True,
        trading_calendar_complete=True,
        missing_rate=0.001,
        anomaly_rate=0.0001,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.005,
        data_version="us-frozen-v1",
        allow_backtest=True,
        allow_display=True,
        allow_portfolio_decision=True,
        dual_source_verified=True,
    )


def test_portfolio_decision_requires_every_production_control() -> None:
    decision = ResearchDataGate().evaluate(
        _request(),
        _evidence(),
        evaluated_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
    )
    assert decision.status is GateStatus.APPROVED
    assert decision.may_generate_positions


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("quality_status", "blocked", "quality"),
        ("source_conflict", True, "provider disagreement"),
        ("universe_snapshot_id", None, "universe snapshot"),
        ("corporate_actions_complete", False, "corporate-action"),
        ("trading_calendar_complete", False, "calendar"),
        ("dual_source_verified", False, "second-source"),
        ("allow_portfolio_decision", False, "portfolio decisions"),
    ),
)
def test_decision_gate_fails_closed(field: str, value: object, message: str) -> None:
    evidence = replace(_evidence(), **{field: value})
    decision = ResearchDataGate().evaluate(_request(), evidence)
    assert decision.status is GateStatus.BLOCKED
    assert not decision.may_rank_securities
    assert any(message in item for item in decision.blockers)


def test_display_can_be_degraded_but_never_authorizes_positions() -> None:
    request = replace(_request(ResearchPurpose.DISPLAY), universe_snapshot_id=None)
    evidence = replace(_evidence(), dual_source_verified=False)
    decision = ResearchDataGate().evaluate(request, evidence)
    assert decision.status is GateStatus.DEGRADED
    assert not decision.may_generate_positions


def test_future_available_data_and_stale_decision_are_blocked() -> None:
    request = _request()
    future = replace(
        _evidence(),
        latest_available_time=request.decision_time + timedelta(minutes=1),
    )
    with pytest.raises(ResearchDataBlockedError, match="after the decision cutoff"):
        ResearchDataGate().authorize(request, future)

    stale = replace(
        _evidence(),
        latest_available_time=request.decision_time - timedelta(days=10),
    )
    with pytest.raises(ResearchDataBlockedError, match="stale"):
        ResearchDataGate().authorize(request, stale)
