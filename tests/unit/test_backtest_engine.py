from dataclasses import dataclass, replace
from datetime import date, timedelta

import pytest

from personal_alpha_terminal.backtest.engine import BacktestEngine
from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    StrategyContext,
    TargetAllocation,
)
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps


@dataclass(frozen=True)
class FirstSignalStrategy:
    signal_date: date
    asset_id: int = 1

    @property
    def name(self) -> str:
        return "first_signal"

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        if context.signal_date != self.signal_date:
            return None
        return TargetAllocation(
            weights={self.asset_id: 1.0},
            rationale=("test_signal",),
        )

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "first_signal",
            "signal_date": self.signal_date.isoformat(),
            "asset_id": self.asset_id,
        }


@dataclass(frozen=True)
class AvailabilityProbeStrategy:
    """Trade only if a second asset is visible at the decision cutoff."""

    signal_date: date

    @property
    def name(self) -> str:
        return "availability_probe"

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        if context.signal_date != self.signal_date or 2 not in context.history:
            return None
        return TargetAllocation(weights={1: 1.0}, rationale=("future_data_visible",))

    def audit_payload(self) -> dict[str, object]:
        return {"type": "availability_probe", "signal_date": self.signal_date.isoformat()}


def _bar(
    offset: int,
    *,
    asset_id: int = 1,
    open_price: float = 100.0,
    close: float = 100.0,
    source: str = "test",
    adjusted_close: float | None = None,
) -> BacktestBar:
    trade_date = date(2024, 1, 2) + timedelta(days=offset)
    timestamps = daily_bar_timestamps(trade_date, "US")
    return BacktestBar(
        asset_id=asset_id,
        symbol=f"S{asset_id}",
        market="US",
        trade_date=trade_date,
        open=open_price,
        high=max(open_price, close),
        low=min(open_price, close),
        close=close,
        adjusted_close=close if adjusted_close is None else adjusted_close,
        volume=1_000_000,
        source=source,
        adjustment_method="point_in_time_total_return",
        provider="fixture",
        event_time=timestamps.event_time,
        available_time=timestamps.available_time,
        ingested_time=timestamps.ingested_time,
        open_tradable=True,
    )


def _config(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = {
        "start_date": date(2024, 1, 2),
        "end_date": date(2024, 2, 20),
        "rebalance_frequency": "daily",
        "initial_capital": 1_000.0,
        "commission_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
        "minimum_sessions": 2,
        "liquidity_lookback_sessions": 2,
        "minimum_liquidity_observations": 1,
        "maximum_adv_participation": 1.0,
    }
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def _dataset(
    bars: tuple[BacktestBar, ...],
    sources: tuple[str, ...] = ("synthetic:manual",),
) -> BacktestDataset:
    return BacktestDataset(
        "US",
        bars,
        sources,
        calendar=tuple(sorted({item.trade_date for item in bars})),
        calendar_source="test_verified_calendar",
    )


def test_close_signal_executes_only_at_next_session_open() -> None:
    bars = (
        _bar(0, open_price=100, close=100),
        _bar(1, open_price=50, close=100),
        _bar(2, open_price=100, close=100),
    )
    result = BacktestEngine().run(
        _dataset(bars),
        FirstSignalStrategy(date(2024, 1, 2)),
        _config(),
    )

    assert result.points[0].nav == pytest.approx(1_000)
    assert result.rebalances[0].signal_date == date(2024, 1, 2)
    assert result.rebalances[0].execution_date == date(2024, 1, 3)
    assert result.points[1].nav == pytest.approx(2_000)


def test_bar_published_after_decision_cutoff_cannot_influence_signal() -> None:
    ordinary = tuple(_bar(offset, asset_id=1) for offset in range(3))
    delayed = _bar(0, asset_id=2)
    assert delayed.available_time is not None
    future_available = delayed.available_time + timedelta(days=1)
    delayed = replace(
        delayed,
        available_time=future_available,
        ingested_time=future_available,
    )
    dataset = _dataset((*ordinary, delayed))

    result = BacktestEngine().run(
        dataset,
        AvailabilityProbeStrategy(date(2024, 1, 2)),
        _config(),
    )

    assert result.rebalances == ()


def test_proportional_cost_solver_reconciles_post_cost_nav() -> None:
    bars = tuple(_bar(offset) for offset in range(3))
    config = _config(commission_bps=100.0)
    result = BacktestEngine().run(
        _dataset(bars),
        FirstSignalStrategy(date(2024, 1, 2)),
        config,
    )

    rebalance = result.rebalances[0]
    assert rebalance.nav_after == pytest.approx(1_000 / 1.01)
    assert rebalance.transaction_cost == pytest.approx(rebalance.nav_after * 0.01)
    assert rebalance.nav_before == pytest.approx(rebalance.nav_after + rebalance.transaction_cost)
    assert result.metrics.total_transaction_cost == pytest.approx(rebalance.transaction_cost)


def test_duplicate_bars_and_provider_stitching_are_rejected() -> None:
    duplicate = _bar(0)
    dataset = BacktestDataset(
        "US",
        (duplicate, duplicate, _bar(1)),
        ("synthetic:manual",),
        calendar=(duplicate.trade_date, _bar(1).trade_date),
    )
    with pytest.raises(ValueError, match="duplicate asset/date"):
        BacktestEngine().run(
            dataset,
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )

    stitched = BacktestDataset(
        "US",
        (_bar(0, source="a"), _bar(1, source="b")),
        ("synthetic:manual",),
        calendar=(_bar(0).trade_date, _bar(1).trade_date),
    )
    with pytest.raises(ValueError, match="provider stitching"):
        BacktestEngine().run(
            stitched,
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )


def test_invalid_ohlc_and_missing_adjusted_price_are_rejected() -> None:
    invalid = replace(_bar(0), high=99, low=90)
    with pytest.raises(ValueError, match="inconsistent OHLC"):
        BacktestEngine().run(
            _dataset((invalid, _bar(1)), ("synthetic",)),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )

    missing_adjusted = (
        _bar(0),
        replace(_bar(1), adjusted_close=None),
    )
    with pytest.raises(ValueError, match="adjusted close required"):
        BacktestEngine().run(
            _dataset(missing_adjusted, ("synthetic",)),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )


def test_current_provider_adjustment_is_rejected_for_point_in_time_backtest() -> None:
    unsafe = replace(
        _bar(0),
        adjustment_method="yahoo_provider_total_return_current_snapshot",
    )

    with pytest.raises(ValueError, match="point-in-time total-return"):
        BacktestEngine().run(
            _dataset((unsafe, _bar(1)), ("synthetic",)),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )


def test_missing_three_time_provenance_is_rejected() -> None:
    missing = replace(_bar(0), available_time=None)
    with pytest.raises(ValueError, match="three-time data contract"):
        BacktestEngine().run(
            _dataset((missing, _bar(1)), ("synthetic",)),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )


def test_monthly_schedule_uses_completed_period_boundary_only() -> None:
    dates = (
        date(2024, 1, 30),
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 2),
    )
    bars = tuple(
        replace(
            _bar(0),
            trade_date=item,
            event_time=daily_bar_timestamps(item, "US").event_time,
            available_time=daily_bar_timestamps(item, "US").available_time,
            ingested_time=daily_bar_timestamps(item, "US").ingested_time,
        )
        for item in dates
    )
    result = BacktestEngine().run(
        _dataset(bars, ("synthetic",)),
        FirstSignalStrategy(date(2024, 1, 31)),
        _config(
            start_date=dates[0],
            end_date=dates[-1],
            rebalance_frequency="monthly",
        ),
    )

    assert len(result.rebalances) == 1
    assert result.rebalances[0].signal_date == date(2024, 1, 31)
    assert result.rebalances[0].execution_date == date(2024, 2, 1)


