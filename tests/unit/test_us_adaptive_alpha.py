from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.strategies.us_adaptive_alpha.allocation import allocate_assets
from personal_alpha_terminal.strategies.us_adaptive_alpha.conditional_overlay import (
    adjust_evidence_family,
    detect_probability_drift,
    estimate_conditional_evidence,
    evaluate_probability_calibration,
    remove_overlapping_observations,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.data_gate import (
    assess_sleeves,
    evaluate_data_gate,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.ensemble import build_ensemble
from personal_alpha_terminal.strategies.us_adaptive_alpha.factor_weighting import (
    compare_factor_weighting,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.momentum_crash import (
    evaluate_momentum_crash_risk,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.regime_overlay import (
    decide_regime_budget,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    AllocationAsset,
    CapitalPreservationConfig,
    ConditionalEvidence,
    ConditionalOverlayConfig,
    DataGateDecision,
    DataGateInput,
    EvidenceGrade,
    FactorEvidence,
    MomentumCrashInput,
    MomentumCrashResult,
    PortfolioRiskSnapshot,
    ProbabilityCalibrationObservation,
    RegimeBudgetDecision,
    RegimeBudgetInput,
    ResearchCapabilities,
    ResearchStage,
    ReturnObservation,
    SleeveSignal,
    StageEvidence,
)
from personal_alpha_terminal.strategies.us_adaptive_alpha.stage_gate import assess_stage_gate


def _gate(*, passed: bool = True) -> DataGateDecision:
    return evaluate_data_gate(
        DataGateInput(
            market="US",
            quality_status="passed" if passed else "blocked",
            sample_count=120 if passed else 0,
            security_master_ready=passed,
            point_in_time_universe_ready=passed,
            trading_calendar_ready=passed,
            corporate_actions_ready=passed,
            point_in_time_total_return_ready=passed,
            as_of_time=datetime(2026, 7, 31, tzinfo=UTC),
            source_ids=("quality:1",),
        )
    )


def _observations(
    prefix: str,
    returns: list[float],
    *,
    start: date = date(2026, 1, 1),
    oos: bool = True,
) -> tuple[ReturnObservation, ...]:
    return tuple(
        ReturnObservation(
            observation_id=f"{prefix}-{index}",
            event_date=start + timedelta(days=index * 2),
            horizon_end_date=start + timedelta(days=index * 2),
            forward_return=value,
            available_time=datetime.combine(
                start + timedelta(days=index * 2),
                datetime.min.time(),
                UTC,
            ),
            is_out_of_sample=oos,
        )
        for index, value in enumerate(returns)
    )


def _positive_evidence(symbol: str = "AAPL") -> ConditionalEvidence:
    return ConditionalEvidence(
        hypothesis_id=f"event->{symbol}",
        horizon_days=5,
        regime="risk_on",
        conditional_sample_size=60,
        baseline_sample_size=120,
        effective_sample_size=50,
        conditional_probability=0.70,
        baseline_probability=0.52,
        probability_lift=0.18,
        odds_ratio=2.15,
        lift_lower=0.04,
        lift_upper=0.30,
        conditional_lower=0.60,
        conditional_upper=0.79,
        average_return=0.02,
        median_return=0.015,
        tail_loss_5pct=-0.05,
        maximum_adverse_return=-0.12,
        net_expected_return=0.018,
        baseline_expected_return=0.005,
        conditional_expected_return=0.020,
        expected_return_lift=0.014,
        mean_return_lower=0.005,
        mean_return_upper=0.03,
        raw_p_value=0.02,
        fdr_q_value=0.04,
        calibration_passed=True,
        drift_passed=True,
        data_age_days=1,
        evidence_decay=0.99,
        grade=EvidenceGrade.MODERATE,
        reasons=(),
        retained_observation_ids=("1",),
    )


def _signal(
    *,
    symbol: str = "AAPL",
    grade: str = "positive",
    sector: str = "Technology",
    cluster: str = "mega-cap-tech",
    sleeve: str = "price_momentum",
) -> SleeveSignal:
    return SleeveSignal(
        sleeve_name=sleeve,
        symbol=symbol,
        signal_grade=grade,  # type: ignore[arg-type]
        requested_weight=0.05,
        evidence_score=0.75,
        sector=sector,
        correlation_cluster=cluster,
        maximum_liquidity_weight=0.10,
        data_as_of=datetime(2026, 7, 31, tzinfo=UTC),
        trace_ids=(f"signal:{symbol}",),
        rationale=("12-1 momentum",),
        failure_conditions=("trend reversal",),
        beta=1.1,
    )


def _regime() -> RegimeBudgetDecision:
    return decide_regime_budget(
        RegimeBudgetInput(
            regime="risk_on",
            calibration_status="calibrated",
            score=0.8,
            probability=0.7,
            previous_multiplier=0.8,
            confirmation_count=5,
            sessions_since_change=10,
        )
    )


def _crash() -> MomentumCrashResult:
    return evaluate_momentum_crash_risk(
        MomentumCrashInput(
            rebound_after_drawdown=0.1,
            winner_loser_beta_spread=0.1,
            return_dispersion=0.1,
            high_volatility_state=0.1,
            momentum_factor_drawdown=0.1,
        )
    )


def test_data_gate_blocks_missing_point_in_time_universe_and_source_failure() -> None:
    gate = evaluate_data_gate(
        DataGateInput(
            market="US",
            quality_status="failed",
            sample_count=120,
            security_master_ready=True,
            point_in_time_universe_ready=False,
            trading_calendar_ready=True,
            corporate_actions_ready=True,
            point_in_time_total_return_ready=True,
            source_conflict=True,
        )
    )

    assert gate.status.value == "blocked"
    assert not gate.allowed_for_research
    assert any("point-in-time universe" in item for item in gate.blockers)
    assert any("provider conflict" in item for item in gate.blockers)


def test_earnings_and_quality_sleeves_disable_without_reliable_pit_data() -> None:
    capabilities = ResearchCapabilities(pit_prices=True, benchmark_history=True)
    assessments = {item.name: item for item in assess_sleeves(_gate(), capabilities)}

    assert assessments["price_momentum"].status.value == "experimental"
    assert assessments["quality_constrained_momentum"].status.value == "disabled"
    assert assessments["post_earnings_drift"].status.value == "disabled"
    assert "no historical backfill" in assessments["quality_constrained_momentum"].reason


def test_overlap_removal_deduplicates_and_right_censors() -> None:
    known = datetime(2026, 1, 31, tzinfo=UTC)
    observations = (
        ReturnObservation("a", date(2026, 1, 1), date(2026, 1, 5), 0.02, known),
        ReturnObservation("b", date(2026, 1, 3), date(2026, 1, 7), 0.03, known),
        ReturnObservation("c", date(2026, 1, 8), date(2026, 1, 12), 0.01, known),
        ReturnObservation("d", date(2026, 1, 8), date(2026, 1, 13), 0.04, known),
        ReturnObservation("future", date(2026, 2, 1), date(2026, 2, 8), 0.05, known),
    )

    retained = remove_overlapping_observations(
        observations,
        as_of_date=date(2026, 1, 31),
        decision_time=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert [item.observation_id for item in retained] == ["a", "c"]


def test_conditional_overlay_suppresses_small_non_oos_sample() -> None:
    config = ConditionalOverlayConfig()
    evidence = estimate_conditional_evidence(
        hypothesis_id="small",
        horizon_days=5,
        regime="all",
        conditional_observations=_observations("c", [0.01] * 10, oos=False),
        baseline_observations=_observations("b", [0.0] * 40),
        as_of_date=date(2026, 4, 1),
        decision_time=datetime(2026, 4, 2, tzinfo=UTC),
        calibration_passed=False,
        drift_passed=True,
        config=config,
    )

    assert evidence.grade is EvidenceGrade.INSUFFICIENT
    assert evidence.conditional_probability is None
    assert any("minimum" in item for item in evidence.reasons)
    assert any("out-of-sample" in item for item in evidence.reasons)


def test_conditional_overlay_reports_lift_tail_and_cost_after_all_gates() -> None:
    config = ConditionalOverlayConfig(maximum_data_age_days=14)
    conditional = _observations(
        "c",
        [-0.02 if index % 8 == 0 else 0.03 for index in range(40)],
    )
    baseline = _observations("b", [0.01, -0.01] * 30, start=date(2025, 8, 1))
    evidence = estimate_conditional_evidence(
        hypothesis_id="event-aapl-5d",
        horizon_days=5,
        regime="risk_on",
        conditional_observations=conditional,
        baseline_observations=baseline,
        as_of_date=date(2026, 3, 25),
        decision_time=datetime(2026, 3, 26, tzinfo=UTC),
        calibration_passed=True,
        drift_passed=True,
        config=config,
    )

    assert evidence.conditional_probability is not None
    assert evidence.baseline_probability is not None
    assert evidence.probability_lift is not None and evidence.probability_lift > 0
    assert evidence.tail_loss_5pct is not None and evidence.tail_loss_5pct <= 0
    assert evidence.net_expected_return == pytest.approx(evidence.average_return - 0.001)
    assert evidence.baseline_expected_return is not None
    assert evidence.expected_return_lift == pytest.approx(
        evidence.average_return - evidence.baseline_expected_return - 0.001
    )
    assert evidence.odds_ratio is not None and evidence.odds_ratio > 1
    assert evidence.raw_p_value is not None


def test_fdr_family_downgrades_unadjusted_weak_evidence() -> None:
    strong = _positive_evidence("AAPL")
    weak = replace(
        strong,
        hypothesis_id="event->MSFT",
        raw_p_value=0.09,
        fdr_q_value=0.09,
    )
    adjusted = adjust_evidence_family(
        (strong, weak),
        config=ConditionalOverlayConfig(fdr_alpha=0.05),
    )

    assert all(item.fdr_q_value is not None for item in adjusted)
    assert adjusted[1].grade is EvidenceGrade.LOW


def test_probability_calibration_and_drift_gates() -> None:
    observations = tuple(
        ProbabilityCalibrationObservation(
            predicted_probability=0.8 if index < 60 else 0.2,
            outcome=(index % 5 != 0) if index < 60 else (index % 5 == 0),
            observed_on=date(2025, 1, 1) + timedelta(days=index),
        )
        for index in range(120)
    )
    calibration = evaluate_probability_calibration(observations)
    assert calibration.status == "calibrated"
    assert calibration.brier_score is not None
    assert calibration.brier_score < calibration.baseline_brier_score  # type: ignore[operator]

    reference = tuple(
        ProbabilityCalibrationObservation(0.5, index % 2 == 0, date(2025, 1, 1))
        for index in range(40)
    )
    recent = tuple(
        ProbabilityCalibrationObservation(0.8, index % 10 != 0, date(2026, 1, 1))
        for index in range(40)
    )
    drift = detect_probability_drift(reference, recent)
    assert drift.status == "drifting"


def test_momentum_crash_monitor_is_gradual_and_missing_data_is_conservative() -> None:
    unavailable = evaluate_momentum_crash_risk(MomentumCrashInput())
    assert not unavailable.available
    assert 0 < unavailable.momentum_multiplier < 1

    high = evaluate_momentum_crash_risk(
        MomentumCrashInput(
            rebound_after_drawdown=0.9,
            winner_loser_beta_spread=0.8,
            short_interest_pressure=0.8,
            return_dispersion=0.9,
            high_volatility_state=0.9,
            momentum_factor_drawdown=0.8,
            valuation_crowding=0.8,
            industry_concentration=0.9,
            correlation_spike=0.9,
        )
    )
    assert high.risk_level == "high"
    assert 0 < high.momentum_multiplier < high.total_risk_multiplier < 1


def test_score_only_regime_cannot_restore_full_risk_in_one_session() -> None:
    decision = decide_regime_budget(
        RegimeBudgetInput(
            regime="risk_on",
            calibration_status="score_only",
            score=0.9,
            probability=None,
            previous_multiplier=0.5,
            confirmation_count=5,
            sessions_since_change=10,
        )
    )

    assert decision.display_name == "Market Regime Score"
    assert decision.applied_multiplier == pytest.approx(0.6)
    assert decision.transition_limited


def test_ensemble_fails_closed_and_conditional_evidence_cannot_create_position() -> None:
    capabilities = ResearchCapabilities(pit_prices=True, benchmark_history=True)
    blocked = build_ensemble(
        data_gate=_gate(passed=False),
        sleeve_assessments=assess_sleeves(_gate(passed=False), capabilities),
        signals=(_signal(),),
        conditional_evidence={"AAPL": _positive_evidence()},
        regime=_regime(),
        momentum_crash=_crash(),
        portfolio=PortfolioRiskSnapshot(),
        config=CapitalPreservationConfig(),
    )
    assert blocked.total_invested_weight == 0
    assert blocked.cash_weight == 1

    gate = _gate()
    result = build_ensemble(
        data_gate=gate,
        sleeve_assessments=assess_sleeves(gate, capabilities),
        signals=(_signal(grade="negative"),),
        conditional_evidence={"AAPL": _positive_evidence()},
        regime=_regime(),
        momentum_crash=_crash(),
        portfolio=PortfolioRiskSnapshot(),
        config=CapitalPreservationConfig(),
    )
    assert result.decisions[0].risk_constrained_weight == 0


def test_ensemble_applies_sector_cluster_and_top_five_limits() -> None:
    gate = _gate()
    capabilities = ResearchCapabilities(pit_prices=True, benchmark_history=True)
    signals = tuple(_signal(symbol=f"T{index}") for index in range(6))
    result = build_ensemble(
        data_gate=gate,
        sleeve_assessments=assess_sleeves(gate, capabilities),
        signals=signals,
        conditional_evidence={},
        regime=_regime(),
        momentum_crash=_crash(),
        portfolio=PortfolioRiskSnapshot(),
        config=CapitalPreservationConfig(
            maximum_single_name_weight=0.10,
            maximum_sector_weight=0.18,
            maximum_cluster_weight=0.18,
            maximum_top_five_weight=0.15,
        ),
    )

    assert sum(item.risk_constrained_weight for item in result.decisions[:5]) <= 0.15 + 1e-12
    assert result.total_invested_weight <= 0.18 + 1e-12


@pytest.mark.parametrize(
    "method",
    (
        "equal_weight",
        "score_bucket_equal",
        "inverse_volatility",
        "cluster_risk",
        "regularized_risk_budget",
    ),
)
def test_allocation_methods_respect_cash_and_position_caps(method: str) -> None:
    assets = tuple(
        AllocationAsset(
            symbol=f"S{index}",
            score=float(index),
            volatility=0.15 + index * 0.01,
            cluster="A" if index < 5 else "B",
            current_weight=0.02,
        )
        for index in range(10)
    )
    result = allocate_assets(
        assets,
        method=method,
        maximum_invested_weight=0.50,
        maximum_asset_weight=0.08,
    )

    assert sum(result.weights.values()) <= 0.50 + 1e-12
    assert max(result.weights.values()) <= 0.08 + 1e-12
    assert result.cash_weight >= 0.50 - 1e-12


def test_stage_gate_never_automatically_approves_real_capital() -> None:
    decision = assess_stage_gate(
        ResearchStage.FORWARD_OBSERVATION,
        StageEvidence(
            data_gate_passed=True,
            frozen_parameters=True,
            locked_test_passed=True,
            benchmark_suite_complete=True,
            costs_included=True,
        observation_days=150,
            shadow_days=80,
            manual_risk_approval=True,
        ),
    )

    assert decision.maximum_allowed_stage is ResearchStage.MANUAL_MICRO_CAPITAL
    assert not decision.automatic_capital_decision_allowed
    assert any("human capital decision" in item for item in decision.blockers)


def test_factor_weighting_compares_five_methods_without_locked_test_input() -> None:
    factors = tuple(
        FactorEvidence(
            name=name,
            category=category,
            available=True,
            train_ic=(0.03, 0.02, 0.04, 0.01, 0.03, 0.02),
            validation_ic=(0.02, 0.03, 0.01, 0.02, 0.04, 0.02),
            theoretical_weight=theory,
        )
        for name, category, theory in (
            ("momentum_12_1", "momentum", 0.35),
            ("roic", "quality", 0.30),
            ("downside_volatility", "risk", 0.20),
            ("liquidity", "risk", 0.15),
        )
    )
    result = compare_factor_weighting(factors)

    assert set(result.candidates) == {
        "equal_weight",
        "fixed_theory",
        "rolling_ic",
        "risk_constrained",
        "regularized",
    }
    assert result.selected_method == "equal_weight"
    assert not result.locked_test_used_for_fitting


def test_unavailable_point_in_time_factor_is_automatically_disabled() -> None:
    result = compare_factor_weighting(
        (
            FactorEvidence(
                name="analyst_estimate_revision",
                category="earnings",
                available=False,
                train_ic=(),
                validation_ic=(),
            ),
        )
    )

    assert result.selected_method == "none"
    assert not result.selected_weights
    assert "disabled factor analyst_estimate_revision" in result.reasons[0]


def test_factor_weighting_fails_closed_when_factor_breadth_cannot_meet_cap() -> None:
    result = compare_factor_weighting(
        (
            FactorEvidence(
                name="momentum_12_1",
                category="momentum",
                available=True,
                train_ic=(0.01,) * 6,
                validation_ic=(0.01,) * 6,
            ),
            FactorEvidence(
                name="roic",
                category="quality",
                available=True,
                train_ic=(0.01,) * 6,
                validation_ic=(0.01,) * 6,
            ),
        ),
        maximum_factor_weight=0.40,
    )

    assert result.selected_method == "none"
    assert any("factor breadth" in reason for reason in result.reasons)
