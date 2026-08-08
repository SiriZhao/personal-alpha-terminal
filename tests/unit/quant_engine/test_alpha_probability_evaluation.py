from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
    UnifiedAlphaEngine,
)
from personal_alpha_terminal.quant_engine.factors.evaluation import (
    evaluate_factor,
    evaluate_ic_decay,
)
from personal_alpha_terminal.quant_engine.probability import (
    estimate_conditional_lift,
    evaluate_probability_calibration,
    evaluate_probability_stability,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _alpha(**changes: object) -> AlphaSignal:
    base = AlphaSignal(
        symbol="AAPL",
        as_of=NOW,
        signal_type="quality",
        expected_excess_return=0.01,
        horizon=20,
        raw_signal=1.2,
        normalized_signal=0.8,
        confidence=0.7,
        confidence_calibrated=True,
        sample_size=250,
        statistical_strength=0.8,
        economic_strength=0.6,
        decay_half_life=40,
        valid_until=NOW + timedelta(days=3),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
        model_version="alpha-v1",
        data_version="data-v1",
    )
    return replace(base, **changes)


def test_unvalidated_or_nonpit_alpha_cannot_enter_daily_decision() -> None:
    signals = (
        _alpha(validation_status=AlphaValidationStatus.TESTED),
        _alpha(signal_type="momentum", pit_valid=False),
        _alpha(signal_type="volatility"),
    )
    eligible = UnifiedAlphaEngine().for_decision(
        signals, decision_time=NOW + timedelta(hours=1)
    )
    assert [item.signal_type for item in eligible] == ["volatility"]
    assert not UnifiedAlphaEngine().for_decision(
        (_alpha(confidence_calibrated=False),),
        decision_time=NOW + timedelta(hours=1),
    )


def test_conditional_probability_reports_baseline_and_expected_return_lift() -> None:
    conditional = tuple([0.02] * 36 + [-0.01] * 4)
    baseline = tuple([0.01, -0.01] * 30)
    result = estimate_conditional_lift(conditional, baseline, minimum_sample_size=30)
    assert result.valid
    assert result.probability_lift is not None and result.probability_lift > 0
    assert result.expected_return_lift is not None and result.expected_return_lift > 0
    assert result.credible_interval is not None
    assert result.odds_ratio is not None and result.odds_ratio > 1


def test_small_probability_sample_is_invalid_and_shows_no_extreme_estimate() -> None:
    result = estimate_conditional_lift((0.1,) * 5, (0.0,) * 100, minimum_sample_size=30)
    assert not result.valid
    assert result.conditional_probability is None
    assert result.expected_return_lift is None


def test_probability_calibration_must_beat_oos_baseline_and_be_stable() -> None:
    outcomes = tuple(index % 2 == 0 for index in range(40))
    useful = tuple(0.8 if outcome else 0.2 for outcome in outcomes)
    calibration = evaluate_probability_calibration(useful, outcomes)
    assert calibration.calibrated
    stable = evaluate_probability_stability(
        (tuple([0.02] * 25 + [-0.01] * 5),) * 3,
        (tuple([0.01, -0.01] * 20),) * 3,
    )
    assert stable.stable


def _panel() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, day in enumerate(pd.date_range("2020-01-31", periods=18, freq="ME")):
        for asset in range(10):
            signal = float(asset)
            rows.append(
                {
                    "as_of_date": day,
                    "permanent_security_id": f"S{asset}",
                    "factor": signal,
                    "forward_return_1d": signal * 0.001 + date_index * 0.00001,
                    "forward_return_5d": signal * 0.002,
                    "forward_return_10d": signal * 0.0015,
                    "forward_return_20d": signal * 0.0008,
                    "forward_return_40d": signal * 0.0002,
                    "forward_return_60d": -signal * 0.0001,
                    "forward_return_120d": -signal * 0.0002,
                    "sector": "A" if asset < 5 else "B",
                    "regime": "risk_on" if date_index < 9 else "neutral",
                }
            )
    return pd.DataFrame(rows)


def test_factor_evaluation_reports_ic_quantiles_turnover_and_decay() -> None:
    panel = _panel()
    result = evaluate_factor(
        panel,
        signal_column="factor",
        forward_return_column="forward_return_5d",
        horizon=5,
    )
    assert result.spearman_ic is not None and result.spearman_ic > 0.9
    assert result.icir is not None
    assert result.top_bottom_spread is not None and result.top_bottom_spread > 0
    assert result.turnover == 0
    assert result.sector_stability
    assert result.regime_stability
    decay = evaluate_ic_decay(panel, signal_column="factor")
    assert decay.peak_horizon in {1, 5, 10, 20, 40, 60, 120}
    assert decay.recommended_rebalance_horizon is not None
