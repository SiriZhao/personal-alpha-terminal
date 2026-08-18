from __future__ import annotations

from datetime import UTC, datetime, time

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.alpha_engine3 import (
    AlphaEngine3Config,
    AlphaEngine3Verdict,
    AlphaModelKind,
    build_forward_labels,
    build_price_feature_panel,
    build_walk_forward_folds,
    evaluate_alpha_engine3,
    evaluate_feature_ablation,
)

FEATURES = (
    "momentum_21",
    "trend_slope_63",
    "realized_volatility_21",
    "size_score",
    "sector_relative_strength_63",
)


def _price_panel(*, periods: int = 260, securities: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(6201)
    sessions = pd.bdate_range("2024-01-02", periods=periods)
    market = rng.normal(0.0003, 0.008, periods)
    rows: list[dict[str, object]] = []
    symbols = ("SPY", *(f"S{index:02d}" for index in range(securities)))
    for offset, symbol in enumerate(symbols):
        shocks = market if symbol == "SPY" else (
            0.85 * market
            + rng.normal(0.00005 * (offset - securities / 2), 0.008, periods)
        )
        close = 100.0 * np.cumprod(1 + shocks)
        for session, value in zip(sessions, close, strict=True):
            rows.append(
                {
                    "permanent_security_id": f"US:XNAS:{symbol}",
                    "ticker": symbol,
                    "trade_date": session.date(),
                    "available_time": datetime.combine(
                        session.date(), time(20, 30), tzinfo=UTC
                    ),
                    "close": float(value),
                    "volume": float(900_000 + 20_000 * offset),
                    "sector": "TECH" if offset % 2 else "INDUSTRIAL",
                    "industry": f"I{offset % 4}",
                    "cluster": f"C{offset % 3}",
                    "market_cap": float(2_000_000_000 + offset * 100_000_000),
                }
            )
    return pd.DataFrame(rows)


def _labeled_panel(*, securities: int = 28) -> pd.DataFrame:
    rng = np.random.default_rng(6202)
    sessions = pd.bdate_range("2020-01-02", periods=420)
    decision_positions = tuple(range(100, 300, 5))
    rows: list[dict[str, object]] = []
    for horizon in (5, 21, 63):
        for position in decision_positions:
            as_of = sessions[position]
            label_end = sessions[position + horizon]
            regime = "RISK_ON" if position % 20 < 10 else "NEUTRAL"
            for index in range(securities):
                momentum = rng.normal()
                trend = 0.60 * momentum + rng.normal(0, 0.80)
                volatility = abs(rng.normal(0.9, 0.35))
                size = rng.normal()
                sector_relative = rng.normal()
                latent = (
                    0.018 * momentum
                    + 0.010 * trend
                    - 0.008 * volatility
                    + 0.004 * sector_relative
                )
                scale = horizon / 21
                forward = latent * scale + rng.normal(0, 0.018 * np.sqrt(scale))
                champion = 0.006 * momentum + 0.003 * trend - 0.002 * volatility
                rows.append(
                    {
                        "permanent_security_id": f"US:XNAS:S{index:03d}",
                        "ticker": f"S{index:03d}",
                        "as_of_date": as_of.date(),
                        "decision_cutoff": datetime.combine(
                            as_of.date(), time(21, 0), tzinfo=UTC
                        ),
                        "feature_available_at": datetime.combine(
                            as_of.date(), time(20, 30), tzinfo=UTC
                        ),
                        "label_end_date": label_end.date(),
                        "horizon_sessions": horizon,
                        "forward_excess_return": forward,
                        "champion_expected_excess_return": champion,
                        "momentum_21": momentum,
                        "trend_slope_63": trend,
                        "realized_volatility_21": volatility,
                        "size_score": size,
                        "sector_relative_strength_63": sector_relative,
                        "sector": f"SECTOR_{index % 4}",
                        "regime": regime,
                    }
                )
    return pd.DataFrame(rows)


def _config() -> AlphaEngine3Config:
    return AlphaEngine3Config(
        minimum_train_dates=14,
        test_dates_per_fold=8,
        embargo_dates=1,
        minimum_training_rows=100,
        minimum_test_rows=80,
        bootstrap_samples=100,
    )


def test_price_features_are_as_of_and_future_poison_invariant() -> None:
    prices = _price_panel()
    sessions = tuple(sorted(set(pd.to_datetime(prices["trade_date"]).dt.date)))
    cutoff_date = sessions[150]
    cutoff = datetime.combine(cutoff_date, time(21, 0), tzinfo=UTC)
    baseline = build_price_feature_panel(
        prices,
        decision_cutoffs=(cutoff,),
        benchmark_symbol="SPY",
        config=AlphaEngine3Config(minimum_history=64),
    )
    poisoned = prices.copy()
    poisoned.loc[
        (poisoned["ticker"] == "S00")
        & (pd.to_datetime(poisoned["trade_date"]).dt.date > cutoff_date),
        "close",
    ] = 10_000_000.0
    changed = build_price_feature_panel(
        poisoned,
        decision_cutoffs=(cutoff,),
        benchmark_symbol="SPY",
        config=AlphaEngine3Config(minimum_history=64),
    )
    pd.testing.assert_frame_equal(baseline.frame, changed.frame)
    assert "momentum_21" in baseline.enabled_features
    assert "adv_20" in baseline.enabled_features
    assert "fundamental:profitability" in baseline.disabled_features
    assert not baseline.fundamentals_pit_safe


def test_forward_labels_start_next_session_and_keep_feature_timestamp() -> None:
    prices = _price_panel()
    sessions = tuple(sorted(set(pd.to_datetime(prices["trade_date"]).dt.date)))
    cutoff_date = sessions[150]
    cutoff = datetime.combine(cutoff_date, time(21, 0), tzinfo=UTC)
    features = build_price_feature_panel(
        prices,
        decision_cutoffs=(cutoff,),
        benchmark_symbol="SPY",
        config=AlphaEngine3Config(minimum_history=64),
    )
    labels = build_forward_labels(
        prices,
        features,
        benchmark_symbol="SPY",
        horizons=(5, 21),
    )
    assert set(labels["horizon_sessions"]) == {5, 21}
    assert set(labels["label_entry_date"]) == {sessions[151]}
    assert bool((labels["feature_available_at"] <= labels["decision_cutoff"]).all())
    assert bool((labels["label_end_date"] > labels["as_of_date"]).all())


def test_walk_forward_purges_overlapping_labels_and_applies_embargo() -> None:
    panel = _labeled_panel()
    folds = build_walk_forward_folds(
        panel,
        horizon_sessions=63,
        config=_config(),
    )
    assert folds
    horizon = panel.loc[panel["horizon_sessions"] == 63].copy()
    for fold in folds:
        train = horizon.loc[horizon["as_of_date"].isin(fold.train_dates)]
        assert max(train["label_end_date"]) < min(fold.test_dates)
        assert fold.purged_rows > 0


def test_all_challengers_run_but_uncertified_data_cannot_promote() -> None:
    evaluation = evaluate_alpha_engine3(
        _labeled_panel(),
        feature_columns=FEATURES,
        manifest=None,
        config=_config(),
        locked_oos=False,
    )
    assert evaluation.verdict is AlphaEngine3Verdict.BLOCKED_DATA_QUALITY
    assert "CERTIFIED_RESEARCH_MANIFEST_REQUIRED" in evaluation.blockers
    assert "LOCKED_OOS_NOT_FROZEN" in evaluation.blockers
    assert evaluation.selected_challenger is not None
    assert len(evaluation.evidence) == 18
    assert all(item.supported for item in evaluation.evidence)
    assert all(item.calibration for item in evaluation.evidence)
    ridge = next(
        item
        for item in evaluation.evidence
        if item.model is AlphaModelKind.RIDGE and item.horizon_sessions == 21
    )
    assert ridge.rank_ic is not None and ridge.rank_ic > 0
    assert ridge.maximum_positive_candidates is not None
    assert ridge.maximum_positive_candidates > 10
    assert set(ridge.attribution) == set(FEATURES)


def test_feature_ablation_is_deterministic_and_identifies_signal_value() -> None:
    panel = _labeled_panel()
    first = evaluate_feature_ablation(
        panel,
        model=AlphaModelKind.RIDGE,
        horizon_sessions=21,
        feature_columns=FEATURES,
        config=_config(),
    )
    second = evaluate_feature_ablation(
        panel,
        model=AlphaModelKind.RIDGE,
        horizon_sessions=21,
        feature_columns=FEATURES,
        config=_config(),
    )
    assert first == second
    momentum = next(item for item in first if item.feature == "momentum_21")
    assert momentum.rank_ic_delta is not None
    assert momentum.rank_ic_delta > 0


def test_future_feature_timestamp_fails_closed() -> None:
    panel = _labeled_panel()
    panel.loc[0, "feature_available_at"] = datetime(2099, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="feature timestamp follows decision cutoff"):
        evaluate_alpha_engine3(
            panel,
            feature_columns=FEATURES,
            manifest=None,
            config=_config(),
        )
