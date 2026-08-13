from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import (
    TradeAction,
    TradeEvidence,
    TradeGenerator,
)
from personal_alpha_terminal.quant_engine.probability_overlay import (
    ConditionalProbabilityEvidence,
    OverlayPerformanceMetrics,
    ProbabilityOverlayIdentity,
    ProbabilityOverlayRegistry,
    ProbabilityOverlayState,
    apply_probability_overlay,
    build_probability_overlay_artifact,
    write_probability_evidence,
    write_probability_overlay_artifact,
)
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

NOW = datetime(2026, 8, 12, 1, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _identity(**changes: str) -> ProbabilityOverlayIdentity:
    values = {
        "strategy_version": "alpha-v1",
        "strategy_parameter_hash": "params-v1",
        "research_data_version": "data-v1",
        "research_data_hash": "data-hash-v1",
        "universe_version": "universe-v1",
        "probability_model_version": "prob-v1",
        "calibration_version": "cal-v1",
    }
    values.update(changes)
    return ProbabilityOverlayIdentity(**values)


def _metrics(*, improved: bool) -> OverlayPerformanceMetrics:
    return OverlayPerformanceMetrics(
        annualized_return=0.13 if improved else 0.10,
        annualized_volatility=0.14,
        sharpe=0.85 if improved else 0.65,
        sortino=1.10 if improved else 0.85,
        max_drawdown=0.16 if improved else 0.17,
        calmar=0.81 if improved else 0.59,
        turnover=0.40,
        hit_rate=0.54 if improved else 0.51,
        average_win=0.012,
        average_loss=-0.009,
        profit_factor=1.30 if improved else 1.10,
        benchmark_alpha=0.025 if improved else 0.010,
        information_ratio=0.50 if improved else 0.25,
        transaction_cost=0.006,
    )


def _artifact(
    *,
    state: ProbabilityOverlayState = ProbabilityOverlayState.PRODUCTION_APPROVED,
    upstream_certified: bool = True,
    identity: ProbabilityOverlayIdentity | None = None,
):
    return build_probability_overlay_artifact(
        artifact_id="overlay-v1",
        identity=identity or _identity(),
        requested_state=state,
        mechanism="OOS_NET_RESIDUAL_SHRINKAGE",
        shrinkage_coefficient=0.5,
        maximum_absolute_adjustment=0.02,
        minimum_condition_sample=100,
        condition_whitelist=("factor-state",),
        multiple_testing_method="BENJAMINI_HOCHBERG",
        train_start=date(2018, 1, 2),
        train_end=date(2021, 12, 31),
        validation_start=date(2022, 1, 3),
        validation_end=date(2023, 12, 29),
        oos_start=date(2024, 1, 2),
        oos_end=date(2025, 12, 31),
        embargo_sessions=20,
        walk_forward_folds=4,
        locked_oos_sessions=504,
        brier_score=0.17,
        baseline_brier_score=0.23,
        log_loss=0.51,
        expected_calibration_error=0.025,
        calibration_slope=1.0,
        calibration_intercept=0.01,
        base_metrics=_metrics(improved=False),
        overlay_metrics=_metrics(improved=True),
        costs_included=True,
        benchmark="SPY",
        locked_oos=True,
        residual_return_net_of_costs=True,
        created_at=NOW - timedelta(days=1),
        available_at=NOW - timedelta(hours=2),
        upstream_research_certified=upstream_certified,
    )


def _alpha(symbol: str, expected: float) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=NOW - timedelta(hours=1),
        signal_type="cross-sectional-composite",
        expected_excess_return=expected,
        horizon=20,
        raw_signal=expected,
        normalized_signal=expected,
        confidence=0.7,
        confidence_calibrated=False,
        sample_size=300,
        statistical_strength=0.7,
        economic_strength=0.7,
        decay_half_life=40,
        valid_until=NOW + timedelta(days=2),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
        model_version="alpha-v1",
        data_version="data-v1",
    )


