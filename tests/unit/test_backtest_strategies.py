from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    EventSignal,
    FactorSnapshot,
    StrategyContext,
)
from personal_alpha_terminal.backtest.strategy import (
    ETFAllocationStrategy,
    EventFollowStrategy,
    FactorQuantileStrategy,
    RotationStrategy,
)
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps


def _history(asset_id: int, multiplier: float) -> tuple[BacktestBar, ...]:
    output: list[BacktestBar] = []
    close = 100.0
    for offset in range(90):
        close *= multiplier
        trade_date = date(2024, 1, 1) + timedelta(days=offset)
        timestamps = daily_bar_timestamps(trade_date, "US")
        output.append(
            BacktestBar(
                asset_id=asset_id,
                symbol=f"S{asset_id}",
                market="US",
                trade_date=trade_date,
                open=close,
                high=close,
                low=close,
                close=close,
                adjusted_close=close,
                volume=100,
                source="test",
                adjustment_method="point_in_time_total_return",
                provider="fixture",
                event_time=timestamps.event_time,
                available_time=timestamps.available_time,
                ingested_time=timestamps.ingested_time,
                open_tradable=True,
            )
        )
    return tuple(output)


def _context() -> StrategyContext:
    history = {
        1: _history(1, 1.003),
        2: _history(2, 1.002),
        3: _history(3, 1.001),
        4: _history(4, 0.999),
        5: _history(5, 0.998),
    }
    calendar = tuple(item.trade_date for item in history[1])
    decision_cutoffs = {item: datetime.combine(item, datetime.max.time(), UTC) for item in calendar}
    return StrategyContext(
        signal_date=calendar[-1],
        signal_cutoff=datetime.combine(calendar[-1], datetime.max.time(), UTC),
        calendar=calendar,
        decision_cutoffs=decision_cutoffs,
        history=history,
        current_weights={},
    )


def test_factor_strategy_uses_latest_nonfuture_snapshot() -> None:
    context = _context()
    snapshots = (
        FactorSnapshot(
            as_of_date=context.signal_date - timedelta(days=1),
            available_at=context.signal_cutoff - timedelta(days=1),
            values={1: 1, 2: 2, 3: 3, 4: 4, 5: 5},
            source="point_in_time_fixture",
        ),
        FactorSnapshot(
            as_of_date=context.signal_date + timedelta(days=1),
            available_at=context.signal_cutoff + timedelta(days=1),
            values={1: 100, 2: 0, 3: 0, 4: 0, 5: 0},
            source="future_fixture",
        ),
    )
    allocation = FactorQuantileStrategy(
        factor_name="roe",
        factor_snapshots=snapshots,
        top_quantile=0.20,
        minimum_assets=5,
    ).generate_targets(context)

    assert allocation is not None
    assert allocation.weights == {5: 1.0}
    assert "factor_as_of=2024-03-29" in allocation.rationale


def test_factor_strategy_rejects_late_published_same_date_snapshot() -> None:
    context = _context()
    strategy = FactorQuantileStrategy(
        factor_name="roe",
        factor_snapshots=(
            FactorSnapshot(
                as_of_date=context.signal_date,
                available_at=context.signal_cutoff + timedelta(seconds=1),
                values={1: 5, 2: 4, 3: 3, 4: 2, 5: 1},
                source="late_fixture",
            ),
        ),
        minimum_assets=5,
    )

    assert strategy.generate_targets(context) is None


def test_event_strategy_filters_events_by_availability_time() -> None:
    context = _context()
    late = EventSignal(
        event_date=context.signal_date,
        available_at=context.signal_cutoff + timedelta(seconds=1),
        source_asset_id=1,
        target_asset_id=2,
        event_type="price_jump",
        description="late revision",
    )
    strategy = EventFollowStrategy(events=(late,))
    assert strategy.generate_targets(context) is None

    known = EventSignal(
        event_date=context.signal_date,
        available_at=context.signal_cutoff - timedelta(seconds=1),
        source_asset_id=1,
        target_asset_id=2,
        event_type="price_jump",
        description="known",
    )
    allocation = EventFollowStrategy(events=(known,)).generate_targets(context)
    assert allocation is not None
    assert allocation.weights == {2: 1.0}


def test_rotation_selects_strongest_group() -> None:
    allocation = RotationStrategy(
        group_by_asset={1: "A", 2: "A", 3: "B", 4: "B", 5: "C"},
        lookback_sessions=20,
        top_groups=1,
    ).generate_targets(_context())

    assert allocation is not None
    assert allocation.weights == pytest.approx({1: 0.5, 2: 0.5})


def test_etf_allocation_uses_momentum_then_inverse_volatility() -> None:
    allocation = ETFAllocationStrategy(
        asset_ids=(1, 2, 3, 4),
        momentum_sessions=20,
        volatility_sessions=10,
        top_k=2,
    ).generate_targets(_context())

    assert allocation is not None
    assert set(allocation.weights) == {1, 2}
    assert sum(allocation.weights.values()) == pytest.approx(1.0)
