from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import exchange_calendars as xcals
import pytest

from personal_alpha_terminal.backtest.schemas import BacktestBar, UniversePoint
from personal_alpha_terminal.quant_engine.backtest.production import (
    BacktestTarget,
    CorporateAction,
    CorporateActionType,
    ProductionBacktestConfig,
    ProductionBacktestDataset,
    ProductionBacktestEngine,
)
from personal_alpha_terminal.quant_engine.backtest.validation import (
    LockedParameters,
    RobustnessObservation,
    RobustnessScenario,
    TimeSeriesSplit,
    assess_robustness,
    build_walk_forward_folds,
)
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)


def _sessions(count: int = 25) -> tuple[date, ...]:
    calendar = xcals.get_calendar("XNYS")
    return tuple(
        item.date()
        for item in calendar.sessions_in_range("2024-01-02", "2024-04-30")[:count]
    )


def _bar(session: date, price: float, asset_id: int = 1) -> BacktestBar:
    from personal_alpha_terminal.core.market_time import market_close_utc

    close_time = market_close_utc(session, "US")
    return BacktestBar(
        asset_id=asset_id,
        symbol="AAA" if asset_id == 1 else "BBB",
        market="US",
        trade_date=session,
        open=price,
        high=price,
        low=price,
        close=price,
        adjusted_close=price,
        volume=10_000_000,
        source="fixture-primary",
        adjustment_method="point_in_time_total_return",
        provider="fixture",
        event_time=close_time,
        available_time=close_time + timedelta(minutes=5),
        ingested_time=close_time + timedelta(minutes=10),
        open_tradable=True,
    )


def _dataset(*, universe_certified: bool = True) -> ProductionBacktestDataset:
    sessions = _sessions()
    split_day = sessions[10]
    bars = tuple(
        _bar(session, 100.0 if session < split_day else 50.0) for session in sessions
    )
    universe = UniversePoint(
        1,
        sessions[0],
        datetime.combine(sessions[0], time(12), UTC),
        frozenset({1}),
        "fixture-universe",
    )
    actions = (
        CorporateAction(
            1,
            CorporateActionType.SPLIT,
            split_day,
            sessions[5],
            datetime.combine(sessions[5], time(20), UTC),
            ratio=2.0,
            source="fixture-action",
        ),
        CorporateAction(
            1,
            CorporateActionType.CASH_DIVIDEND,
            sessions[15],
            sessions[8],
            datetime.combine(sessions[8], time(20), UTC),
            cash_amount=1.0,
            source="fixture-action",
        ),
    )
    return ProductionBacktestDataset(
        bars,
        sessions,
        "fixture-verified-us-calendar",
        (universe,),
        actions,
        True,
        universe_certified,
        "data-v1",
    )


def _target(dataset: ProductionBacktestDataset) -> BacktestTarget:
    signal_time = datetime.combine(dataset.calendar[0], time(22), UTC)
    return BacktestTarget(
        signal_time,
        dataset.calendar[1],
        {1: 0.5},
        1,
        "data-v1",
        "alpha-portfolio-v1",
        "PRODUCTION_APPROVED",
        {1: {"Momentum": 0.6, "Quality": 0.4}},
        "fixture-parameter-lock",
        "fixture-oos-validation",
    )


def _engine() -> ProductionBacktestEngine:
    return ProductionBacktestEngine(
        TransactionCostModel(
            TransactionCostConfig(
                commission_bps=0,
                spread_bps=0,
                slippage_bps=0,
                impact_coefficient_bps=0,
                maximum_adv_participation=1,
            )
        )
    )


def test_raw_price_split_dividend_and_accounting_reconcile() -> None:
    dataset = _dataset()
    benchmark = tuple((session, 0.0) for session in dataset.calendar[1:])
    result = _engine().run(
        dataset,
        (_target(dataset),),
        ProductionBacktestConfig(
            initial_capital=100_000,
            benchmark_returns=benchmark,
            minimum_sessions=20,
            git_commit="fixture",
        ),
        sectors={1: "Technology"},
    )
    assert result.status == "PRODUCTION_APPROVED"
    assert result.trades[0].execution_date == dataset.calendar[1]
    assert result.trades[0].raw_price == 100
    assert result.dividends == pytest.approx(1_000)
    assert result.points[-1].equity == pytest.approx(101_000)
    assert result.realized_pnl == pytest.approx(0)
    assert result.unrealized_pnl == pytest.approx(0)
    assert result.metrics.net_return == pytest.approx(0.01)
    assert result.run_manifest_hash
    assert result.alpha_source_contribution


