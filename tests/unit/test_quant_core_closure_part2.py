# ruff: noqa: E501, I001, UP017
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.outbound_policy import redact_outbound_payload, verify_numeric_claim
from personal_alpha_terminal.models import Base
from personal_alpha_terminal.quant_engine.conditional_evidence import ConditionalSample, benjamini_hochberg, build_conditional_evidence
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig, TransactionCostModel
from personal_alpha_terminal.quant_engine.event_study_production import EventObservation, run_event_study
from personal_alpha_terminal.quant_engine.factors.contracts import FactorObservation
from personal_alpha_terminal.quant_engine.factors.cross_sectional import FactorSignalStatus
from personal_alpha_terminal.quant_engine.governance import ExperimentDefinition, ExperimentRegistry, deflated_sharpe_risk, purged_walk_forward_splits
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    RiskModelStatus,
    SizeExposureStatus,
)
from personal_alpha_terminal.quant_engine.risk.stress import evaluate_portfolio_stress

UTC = timezone.utc


def test_factor_observation_rejects_future_and_nonfinite_valid_data() -> None:
    now = datetime(2024, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="unavailable"):
        FactorObservation("A", now, now + timedelta(seconds=1), "d", "f", 1, 1, 1, 1, FactorSignalStatus.VALID)
    with pytest.raises(ValueError, match="finite"):
        FactorObservation("A", now, now, "d", "f", float("nan"), 1, 1, 1, FactorSignalStatus.VALID)


def _samples(count: int, *, start: datetime, conditional: bool) -> tuple[ConditionalSample, ...]:
    return tuple(ConditionalSample(start + timedelta(days=i), start + timedelta(days=i + 1), (0.02 if i % 4 else -0.01) if conditional else (0.01 if i % 2 else -0.01), f"c-{i}") for i in range(count))


def test_conditional_evidence_is_lift_based_oos_calibrated_and_fdr_gated() -> None:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    result = build_conditional_evidence(
        conditional_samples=_samples(60, start=start, conditional=True), baseline_samples=_samples(100, start=start, conditional=False), information_cutoff=start + timedelta(days=100),
        oos_probabilities=tuple(0.75 if i % 4 else 0.25 for i in range(60)), oos_outcomes=tuple(i % 4 != 0 for i in range(60)), transaction_cost_rate=0.001,
        raw_p_value=0.01, family_p_values=(0.01, 0.2, 0.4), maximum_age_days=100,
    )
    assert result.probability_lift is not None and result.probability_lift > 0
    assert result.oos_brier is not None and result.baseline_brier is not None
    assert result.oos_brier < result.baseline_brier
    assert result.fdr_adjusted_p_value == pytest.approx(0.03)
    assert result.status == "VALIDATED_SUPPORTING_EVIDENCE"
    assert benjamini_hochberg((0.01, 0.04, 0.9)) == pytest.approx((0.03, 0.06, 0.9))


def test_conditional_evidence_right_censors_and_deduplicates_clusters() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    samples = _samples(35, start=start, conditional=True)
    duplicate = ConditionalSample(start, start + timedelta(days=1), 0.9, "c-0")
    future = ConditionalSample(start, start + timedelta(days=99), 0.9, "future")
    result = build_conditional_evidence(
        conditional_samples=(*samples, duplicate, future), baseline_samples=_samples(40, start=start, conditional=False), information_cutoff=start + timedelta(days=50),
        oos_probabilities=tuple(0.5 for _ in range(35)), oos_outcomes=tuple(i % 2 == 0 for i in range(35)), transaction_cost_rate=0, raw_p_value=0.5, family_p_values=(0.5,), maximum_age_days=100,
    )
    assert result.raw_sample_size == 35
    assert result.status == "BLOCKED"


def _definition(parameter: str = "p1") -> ExperimentDefinition:
    return ExperimentDefinition("exp", "Does a PIT factor add after-cost OOS alpha?", "v1", "d1", "u1", {"momentum": "1"}, parameter, (date(2010, 1, 1), date(2015, 12, 31)), (date(2016, 1, 1), date(2017, 12, 31)), 5, (date(2018, 1, 1), date(2020, 12, 31)), {"SPY": "proxy-v1"}, "cost-v1", "abc")


