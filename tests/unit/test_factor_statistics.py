from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorBacktestPeriodResult,
    FactorDataset,
    FactorFinancialPoint,
    FactorPricePoint,
)
from personal_alpha_terminal.analysis.factors.statistics import (
    calculate_factor_scores,
    summarize_backtest,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


def asset(
    instrument_id: int,
    symbol: str,
    *,
    pe: float,
    growth: float,
    roe: float,
    daily_return: float,
) -> FactorAssetData:
    prices: list[FactorPricePoint] = []
    close = 100.0
    for index in range(40):
        close *= 1 + daily_return + ((index % 3) - 1) / 10000
        prices.append(
            FactorPricePoint(
                date=date(2025, 1, 1) + timedelta(days=index),
                close=close,
            )
        )
    prior_revenue = 100.0
    prior_eps = 2.0
    financials = (
        FactorFinancialPoint(
            period_end=date(2023, 12, 31),
            period_type="annual",
            available_at=datetime(2024, 2, 1, tzinfo=UTC),
            revenue=prior_revenue,
            free_cash_flow=10,
            roe=roe - 0.02,
            roic=roe - 0.03,
            pe=pe + 2,
            pb=pe / 10 + 0.2,
            eps=prior_eps,
            shares_outstanding=10,
        ),
        FactorFinancialPoint(
            period_end=date(2024, 12, 31),
            period_type="annual",
            available_at=datetime(2025, 1, 15, tzinfo=UTC),
            revenue=prior_revenue * (1 + growth),
            free_cash_flow=10 * (1 + growth),
            roe=roe,
            roic=roe - 0.01,
            pe=pe,
            pb=pe / 10,
            eps=prior_eps * (1 + growth),
            shares_outstanding=10,
        ),
    )
    return FactorAssetData(
        instrument=GraphInstrument(
            id=instrument_id,
            key=f"stock:{instrument_id}",
            symbol=symbol,
            name=symbol,
            market="US",
            asset_type="stock",
            industry=None,
        ),
        prices=tuple(prices),
        financials=financials,
    )


def test_factor_score_rewards_value_growth_quality_momentum_and_low_volatility() -> None:
    dataset = FactorDataset(
        assets=(
            asset(1, "BEST", pe=10, growth=0.3, roe=0.25, daily_return=0.004),
            asset(2, "MID", pe=20, growth=0.15, roe=0.15, daily_return=0.002),
            asset(3, "WORST", pe=30, growth=0.02, roe=0.05, daily_return=-0.001),
        )
    )

    scores = calculate_factor_scores(
        dataset,
        as_of_date=date(2025, 2, 9),
        momentum_lookback=20,
        momentum_skip=2,
        volatility_window=10,
        minimum_categories=3,
    )

    assert [item.instrument.symbol for item in scores] == ["BEST", "MID", "WORST"]
    assert scores[0].factor_score > scores[-1].factor_score
    assert scores[0].normalized_factors["pe"] == pytest.approx(100)
    assert scores[0].normalized_factors["revenue_growth"] == pytest.approx(100)


def test_backtest_summary_compounds_and_reports_drawdown() -> None:
    instrument = asset(
        1,
        "BEST",
        pe=10,
        growth=0.3,
        roe=0.25,
        daily_return=0.004,
    ).instrument
    periods = (
        FactorBacktestPeriodResult(
            date(2025, 1, 1),
            date(2025, 1, 31),
            (instrument,),
            0.10,
            0.05,
            0.05,
        ),
        FactorBacktestPeriodResult(
            date(2025, 2, 1),
            date(2025, 2, 28),
            (instrument,),
            -0.05,
            -0.02,
            -0.03,
        ),
    )

    summary = summarize_backtest(
        periods,
        holding_period=21,
        annual_risk_free_rate=0,
    )

    assert summary.cumulative_return == pytest.approx(0.045)
    assert summary.max_drawdown == pytest.approx(-0.05)
    assert summary.excess_hit_rate == pytest.approx(0.5)


def test_factor_snapshot_excludes_financials_unavailable_as_of_date() -> None:
    original = asset(
        1,
        "POINT_IN_TIME",
        pe=12,
        growth=0.2,
        roe=0.2,
        daily_return=0.001,
    )
    future_financial = replace(
        original.financials[-1],
        available_at=datetime(2025, 2, 9, 23, tzinfo=UTC),
        pe=1.0,
        pb=0.1,
        roe=0.9,
    )
    dataset = FactorDataset(
        assets=(
            replace(
                original,
                financials=(original.financials[0], future_financial),
            ),
        )
    )

    scores = calculate_factor_scores(
        dataset,
        as_of_date=date(2025, 2, 9),
        momentum_lookback=20,
        momentum_skip=2,
        volatility_window=10,
        minimum_categories=1,
    )

    assert len(scores) == 1
    assert scores[0].raw_factors["pe"] == original.financials[0].pe
    assert scores[0].raw_factors["roe"] == original.financials[0].roe


def test_fcf_yield_uses_raw_close_not_adjusted_return_price() -> None:
    original = asset(
        1,
        "VALUATION",
        pe=12,
        growth=0.2,
        roe=0.2,
        daily_return=0.001,
    )
    latest_price = original.prices[-1]
    adjusted_asset = replace(
        original,
        prices=(
            *original.prices[:-1],
            replace(
                latest_price,
                close=50.0,
                raw_close=100.0,
            ),
        ),
    )

    scores = calculate_factor_scores(
        FactorDataset(assets=(adjusted_asset,)),
        as_of_date=latest_price.date,
        momentum_lookback=20,
        momentum_skip=2,
        volatility_window=10,
        minimum_categories=1,
    )

    expected = original.financials[-1].free_cash_flow / (
        100.0 * original.financials[-1].shares_outstanding
    )
    assert scores[0].raw_factors["fcf_yield"] == pytest.approx(expected)