def test_transaction_costs_reduce_net_return_and_are_booked_in_pnl() -> None:
    dataset = _dataset()
    config = ProductionBacktestConfig(
        initial_capital=100_000,
        benchmark_returns=tuple((session, 0.0) for session in dataset.calendar[1:]),
        minimum_sessions=20,
        git_commit="fixture",
    )
    zero_cost = _engine().run(dataset, (_target(dataset),), config, sectors={1: "Technology"})
    costly = ProductionBacktestEngine(
        TransactionCostModel(
            TransactionCostConfig(
                commission_bps=5,
                spread_bps=10,
                slippage_bps=10,
                impact_coefficient_bps=20,
                maximum_adv_participation=1,
            )
        )
    ).run(dataset, (_target(dataset),), config, sectors={1: "Technology"})
    assert costly.transaction_costs > 0
    assert costly.metrics.transaction_cost == pytest.approx(costly.transaction_costs)
    assert costly.metrics.net_return < zero_cost.metrics.net_return
    assert costly.metrics.gross_return > costly.metrics.net_return


def test_exit_trade_realized_pnl_and_holding_period_reconcile() -> None:
    dataset = _dataset()
    exit_signal_date = dataset.calendar[17]
    exit_target = BacktestTarget(
        datetime.combine(exit_signal_date, time(22), UTC),
        dataset.calendar[18],
        {},
        1,
        "data-v1",
        "alpha-portfolio-v1",
        "PRODUCTION_APPROVED",
        {},
        "fixture-parameter-lock",
        "fixture-oos-validation",
    )
    result = _engine().run(
        dataset,
        (_target(dataset), exit_target),
        ProductionBacktestConfig(
            initial_capital=100_000,
            benchmark_returns=tuple((session, 0.0) for session in dataset.calendar[1:]),
            minimum_sessions=20,
            git_commit="fixture",
        ),
        sectors={1: "Technology"},
    )
    assert len(result.trades) == 2
    assert result.trades[-1].shares < 0
    assert result.metrics.average_holding_period == pytest.approx(17)
    assert result.points[-1].equity == pytest.approx(
        100_000 + result.realized_pnl + result.unrealized_pnl + result.dividends
    )


def test_survivorship_risk_is_explicit_and_action_ledger_fails_closed() -> None:
    dataset = _dataset(universe_certified=False)
    result = _engine().run(
        dataset,
        (_target(dataset),),
        ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
        sectors={1: "Technology"},
    )
    assert result.status == "RESEARCH_ONLY"
    assert "SURVIVORSHIP_BIAS_RISK" in result.limitations
    assert "BENCHMARK_TOTAL_RETURN_COVERAGE_INCOMPLETE" in result.limitations
    with pytest.raises(ValueError, match="corporate-action ledger"):
        _engine().run(
            replace(dataset, corporate_action_ledger_certified=False),
            (_target(dataset),),
            ProductionBacktestConfig(minimum_sessions=20),
            sectors={1: "Technology"},
        )


def test_same_bar_target_and_unavailable_universe_are_rejected() -> None:
    dataset = _dataset()
    target = _target(dataset)
    with pytest.raises(ValueError, match="after the signal date"):
        replace(target, earliest_execution_date=target.signal_time.date())
    late_universe = replace(
        dataset.universe_timeline[0],
        available_at=target.signal_time + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="unavailable PIT universe"):
        _engine().run(
            replace(dataset, universe_timeline=(late_universe,)),
            (target,),
            ProductionBacktestConfig(minimum_sessions=20),
            sectors={1: "Technology"},
        )


