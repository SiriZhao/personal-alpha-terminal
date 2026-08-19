"""ROUND77 attribution and participation diagnosis tests."""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.research.alpha_diagnosis import (
    CashClassification,
    MarketRegime,
    PerformanceObservation,
    RegimeInput,
    StatisticalStatus,
    aggregate_cash_classification,
    build_economic_diagnosis,
    classify_regime,
    compute_performance_metrics,
    fixed_selection_exposure_counterfactual,
    paired_block_bootstrap,
    reconcile_active_return,
    validate_variant_alignment,
)
from personal_alpha_terminal.research.certified_data import current_data_certification
from personal_alpha_terminal.research.production_parity_replay import (
    ReplayEvidenceClass,
    ReplayVariant,
)

NOW = datetime(2024, 1, 3, 20, tzinfo=UTC)


def _observation(index: int, *, evidence: ReplayEvidenceClass = ReplayEvidenceClass.FIXTURE_SUPPLEMENTARY) -> PerformanceObservation:
    return PerformanceObservation(
        session=date(2024, 1, 3) + timedelta(days=index),
        decision_time=NOW + timedelta(days=index),
        evidence_cutoff=NOW + timedelta(days=index, minutes=-1),
        evidence_class=evidence,
        portfolio_return=0.012 if index % 2 == 0 else -0.002,
        spy_return=0.010 if index % 2 == 0 else -0.004,
        qqq_return=0.011 if index % 2 == 0 else -0.005,
        selection_alpha=0.001,
        timing_exposure_alpha=0.0015,
        cost_drag=-0.0005,
        turnover=0.1,
        expected_cost=0.0004,
        realized_cost=0.0005,
        concentration=0.4,
        exposure=0.8,
        cash=0.2,
        cash_breakdown={
            CashClassification.INTENTIONAL_RISK_CASH: 0.1,
            CashClassification.NO_VALID_OPPORTUNITY_CASH: 0.05,
            CashClassification.OPTIMIZER_ARTIFACT_CASH: 0.03,
            CashClassification.CONSTRAINT_BINDING_CASH: 0.01,
            CashClassification.ROUNDING_CASH: 0.01,
            CashClassification.DATA_QUALITY_CASH: 0.0,
        },
        regime=MarketRegime.NORMAL,
    )


def test_active_return_reconciliation_has_no_unlabelled_alpha_residual() -> None:
    rows = (_observation(0), _observation(1))
    attribution = reconcile_active_return(rows)
    assert attribution.reconciled
    assert attribution.residual == pytest.approx(0.0)
    assert attribution.active_return == pytest.approx(
        attribution.selection_alpha + attribution.timing_exposure_alpha + attribution.cost_drag
    )


def test_fixed_selection_counterfactual_preserves_selected_names() -> None:
    base = {"AAA": 0.6, "BBB": 0.2}
    counterfactual = fixed_selection_exposure_counterfactual(base, gross_exposure=0.9, label="90%")
    assert set(counterfactual.weights) == set(base)
    assert sum(counterfactual.weights.values()) == pytest.approx(0.9)
    assert counterfactual.cash == pytest.approx(0.1)


def test_regime_uses_only_decision_time_available_inputs() -> None:
    with pytest.raises(ValueError, match="future-available"):
        RegimeInput(NOW, NOW, NOW + timedelta(seconds=1), 0.2, -0.05, False)
    bull = RegimeInput(NOW, NOW, NOW, 0.2, -0.05, False)
    assert classify_regime(bull) is MarketRegime.BULL


def test_cost_cash_and_benchmark_metrics_are_explicit() -> None:
    rows = tuple(_observation(index) for index in range(4))
    metrics = compute_performance_metrics(rows)
    assert metrics.realized_cost == pytest.approx(0.002)
    assert metrics.expected_cost == pytest.approx(0.0016)
    assert metrics.spy_excess is not None
    cash = aggregate_cash_classification(rows)
    assert cash[CashClassification.OPTIMIZER_ARTIFACT_CASH] == pytest.approx(0.12)
    with pytest.raises(ValueError, match="reconcile"):
        replace(
            _observation(0),
            cash_breakdown={CashClassification.INTENTIONAL_RISK_CASH: 0.1},
        )


def test_bootstrap_is_deterministic_and_refuses_insufficient_sample() -> None:
    small = paired_block_bootstrap(tuple(_observation(index) for index in range(3)), min_sessions=4)
    assert small.status is StatisticalStatus.INSUFFICIENT_SAMPLE
    rows = tuple(_observation(index) for index in range(20))
    first = paired_block_bootstrap(rows, min_sessions=20, resamples=100, random_seed=11)
    second = paired_block_bootstrap(rows, min_sessions=20, resamples=100, random_seed=11)
    assert first == second
    assert first.status is StatisticalStatus.ESTABLISHED


def test_variant_alignment_rejects_misaligned_benchmark_cutoffs() -> None:
    first = tuple(_observation(index) for index in range(2))
    changed = list(first)
    changed[1] = replace(
        first[1],
        evidence_cutoff=first[1].evidence_cutoff - timedelta(seconds=1),
    )
    blockers = validate_variant_alignment(
        {ReplayVariant.PURE_QUANT: first, ReplayVariant.ALPHA_ENGINE3_CHALLENGER: tuple(changed)}
    )
    assert "VARIANT_EVIDENCE_ALIGNMENT_MISMATCH" in blockers[0]


def test_current_economic_diagnosis_is_blocked_and_answers_not_established() -> None:
    diagnosis = build_economic_diagnosis(
        {ReplayVariant.PURE_QUANT: (_observation(0),)},
        data_certification=current_data_certification(),
        locked_oos_manifest=None,
    )
    assert diagnosis.status.value == "BLOCKED_DATA_QUALITY"
    assert all(value.startswith("NOT ESTABLISHED / N/A") for value in diagnosis.answers.values())
