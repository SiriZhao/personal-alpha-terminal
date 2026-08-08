from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.portfolio.management_engine import analyze_portfolio
from personal_alpha_terminal.portfolio.management_schemas import (
    AllocationTarget,
    AssetPricePoint,
    AssetPriceSeries,
    LedgerEvent,
    ManagedAsset,
    PortfolioManagementData,
)
from personal_alpha_terminal.portfolio.schemas import FxPoint, FxSeries


def event(
    identifier: int,
    kind: str,
    day: date,
    *,
    asset: ManagedAsset | None = None,
    quantity: float | None = None,
    price: float | None = None,
    cash: float | None = None,
    fee: float = 0,
    currency: str = "USD",
    fx_rate: float = 1,
) -> LedgerEvent:
    timestamp = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return LedgerEvent(
        id=identifier,
        transaction_type=kind,
        trade_date=day,
        settlement_date=day,
        currency=currency,
        fx_rate_to_base=fx_rate,
        available_time=timestamp,
        asset=asset,
        quantity=quantity,
        unit_price=price,
        cash_amount=cash,
        fee_amount=fee,
    )


def build_data() -> PortfolioManagementData:
    start = date(2025, 1, 2)
    stock = ManagedAsset(1, "EQ", "Equity", "stock", "USD", "Technology")
    bond = ManagedAsset(2, "BOND", "Bond", "bond", "USD", "Fixed Income")
    benchmark = ManagedAsset(9, "SPY", "Benchmark", "etf", "USD", "Broad Market")
    equity_price = 100.0
    bond_price = 100.0
    benchmark_price = 100.0
    equity_points: list[AssetPricePoint] = []
    bond_points: list[AssetPricePoint] = []
    benchmark_points: list[AssetPricePoint] = []
    for offset in range(90):
        day = start + timedelta(days=offset)
        if offset:
            benchmark_return = 0.004 if offset % 2 else -0.001
            benchmark_price *= 1 + benchmark_return
            equity_price *= 1 + 1.2 * benchmark_return
            bond_price *= 1 + 0.1 * benchmark_return
        equity_points.append(AssetPricePoint(day, equity_price))
        bond_points.append(AssetPricePoint(day, bond_price))
        benchmark_points.append(AssetPricePoint(day, benchmark_price))
    return PortfolioManagementData(
        portfolio_id=1,
        portfolio_name="Core",
        base_currency="USD",
        start_date=start,
        end_date=start + timedelta(days=89),
        transactions=(
            event(1, "deposit", start, cash=10_000),
            event(2, "buy", start, asset=stock, quantity=50, price=100, fee=5),
            event(3, "buy", start, asset=bond, quantity=20, price=100, fee=2),
            event(4, "dividend", start + timedelta(days=30), asset=stock, cash=50),
            event(5, "fee", start + timedelta(days=45), cash=3),
            event(6, "deposit", start + timedelta(days=60), cash=1_000),
        ),
        prices=(
            AssetPriceSeries(stock, tuple(equity_points)),
            AssetPriceSeries(bond, tuple(bond_points)),
        ),
        fx_series=(),
        benchmark=benchmark,
        benchmark_prices=tuple(benchmark_points),
        targets=(
            AllocationTarget("asset:1", "EQ", 0.40),
            AllocationTarget("asset:2", "BOND", 0.30),
            AllocationTarget("cash:USD", "Cash USD", 0.30),
        ),
    )


def test_actual_ledger_performance_excludes_external_deposit_and_calculates_metrics() -> None:
    result = analyze_portfolio(
        build_data(),
        annual_risk_free_rate=0,
        minimum_observations=60,
        price_max_staleness_days=2,
        rebalance_drift_threshold=0.01,
        minimum_rebalance_value=10,
    )

    deposit_day = next(point for point in result.equity_curve if point.external_flow == 1_000)
    previous = result.equity_curve[result.equity_curve.index(deposit_day) - 1]
    assert deposit_day.daily_return == pytest.approx(
        (deposit_day.value - 1_000) / previous.value - 1
    )
    assert result.net_external_flow == pytest.approx(11_000)
    assert result.observation_count == 89
    assert result.annualized_volatility is not None
    assert result.sharpe_ratio is not None
    assert result.sortino_ratio is not None
    assert result.beta is not None
    assert result.alpha is not None
    assert sum(result.asset_class_exposure.values()) == pytest.approx(1)
    assert result.asset_class_exposure["bond"] > 0
    assert result.industry_exposure["Technology"] > 0
    assert result.currency_exposure == pytest.approx({"USD": 1.0})
    assert result.largest_position_weight == pytest.approx(result.positions[0].weight)
    assert result.concentration_hhi == pytest.approx(
        sum(item.weight**2 for item in result.positions)
    )
    assert result.rebalance_suggestions