def test_unverified_calendar_is_blocked_and_empty_verified_session_is_rejected() -> None:
    bars = (_bar(0), _bar(1))
    with pytest.raises(ValueError, match="verified trading calendar"):
        BacktestEngine().run(
            BacktestDataset("US", bars, ("synthetic",)),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )

    with pytest.raises(ValueError, match="source provenance"):
        BacktestEngine().run(
            BacktestDataset(
                "US",
                bars,
                ("synthetic",),
                calendar=(date(2024, 1, 2), date(2024, 1, 3)),
            ),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )

    with pytest.raises(ValueError, match="sessions with no asset bars"):
        BacktestEngine().run(
            BacktestDataset(
                "US",
                bars,
                ("synthetic",),
                calendar=(
                    date(2024, 1, 2),
                    date(2024, 1, 3),
                    date(2024, 1, 4),
                ),
                calendar_source="test_verified_calendar",
            ),
            FirstSignalStrategy(date(2024, 1, 2)),
            _config(),
        )


def test_weekend_session_is_rejected_even_when_caller_labels_calendar_verified() -> None:
    friday = replace(
        _bar(0),
        trade_date=date(2024, 1, 5),
        event_time=daily_bar_timestamps(date(2024, 1, 5), "US").event_time,
        available_time=daily_bar_timestamps(date(2024, 1, 5), "US").available_time,
        ingested_time=daily_bar_timestamps(date(2024, 1, 5), "US").ingested_time,
    )
    saturday = replace(
        _bar(1),
        trade_date=date(2024, 1, 6),
        event_time=daily_bar_timestamps(date(2024, 1, 6), "US").event_time,
        available_time=daily_bar_timestamps(date(2024, 1, 6), "US").available_time,
        ingested_time=daily_bar_timestamps(date(2024, 1, 6), "US").ingested_time,
    )
    with pytest.raises(ValueError, match="weekend"):
        BacktestEngine().run(
            BacktestDataset(
                "US",
                (friday, saturday),
                ("synthetic",),
                calendar=(friday.trade_date, saturday.trade_date),
                calendar_source="claimed_verified",
            ),
            FirstSignalStrategy(friday.trade_date),
            _config(),
        )


def test_unconfirmed_open_and_excessive_adv_participation_reject_trades() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    unconfirmed = (bars[0], replace(bars[1], open_tradable=None), bars[2])
    result = BacktestEngine().run(
        _dataset(unconfirmed),
        FirstSignalStrategy(date(2024, 1, 2)),
        _config(),
    )
    assert result.rebalances[0].status == "rejected"
    assert "tradability" in (result.rebalances[0].rejection_reason or "")

    low_volume = tuple(replace(item, volume=1) for item in bars)
    result = BacktestEngine().run(
        _dataset(low_volume),
        FirstSignalStrategy(date(2024, 1, 3)),
        _config(
            minimum_liquidity_observations=2,
            maximum_adv_participation=0.05,
        ),
    )
    assert result.rebalances[0].status == "rejected"
    assert "liquidity" in (result.rebalances[0].rejection_reason or "")