def _evidence(
    symbol: str,
    residual: float,
    *,
    sample_size: int = 150,
    available_at: datetime = NOW - timedelta(minutes=30),
) -> ConditionalProbabilityEvidence:
    return ConditionalProbabilityEvidence(
        symbol=symbol,
        condition_id="factor-state",
        as_of=NOW - timedelta(hours=1),
        available_at=available_at,
        sample_size=sample_size,
        wins=90 if sample_size == 150 else sample_size // 2,
        losses=60 if sample_size == 150 else sample_size - sample_size // 2,
        raw_probability=0.60,
        prior_probability=0.50,
        posterior_probability=0.58,
        credible_interval=(0.50, 0.66),
        expected_residual_return=residual,
        calibration_state="CALIBRATED_LOCKED_OOS",
        model_version="prob-v1",
        data_version="data-v1",
    )


def _base_signals() -> tuple[AlphaSignal, ...]:
    return tuple(
        _alpha(symbol, expected)
        for symbol, expected in zip(SYMBOLS, (0.014, 0.013, 0.012, 0.011), strict=True)
    )


def _all_evidence() -> tuple[ConditionalProbabilityEvidence, ...]:
    return tuple(
        _evidence(symbol, residual)
        for symbol, residual in zip(SYMBOLS, (-0.006, 0.0, 0.004, 0.020), strict=True)
    )


def test_uncertified_research_data_cannot_produce_overlay_approval() -> None:
    artifact = _artifact(upstream_certified=False)

    assert artifact.state is ProbabilityOverlayState.RESEARCH_ONLY
    assert "RESEARCH_DATA_NOT_CERTIFIED" in artifact.blockers


def test_research_only_probability_never_changes_base_alpha() -> None:
    base = _base_signals()
    result = apply_probability_overlay(
        base,
        _all_evidence(),
        artifact=_artifact(state=ProbabilityOverlayState.RESEARCH_ONLY),
        expected_identity=_identity(),
        decision_time=NOW,
    )

    assert not result.active
    assert result.signals == base
    assert result.reason == "PROBABILITY_OVERLAY_NOT_PRODUCTION_APPROVED"


def test_missing_probability_artifact_safely_falls_back_to_base() -> None:
    base = _base_signals()
    result = apply_probability_overlay(
        base,
        (),
        artifact=None,
        expected_identity=_identity(),
        decision_time=NOW,
    )

    assert result.signals == base
    assert result.reason == "PROBABILITY_FALLBACK_CLASSICAL"


def test_only_approved_overlay_changes_expected_return_and_rank_inputs() -> None:
    base = _base_signals()
    result = apply_probability_overlay(
        base,
        _all_evidence(),
        artifact=_artifact(),
        expected_identity=_identity(),
        decision_time=NOW,
    )
    expected = {item.symbol: item.expected_excess_return for item in result.signals}

    assert result.active
    assert expected["D"] == pytest.approx(0.021)
    assert expected["A"] == pytest.approx(0.011)
    assert max(expected, key=expected.get) == "D"


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        ((_evidence("A", 0.1, sample_size=30),), "PROBABILITY_SAMPLE_INSUFFICIENT"),
        (
            tuple(
                _evidence(symbol, 0.01, available_at=NOW + timedelta(seconds=1))
                for symbol in SYMBOLS
            ),
            "FUTURE_PROBABILITY_EVIDENCE_NOT_ALLOWED",
        ),
    ],
)
def test_incomplete_small_or_future_probability_evidence_cannot_change_alpha(
    evidence: tuple[ConditionalProbabilityEvidence, ...], reason: str
) -> None:
    base = _base_signals()
    result = apply_probability_overlay(
        base,
        evidence,
        artifact=_artifact(),
        expected_identity=_identity(),
        decision_time=NOW,
    )

    assert not result.active
    assert result.signals == base
    assert result.reason == reason


def test_parameter_or_data_hash_change_invalidates_old_overlay() -> None:
    base = _base_signals()
    result = apply_probability_overlay(
        base,
        _all_evidence(),
        artifact=_artifact(),
        expected_identity=_identity(strategy_parameter_hash="params-v2"),
        decision_time=NOW,
    )

    assert result.signals == base
    assert result.reason == "PROBABILITY_ARTIFACT_IDENTITY_MISMATCH"


