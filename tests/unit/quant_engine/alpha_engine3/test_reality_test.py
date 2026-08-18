from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from personal_alpha_terminal.quant_engine.alpha_engine3 import (
    AlignedPerformanceObservation,
    RealityTestVerdict,
    classify_market_regime_as_of,
    compact_reality_status,
    run_alpha_engine3_reality_test,
)


def _observations() -> tuple[AlignedPerformanceObservation, ...]:
    rows: list[AlignedPerformanceObservation] = []
    start = date(2025, 1, 2)
    for index in range(140):
        benchmark = 0.004 if index % 5 else -0.006
        champion_exposure = 0.55
        challenger_exposure = 0.80
        champion = champion_exposure * benchmark + 0.0002 - 0.0001
        challenger = challenger_exposure * benchmark + 0.0006 - 0.0002
        rows.append(
            AlignedPerformanceObservation(
                session=start + timedelta(days=index),
                champion_return=champion,
                challenger_return=challenger,
                spy_return=benchmark,
                qqq_return=benchmark + 0.0003,
                champion_exposure=champion_exposure,
                challenger_exposure=challenger_exposure,
                champion_turnover=0.03,
                challenger_turnover=0.05,
                champion_cost=0.0001,
                challenger_cost=0.0002,
                champion_concentration=0.18,
                challenger_concentration=0.20,
                decisions=1,
                risk_targeted_exposure=0.90,
                adaptive_exposure=0.75,
            )
        )
    return tuple(rows)


def test_reality_test_reconciles_selection_timing_and_cost_without_promotion() -> None:
    result = run_alpha_engine3_reality_test(_observations(), bootstrap_samples=100)
    challenger = result.challenger
    reconciled = challenger.selection_alpha + challenger.timing_alpha + challenger.cost_drag
    arithmetic_active = sum(item.challenger_return - item.spy_return for item in _observations())
    assert reconciled == pytest.approx(arithmetic_active)
    assert result.verdict is RealityTestVerdict.BLOCKED_DATA_QUALITY
    assert result.diagnostic_only
    assert result.challenger_minus_champion["total_return"] is not None


def test_counterfactual_exposure_explains_bull_opportunity_loss() -> None:
    result = run_alpha_engine3_reality_test(_observations(), bootstrap_samples=100)
    by_name = {item.name: item for item in result.challenger_counterfactuals}
    assert by_name["100%"].total_return > by_name["current_exposure"].total_return
    assert by_name["current_exposure"].underexposure_drag > 0
    assert result.challenger.upside_capture is not None
    assert result.challenger.downside_capture is not None


def test_regime_classification_does_not_use_current_session_return() -> None:
    benchmark = tuple(np.linspace(-0.002, 0.004, 40))
    poisoned = list(benchmark)
    poisoned[30] = 0.50
    assert classify_market_regime_as_of(benchmark, index=30) == classify_market_regime_as_of(
        tuple(poisoned),
        index=30,
    )


def test_compact_status_keeps_operator_view_small() -> None:
    status = compact_reality_status(
        run_alpha_engine3_reality_test(_observations(), bootstrap_samples=100)
    )
    assert "ALPHA ENGINE 3 REALITY" in status
    assert "cash_drag=" in status
