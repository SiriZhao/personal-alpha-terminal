from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.alpha_discovery.factor_generator import (
    FACTOR_BY_NAME,
    generate_factor_panel,
)
from personal_alpha_terminal.alpha_discovery.schemas import MarketEnvironmentPoint
from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorDataset,
    FactorFinancialPoint,
    FactorPricePoint,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


def _asset(instrument_id: int, daily_return: float) -> FactorAssetData:
    prices: list[FactorPricePoint] = []
    close = 100.0 + instrument_id
    for index in range(290):
        close *= 1 + daily_return
        prices.append(
            FactorPricePoint(
                date=date(2024, 1, 1) + timedelta(days=index),
                close=close,
                raw_close=close * 2,
            )
        )
    financials = (
        FactorFinancialPoint(
            period_end=date(2023, 6, 30),
            period_type="annual",
            available_at=datetime(2024, 2, 1, tzinfo=UTC),
            revenue=100,
            free_cash_flow=10,
            roe=0.10,
            roic=0.09,
            pe=20,
            pb=2,
            eps=2,
            shares_outstanding=10,
            ps=3,
            gross_margin=0.30,
            debt_ratio=0.50,
            source="fundamental_a",
        ),
        FactorFinancialPoint(
            period_end=date(2024, 6, 30),
            period_type="annual",
            available_at=datetime(2024, 8, 1, 12, tzinfo=UTC),
            revenue=120,
            free_cash_flow=12,
            roe=0.15,
            roic=0.13,
            pe=15,
            pb=1.5,
            eps=2.5,
            shares_outstanding=10,
            ps=2.5,
            gross_margin=0.35,
            debt_ratio=0.40,
            source="fundamental_a",
        ),
        FactorFinancialPoint(
            period_end=date(2025, 6, 30),
            period_type="annual",
            available_at=datetime(2024, 9, 16, 22, tzinfo=UTC),
            revenue=999,
            free_cash_flow=999,
            roe=0.99,
            roic=0.99,
            pe=1,
            pb=0.1,
            eps=99,
            shares_outstanding=10,
            ps=0.1,
            gross_margin=0.99,
            debt_ratio=0.01,
            source="fundamental_a",
        ),
    )
    return FactorAssetData(
        instrument=GraphInstrument(
            id=instrument_id,
            key=f"stock:{instrument_id}",
            symbol=f"S{instrument_id}",
            name=f"Stock {instrument_id}",
            market="US",
            asset_type="stock",
            industry="Test",
        ),
        prices=tuple(prices),
        financials=financials,
    )


def test_generator_uses_point_in_time_financials_raw_valuation_and_adjusted_returns() -> None:
    dataset = FactorDataset(assets=tuple(_asset(index, 0.0005 * index) for index in range(1, 5)))
    as_of_date = date(2024, 9, 16)
    environment = (
        MarketEnvironmentPoint(
            date=as_of_date - timedelta(days=1),
            available_at=datetime(2024, 9, 15, 20, tzinfo=UTC),
            vix=18,
            interest_rate=0.04,
            dollar_index=102,
            market_breadth=0.60,
            source="macro_test",
        ),
        MarketEnvironmentPoint(
            date=as_of_date,
            available_at=datetime(2024, 9, 16, 22, tzinfo=UTC),
            vix=99,
            source="future_after_close",
        ),
    )

    panel = generate_factor_panel(
        dataset,
        market="US",
        rebalance_dates=(as_of_date,),
        horizon_days=5,
        minimum_cross_section=3,
        environment=environment,
    )

    assert len(panel.observations) == 4
    first = panel.observations[0]
    assert first.factor_values["pe"] == 15
    assert first.factor_values["ps"] == 2.5
    assert first.factor_values["revenue_growth"] == pytest.approx(0.20)
    assert first.factor_values["eps_growth"] == pytest.approx(0.25)
    assert first.factor_values["gross_margin"] == 0.35
    assert first.factor_values["debt_ratio"] == 0.40
    assert first.factor_values["vix"] == 18
    latest_price = next(item for item in dataset.assets[0].prices if item.date == as_of_date)
    assert first.factor_values["fcf_yield"] == pytest.approx(
        12 / (float(latest_price.raw_close) * 10)
    )
    assert first.forward_return > 0
    assert len(panel.data_fingerprint) == 64


def test_generator_produces_all_requested_price_and_technical_factors() -> None:
    dataset = FactorDataset(assets=tuple(_asset(index, 0.0005 * index) for index in range(1, 5)))
    as_of_date = date(2024, 9, 16)

    panel = generate_factor_panel(
        dataset,
        market="US",
        rebalance_dates=(as_of_date,),
        horizon_days=5,
        minimum_cross_section=3,
    )

    values = panel.observations[0].factor_values
    for factor in (
        "momentum_1m",
        "momentum_3m",
        "momentum_6m",
        "momentum_12m",
        "volatility_3m",
        "maximum_drawdown_6m",
        "ma_20_distance",
        "ma_60_distance",
        "rsi_14",
        "macd_histogram_pct",
    ):
        assert factor in FACTOR_BY_NAME
        assert values[factor] is not None


def test_generator_drops_stale_market_environment_values() -> None:
    dataset = FactorDataset(assets=tuple(_asset(index, 0.0005 * index) for index in range(1, 5)))
    as_of_date = date(2024, 9, 16)

    panel = generate_factor_panel(
        dataset,
        market="US",
        rebalance_dates=(as_of_date,),
        horizon_days=5,
        minimum_cross_section=3,
        environment=(
            MarketEnvironmentPoint(
                date=as_of_date - timedelta(days=10),
                available_at=datetime(2024, 9, 6, 20, tzinfo=UTC),
                vix=17,
            ),
        ),
        environment_max_staleness_days=5,
    )

    assert panel.observations[0].factor_values["vix"] is None