def test_probability_artifact_and_evidence_are_hash_verified_and_immutable(tmp_path) -> None:
    artifact = _artifact()
    artifact_path = write_probability_overlay_artifact(artifact, tmp_path)
    evidence_path = write_probability_evidence(artifact, _all_evidence(), tmp_path)
    registry = ProbabilityOverlayRegistry(tmp_path)

    assert registry.matching(_identity()) == artifact
    assert registry.evidence(artifact, decision_time=NOW) == _all_evidence()
    assert write_probability_overlay_artifact(artifact, tmp_path) == artifact_path
    assert write_probability_evidence(artifact, _all_evidence(), tmp_path) == evidence_path

    evidence_path.write_text(evidence_path.read_text().replace("0.02", "0.03"))
    with pytest.raises(ValueError, match="content hash mismatch"):
        registry.evidence(artifact, decision_time=NOW)


def _authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 11),
        NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "TEST_FIXTURE",
        ("source-a",),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        NOW - timedelta(days=2),
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
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _risk():
    rng = np.random.default_rng(81)
    market = rng.normal(0.0003, 0.008, 180)
    returns = pd.DataFrame(
        {
            symbol: 0.7 * market + rng.normal(0.0002, 0.006, 180)
            for symbol in SYMBOLS
        },
        index=pd.bdate_range("2025-11-24", periods=180),
    )
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            75_000_000.0,
            (index - 1.5) / 4,
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    return PortfolioRiskModel().fit(
        returns,
        metadata=metadata,
        benchmark_returns=pd.Series(market, index=returns.index),
    )


def _construction() -> PortfolioConstructionEngine:
    return PortfolioConstructionEngine(
        PortfolioConstraints(
            maximum_position_weight=0.30,
            maximum_sector_weight=0.60,
            maximum_cluster_weight=0.70,
            maximum_hhi=0.35,
            minimum_cash_weight=0.15,
            maximum_gross_exposure=0.85,
            target_annualized_volatility=0.25,
            maximum_beta=1.10,
            maximum_turnover=0.90,
            maximum_size_exposure=0.50,
            no_trade_band=0.001,
            minimum_rebalance_weight=0.001,
            minimum_trade_value=10.0,
            risk_aversion=2.0,
            turnover_penalty=0.0001,
            model_validation_id="TEST_FIXTURE_LOCKED_OOS",
        )
    )


def test_causal_chain_approved_probability_changes_weight_and_recommendation() -> None:
    base = _base_signals()
    adjusted = apply_probability_overlay(
        base,
        _all_evidence(),
        artifact=_artifact(),
        expected_identity=_identity(),
        decision_time=NOW,
    ).signals
    engine = _construction()
    risk = _risk()
    budget = RiskBudget(1.0, 1.0, 1.0, True, ())
    initial = engine.construct(
        authorization=_authorization(),
        alpha_signals=base,
        risk=risk,
        current_weights={},
        portfolio_value=100_000.0,
        decision_time=NOW,
        risk_budget=budget,
    )
    base_target = engine.construct(
        authorization=_authorization(),
        alpha_signals=base,
        risk=risk,
        current_weights=initial.target_weights,
        portfolio_value=100_000.0,
        decision_time=NOW,
        risk_budget=budget,
    )
    overlay_target = engine.construct(
        authorization=_authorization(),
        alpha_signals=adjusted,
        risk=risk,
        current_weights=initial.target_weights,
        portfolio_value=100_000.0,
        decision_time=NOW,
        risk_budget=budget,
    )
    evidence = {
        item.symbol: TradeEvidence(
            item.expected_excess_return,
            item.confidence,
            item.horizon,
            ("deterministic alpha",),
            (),
        )
        for item in adjusted
    }
    proposals = TradeGenerator().generate(
        target=overlay_target,
        current_weights=initial.target_weights,
        portfolio_value=100_000.0,
        evidence=evidence,
        risk_contribution={},
        average_daily_dollar_volume=dict.fromkeys(SYMBOLS, 75_000_000.0),
        minimum_trade_weight=0.001,
    )

    assert base_target.production_approved and overlay_target.production_approved
    assert overlay_target.target_weights != pytest.approx(base_target.target_weights)
    assert overlay_target.target_weights.get("D", 0.0) > base_target.target_weights.get(
        "D", 0.0
    )
    assert any(item.action is not TradeAction.HOLD for item in proposals)