def test_calendar_holiday_and_pre_close_signal_are_rejected() -> None:
    dataset = _dataset()
    holiday = date(2024, 1, 15)
    invalid_calendar = tuple(sorted((*dataset.calendar, holiday)))
    with pytest.raises(ValueError, match="non-exchange sessions"):
        _engine().run(
            replace(dataset, calendar=invalid_calendar),
            (_target(dataset),),
            ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
            sectors={1: "Technology"},
        )


def test_price_policy_data_version_and_provider_stitching_fail_closed() -> None:
    dataset = _dataset()
    with pytest.raises(ValueError, match="raw, unadjusted"):
        _engine().run(
            replace(dataset, execution_price_policy="ADJUSTED_CLOSE"),
            (_target(dataset),),
            ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
            sectors={1: "Technology"},
        )
    with pytest.raises(ValueError, match="versions do not match"):
        _engine().run(
            dataset,
            (replace(_target(dataset), data_version="other-data"),),
            ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
            sectors={1: "Technology"},
        )
    stitched_bar = replace(dataset.bars[-1], provider="other-provider")
    with pytest.raises(ValueError, match="provider stitching"):
        _engine().run(
            replace(dataset, bars=(*dataset.bars[:-1], stitched_bar)),
            (_target(dataset),),
            ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
            sectors={1: "Technology"},
        )
    target = replace(
        _target(dataset),
        signal_time=datetime.combine(dataset.calendar[0], time(19), UTC),
    )
    with pytest.raises(ValueError, match="before the signal-session close"):
        _engine().run(
            dataset,
            (target,),
            ProductionBacktestConfig(minimum_sessions=20, git_commit="fixture"),
            sectors={1: "Technology"},
        )


def test_walk_forward_lock_and_robustness_status() -> None:
    split = TimeSeriesSplit(
        date(2010, 1, 1),
        date(2017, 12, 31),
        date(2018, 1, 1),
        date(2019, 12, 31),
        date(2020, 1, 1),
        date(2022, 12, 31),
    )
    assert split.test_start > split.validation_end
    locked = LockedParameters(
        {"risk_aversion": 3.0},
        (split.train_start, split.train_end),
        (split.validation_start, split.validation_end),
        True,
    )
    locked.require_untouched(locked.fingerprint)
    with pytest.raises(RuntimeError, match="locked"):
        locked.require_untouched("changed")
    observations = (
        RobustnessObservation(RobustnessScenario("base"), 0.20, -0.10, 1.0),
        RobustnessObservation(RobustnessScenario("parameter-20", 0.8), 0.17, -0.12, 0.8),
        RobustnessObservation(RobustnessScenario("parameter-10", 0.9), 0.19, -0.11, 0.9),
        RobustnessObservation(RobustnessScenario("parameter+10", 1.1), 0.18, -0.12, 0.8),
        RobustnessObservation(RobustnessScenario("parameter+20", 1.2), 0.16, -0.13, 0.7),
        RobustnessObservation(
            RobustnessScenario("higher-spread", spread_multiplier=2),
            0.16,
            -0.12,
            0.7,
        ),
        RobustnessObservation(
            RobustnessScenario("delay", execution_delay_sessions=1),
            0.05,
            -0.20,
            0.2,
        ),
    )
    assessment = assess_robustness(observations)
    assert assessment.status == "UNSTABLE"
    assert "delay" in assessment.failed_scenarios


def test_walk_forward_folds_are_chronological_embargoed_and_repeatable() -> None:
    sessions = _sessions(25)
    folds = build_walk_forward_folds(
        sessions,
        train_sessions=8,
        validation_sessions=4,
        test_sessions=4,
        step_sessions=4,
        embargo_sessions=1,
    )
    repeated = build_walk_forward_folds(
        sessions,
        train_sessions=8,
        validation_sessions=4,
        test_sessions=4,
        step_sessions=4,
        embargo_sessions=1,
    )
    assert folds == repeated
    assert len(folds) >= 2
    assert all(item.parameter_lock_required for item in folds)
    assert all(
        item.split.train_end < item.split.validation_start < item.split.test_start
        for item in folds
    )
    with pytest.raises(ValueError, match="sorted and unique"):
        build_walk_forward_folds(
            (*sessions, sessions[-1]),
            train_sessions=8,
            validation_sessions=4,
            test_sessions=4,
            step_sessions=4,
        )
