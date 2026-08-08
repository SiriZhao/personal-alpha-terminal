from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from personal_alpha_terminal.decision_engine import (
    DecisionAction,
    DecisionBatchStatus,
    DecisionCandidate,
    DecisionEngine,
)
from personal_alpha_terminal.research import (
    GateDecision,
    GateStatus,
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

NOW = datetime(2026, 8, 1, 1, tzinfo=UTC)


def _request() -> ResearchDataRequest:
    return ResearchDataRequest(
        purpose=ResearchPurpose.PORTFOLIO_DECISION,
        market="US",
        asset_type="stock",
        start_date=date(2010, 1, 1),
        end_date=date(2026, 7, 31),
        decision_time=NOW,
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="us-2026-07-31",
    )


def _authorization() -> ResearchDataAuthorization:
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="licensed_primary",
        provider="primary_adapter",
        source_ids=("quality:42", "snapshot:99"),
        latest_available_time=NOW - timedelta(hours=2),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="us-2026-07-31",
        universe_available_time=NOW - timedelta(hours=3),
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
    return ResearchDataGate().authorize(_request(), evidence, evaluated_at=NOW)


def _candidate(**changes: object) -> DecisionCandidate:
    base = DecisionCandidate(
        stock_id=1,
        ticker="AAPL",
        permanent_security_id="FIGI-AAPL",
        current_weight=0.05,
        optimized_target_weight=0.10,
        reference_price=200.0,
        factor_score=80.0,
        regime_score=20.0,
        risk_score=30.0,
        probability_lift=0.08,
        probability_sample_size=120,
        probability_calibrated=True,
        oos_validated=True,
        as_of_time=NOW - timedelta(hours=1),
        source_ids=("factor:1", "conditional:1"),
        rationale=("quality-momentum rank passed",),
        risk_factors=("equity loss remains possible",),
        maximum_shares=100,
        alpha_validation_status="PRODUCTION_APPROVED",
        expected_excess_return=0.015,
        alpha_confidence=0.82,
        alpha_pit_valid=True,
        alpha_model_version="approved-alpha-v1",
        alpha_data_version="us-frozen-v1",
        portfolio_validation_status="PRODUCTION_APPROVED",
        portfolio_model_version="risk-budget-v1",
        risk_constraints_applied=True,
    )
    return replace(base, **changes)


def test_approved_evidence_generates_explainable_next_session_action() -> None:
    result = DecisionEngine().generate(
        authorization=_authorization(),
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=(_candidate(),),
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )

    assert result.status is DecisionBatchStatus.GENERATED
    recommendation = result.recommendations[0]
    assert recommendation.action is DecisionAction.BUY
    assert recommendation.suggested_shares == 25
    assert recommendation.earliest_execution_time > result.as_of_time
    assert recommendation.evidence_grade == "PRODUCTION_APPROVED"
    assert set(recommendation.component_scores) == {
        "expected_excess_return",
        "alpha_confidence",
        "risk_score",
        "portfolio_target_delta",
    }


def test_small_sample_stale_or_unvalidated_evidence_generates_no_decision() -> None:
    candidates = (
        _candidate(probability_sample_size=29),
        _candidate(stock_id=2, permanent_security_id="FIGI-2", oos_validated=False),
        _candidate(
            stock_id=3,
            permanent_security_id="FIGI-3",
            as_of_time=NOW - timedelta(days=4),
        ),
    )
    result = DecisionEngine().generate(
        authorization=_authorization(),
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=candidates,
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )

    assert result.status is DecisionBatchStatus.NO_DECISION
    assert not result.recommendations
    assert any("sample" in item for item in result.blockers)
    assert any("out-of-sample" in item for item in result.blockers)
    assert any("stale" in item for item in result.blockers)


def test_high_risk_veto_can_only_create_watch_not_a_position_increase() -> None:
    result = DecisionEngine().generate(
        authorization=_authorization(),
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=(_candidate(risk_score=90),),
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )

    recommendation = result.recommendations[0]
    assert recommendation.action is DecisionAction.WATCH
    assert recommendation.target_weight == recommendation.current_weight
    assert recommendation.suggested_shares == 0


def test_nonapproved_authorization_fails_closed() -> None:
    request = _request()
    decision = GateDecision(
        status=GateStatus.BLOCKED,
        purpose=request.purpose,
        blockers=("data certification missing",),
        warnings=(),
        allowed_actions=("diagnostics",),
        evidence_fingerprint="blocked",
        evaluated_at=NOW,
    )
    authorization = ResearchDataAuthorization(decision, request, NOW, "blocked-auth")

    result = DecisionEngine().generate(
        authorization=authorization,
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=(_candidate(),),
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )

    assert result.status is DecisionBatchStatus.BLOCKED
    assert not result.recommendations


def test_tested_but_not_production_approved_alpha_cannot_generate_action() -> None:
    result = DecisionEngine().generate(
        authorization=_authorization(),
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=(_candidate(alpha_validation_status="TESTED"),),
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )
    assert result.status is DecisionBatchStatus.NO_DECISION
    assert any("PRODUCTION_APPROVED" in item for item in result.blockers)


def test_unvalidated_portfolio_target_cannot_generate_action() -> None:
    result = DecisionEngine().generate(
        authorization=_authorization(),
        portfolio_id=1,
        portfolio_value=100_000,
        candidates=(_candidate(portfolio_validation_status="TESTED"),),
        generated_at=NOW,
        earliest_execution_time=NOW + timedelta(hours=14),
    )
    assert result.status is DecisionBatchStatus.NO_DECISION
    assert any("portfolio construction" in item for item in result.blockers)