def test_experiment_registry_is_append_only_and_locked_test_immutable() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        registry = ExperimentRegistry(session)
        first = registry.register(_definition())
        registry.lock(first)
        returns = tuple(0.001 + (i % 5) * 0.0001 for i in range(60))
        risk = deflated_sharpe_risk(returns, trial_count=2)
        registry.record_result(first, stage="LOCKED_TEST", metrics={"sharpe": 1.0}, mining_risk=risk, status="REJECTED", evaluated_at=datetime.now(UTC))
        with pytest.raises(ValueError, match="immutable"):
            registry.record_result(first, stage="LOCKED_TEST", metrics={"sharpe": 2.0}, mining_risk=risk, status="VALIDATED", evaluated_at=datetime.now(UTC))
        assert registry.register(_definition("p2")).version == 2
    assert purged_walk_forward_splits(100, train_size=40, validation_size=10, test_size=10, embargo=5, step=10)


def test_event_study_uses_abnormal_returns_and_remains_support_only() -> None:
    index = pd.date_range("2020-01-01", periods=140, freq="B", tz="UTC")
    asset = pd.Series(0.002, index=index)
    benchmark = pd.Series(0.001, index=index)
    events = tuple(EventObservation(f"e{i}", index[i].to_pydatetime(), index[i], f"c{i}", "NEUTRAL") for i in range(20, 120, 5))
    result = run_event_study(events=events, asset_returns=asset, benchmark_returns=benchmark, information_cutoff=index[-1].to_pydatetime(), minimum_sample_size=20, random_seed=7)
    assert result.mean_abnormal_return == pytest.approx(0.005)
    assert result.status == "RESEARCH_SUPPORT_ONLY"


def test_cost_model_includes_configured_minimum_and_regulatory_fee() -> None:
    model = TransactionCostModel(TransactionCostConfig(commission_bps=0, minimum_fee=1, regulatory_fee_bps=2))
    result = model.estimate(trade_value=1000, average_daily_dollar_volume=1_000_000)
    assert result.commission == 1
    assert result.regulatory_fee == pytest.approx(0.2)
    assert result.total_cost >= 1.2


def test_portfolio_stress_reports_cvar_liquidity_and_concentration() -> None:
    covariance = np.array([[0.04, 0.01], [0.01, 0.09]])
    risk = RiskModelEstimate(
        symbols=("A", "B"),
        annualized_covariance=covariance,
        correlation=np.array([[1, 0.2], [0.2, 1]]),
        annualized_volatility={"A": 0.2, "B": 0.3},
        beta={"A": 1.0, "B": 1.2},
        sectors={"A": "TECH", "B": "FIN"},
        average_daily_dollar_volume={"A": 1_000_000, "B": 500_000},
        size_scores={"A": 1, "B": 0},
        size_exposure_status=SizeExposureStatus.VALID,
        observations=100,
        status=RiskModelStatus.VALID,
        condition_number=2,
        shrinkage=0.2,
        model_version="risk-v1",
        limitations=(),
    )
    report = evaluate_portfolio_stress(weights={"A": 0.4, "B": 0.3}, portfolio_returns=tuple(-0.02 if i % 20 == 0 else 0.001 for i in range(100)), risk=risk, portfolio_value=100_000, maximum_adv_participation=0.02)
    assert report.historical_cvar_95 < 0
    assert report.liquidity_liquidation_days > 0
    assert report.hhi == pytest.approx(0.25)


def test_ai_outbound_is_redacted_and_numeric_claim_must_match_evidence() -> None:
    redacted = redact_outbound_payload({"symbol": "AAPL", "account_number": "secret", "nested": {"quantity": 5, "score": 1}})
    assert "account_number" not in redacted
    assert redacted["nested"] == {"score": 1}
    evidence = {"symbol": "AAPL", "date": "2024-01-01", "return": 0.05, "return_unit": "decimal", "source_field": "return"}
    claim = {"symbol": "AAPL", "date": "2024-01-01", "field": "return", "value": 0.05, "unit": "decimal", "direction": "positive"}
    assert verify_numeric_claim(claim=claim, evidence=evidence)
    assert not verify_numeric_claim(claim={**claim, "value": 0.5}, evidence=evidence)
