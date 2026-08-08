from datetime import UTC, date, datetime, timedelta

import pandas as pd

from personal_alpha_terminal.quant_engine.backtest.backtrader_engine import BacktraderEngine
from personal_alpha_terminal.quant_engine.backtest.vectorbt_engine import VectorBTEngine
from personal_alpha_terminal.quant_engine.strategies.momentum_strategy import MomentumStrategy
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


def _authorization() -> ResearchDataAuthorization:
    decision_time = datetime(2026, 1, 1, tzinfo=UTC)
    request = ResearchDataRequest(
        purpose=ResearchPurpose.BACKTEST,
        market="US",
        asset_type="stock",
        start_date=date(2020, 1, 1),
        end_date=date(2025, 12, 31),
        decision_time=decision_time,
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="pit-us-test",
        maximum_age=timedelta(days=365),
    )
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="fixture",
        provider="fixture",
        source_ids=("fixture:certified",),
        latest_available_time=decision_time - timedelta(days=1),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="pit-us-test",
        universe_available_time=decision_time - timedelta(days=365),
        corporate_actions_complete=True,
        trading_calendar_complete=True,
        missing_rate=0,
        anomaly_rate=0,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.01,
        data_version="fixture-v1",
        allow_backtest=True,
        allow_display=True,
        allow_portfolio_decision=False,
        dual_source_verified=False,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=decision_time)


def _prices(count: int = 90) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=count)
    close = pd.Series(
        [100 + index_value * 0.35 + (index_value % 9 - 4) * 0.2 for index_value in range(count)],
        index=index,
    )
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]) * 1.001,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_vectorbt_ma_uses_risk_metrics_and_next_bar_execution() -> None:
    bars = _prices()
    result = VectorBTEngine().run_moving_average(
        authorization=_authorization(),
        close=bars["close"],
        execution_price=bars["open"],
        fast_window=5,
        slow_window=20,
    )

    assert result.performance.observations == len(bars) - 1
    assert result.performance.maximum_drawdown <= 0
    assert result.total_cost >= 0
    assert "T+1" in result.execution_policy


def test_vectorbt_optimizer_locks_selection_to_training_slice() -> None:
    bars = _prices(120)
    result = VectorBTEngine().optimize_moving_average(
        authorization=_authorization(),
        close=bars["close"],
        execution_price=bars["open"],
        windows=(3, 5, 10, 20),
    )

    assert result.candidates_evaluated > 1
    assert "validation not optimized" in result.selection_rule
    assert result.validation_result.performance.observations > 0


def test_backtrader_produces_auditable_next_bar_trade_log() -> None:
    result = BacktraderEngine().run(
        authorization=_authorization(),
        ticker="FIXTURE",
        bars=_prices(100),
        strategy=MomentumStrategy(lookback=5, exit_lookback=3),
    )

    assert result.performance.observations > 0
    assert result.trades
    assert all(item.reason.startswith("momentum:") for item in result.trades)
    assert "next bar" in result.execution_policy


def test_vectorbt_supports_precomputed_etf_or_factor_weights() -> None:
    bars = _prices(60)
    prices = pd.DataFrame({"ETF_A": bars["open"], "ETF_B": bars["open"] * 0.8})
    weights = pd.DataFrame(float("nan"), index=prices.index, columns=prices.columns)
    weights.loc[prices.index[10], :] = [0.6, 0.3]
    weights.loc[prices.index[40], :] = [0.2, 0.5]

    result = VectorBTEngine().run_target_weights(
        authorization=_authorization(),
        execution_prices=prices,
        target_weights=weights,
        strategy="etf_rotation",
    )

    assert result.parameters["assets"] == 2
    assert result.trade_count >= 2
    assert result.performance.maximum_drawdown <= 0