def test_unadjusted_ex_dividend_price_and_cash_dividend_are_not_double_counted() -> None:
    start = date(2025, 1, 2)
    stock = ManagedAsset(1, "DIV", "Dividend Stock", "stock", "USD", "Utilities")
    benchmark = ManagedAsset(9, "SPY", "Benchmark", "etf", "USD", "Broad Market")
    data = PortfolioManagementData(
        portfolio_id=1,
        portfolio_name="Dividend",
        base_currency="USD",
        start_date=start,
        end_date=start + timedelta(days=2),
        transactions=(
            event(1, "deposit", start, cash=1_000),
            event(2, "buy", start, asset=stock, quantity=10, price=100),
            event(3, "dividend", start + timedelta(days=1), asset=stock, cash=10),
        ),
        prices=(
            AssetPriceSeries(
                stock,
                (
                    AssetPricePoint(start, 100),
                    AssetPricePoint(start + timedelta(days=1), 99),
                    AssetPricePoint(start + timedelta(days=2), 99),
                ),
            ),
        ),
        fx_series=(),
        benchmark=benchmark,
        benchmark_prices=(
            AssetPricePoint(start, 100),
            AssetPricePoint(start + timedelta(days=1), 100),
            AssetPricePoint(start + timedelta(days=2), 100),
        ),
        targets=(),
    )

    result = analyze_portfolio(
        data,
        minimum_observations=2,
        price_max_staleness_days=1,
    )

    assert result.total_value == pytest.approx(1_000)
    assert result.cumulative_return == pytest.approx(0)
    assert result.period_pnl == pytest.approx(0)


def test_split_changes_quantity_without_creating_return() -> None:
    start = date(2025, 1, 2)
    stock = ManagedAsset(1, "SPLT", "Split Stock", "stock", "USD", "Technology")
    benchmark = ManagedAsset(9, "SPY", "Benchmark", "etf", "USD", "Broad Market")
    data = PortfolioManagementData(
        portfolio_id=1,
        portfolio_name="Split",
        base_currency="USD",
        start_date=start,
        end_date=start + timedelta(days=1),
        transactions=(
            event(1, "deposit", start, cash=1_000),
            event(2, "buy", start, asset=stock, quantity=10, price=100),
            event(3, "split", start + timedelta(days=1), asset=stock, quantity=2),
        ),
        prices=(
            AssetPriceSeries(
                stock,
                (
                    AssetPricePoint(start, 100),
                    AssetPricePoint(start + timedelta(days=1), 50),
                ),
            ),
        ),
        fx_series=(),
        benchmark=benchmark,
        benchmark_prices=(
            AssetPricePoint(start, 100),
            AssetPricePoint(start + timedelta(days=1), 100),
        ),
        targets=(),
    )

    result = analyze_portfolio(data, minimum_observations=2, price_max_staleness_days=1)

    assert result.positions[0].quantity == pytest.approx(20)
    assert result.total_value == pytest.approx(1_000)
    assert result.cumulative_return == pytest.approx(0)


def test_fx_sell_fee_and_withdrawal_are_accounted_without_false_loss() -> None:
    start = date(2025, 1, 2)
    stock = ManagedAsset(1, "EUR_EQ", "Euro Equity", "stock", "EUR", "Industrials")
    benchmark = ManagedAsset(9, "SPY", "Benchmark", "etf", "USD", "Broad Market")
    data = PortfolioManagementData(
        portfolio_id=1,
        portfolio_name="FX",
        base_currency="USD",
        start_date=start,
        end_date=start + timedelta(days=2),
        transactions=(
            event(1, "deposit", start, cash=1_000, currency="EUR", fx_rate=1.2),
            event(
                2,
                "buy",
                start,
                asset=stock,
                quantity=5,
                price=100,
                currency="EUR",
                fx_rate=1.2,
            ),
            event(
                3,
                "sell",
                start + timedelta(days=2),
                asset=stock,
                quantity=1,
                price=110,
                fee=1,
                currency="EUR",
                fx_rate=1.1,
            ),
            event(
                4,
                "withdrawal",
                start + timedelta(days=2),
                cash=100,
                currency="EUR",
                fx_rate=1.1,
            ),
        ),
        prices=(
            AssetPriceSeries(
                stock,
                (
                    AssetPricePoint(start, 100),
                    AssetPricePoint(start + timedelta(days=1), 100),
                    AssetPricePoint(start + timedelta(days=2), 110),
                ),
            ),
        ),
        fx_series=(
            FxSeries(
                base_currency="EUR",
                quote_currency="USD",
                values=(
                    FxPoint(start, 1.2),
                    FxPoint(start + timedelta(days=1), 1.1),
                    FxPoint(start + timedelta(days=2), 1.1),
                ),
            ),
        ),
        benchmark=benchmark,
        benchmark_prices=(
            AssetPricePoint(start, 100),
            AssetPricePoint(start + timedelta(days=1), 100),
            AssetPricePoint(start + timedelta(days=2), 100),
        ),
        targets=(),
    )

    result = analyze_portfolio(
        data,
        minimum_observations=2,
        price_max_staleness_days=1,
        fx_max_staleness_days=1,
    )

    assert result.equity_curve[1].daily_return == pytest.approx(1_100 / 1_200 - 1)
    assert result.total_value == pytest.approx((4 * 110 + 509) * 1.1)
    assert result.equity_curve[2].daily_return == pytest.approx(
        (result.total_value + 110) / 1_100 - 1
    )
    assert result.net_external_flow == pytest.approx(1_200 - 110)
    assert result.currency_exposure == pytest.approx({"EUR": 1.0})


def test_rejects_unfunded_purchase_and_oversell() -> None:
    data = build_data()
    unfunded = (event(99, "buy", data.start_date, asset=data.prices[0].asset, quantity=1, price=1),)
    with pytest.raises(ValueError, match="negative USD cash"):
        analyze_portfolio(replace(data, transactions=unfunded))
