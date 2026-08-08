from dataclasses import replace
from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.portfolio.engine import apply_stress, calculate_risk
from personal_alpha_terminal.portfolio.schemas import (
    FxPoint,
    FxSeries,
    PortfolioRiskData,
    RiskPositionData,
    RiskPricePoint,
    StressScenario,
)


def instrument(
    identifier: int,
    symbol: str,
    asset_type: str = "stock",
) -> GraphInstrument:
    return GraphInstrument(
        id=identifier,
        key=f"{asset_type}:{identifier}",
        symbol=symbol,
        name=symbol,
        market="US",
        asset_type=asset_type,
        industry="Technology",
    )


def build_risk_data() -> PortfolioRiskData:
    start = date(2025, 1, 1)
    benchmark_price = 100.0
    usd_price = 20.0
    cny_price = 40.0
    benchmark_points = [RiskPricePoint(start, benchmark_price)]
    usd_points = [RiskPricePoint(start, usd_price)]
    cny_points = [RiskPricePoint(start, cny_price)]
    fx_points = [FxPoint(start, 7.0)]
    for offset in range(1, 91):
        benchmark_return = 0.01 if offset % 2 else -0.004
        benchmark_price *= 1 + benchmark_return
        usd_price *= 1 + 1.2 * benchmark_return
        cny_price *= 1 + 0.5 * benchmark_return
        point_date = start + timedelta(days=offset)
        benchmark_points.append(RiskPricePoint(point_date, benchmark_price))
        usd_points.append(RiskPricePoint(point_date, usd_price))
        cny_points.append(RiskPricePoint(point_date, cny_price))
        fx_points.append(FxPoint(point_date, 7.0))
    return PortfolioRiskData(
        portfolio_id=1,
        portfolio_name="Global",
        base_currency="CNY",
        cash_balance=1_000.0,
        as_of_date=start + timedelta(days=90),
        positions=(
            RiskPositionData(
                instrument=instrument(1, "US_EQ"),
                currency="USD",
                industry="Semiconductors",
                quantity=10,
                prices=tuple(usd_points),
            ),
            RiskPositionData(
                instrument=instrument(2, "CN_ETF", "etf"),
                currency="CNY",
                industry="Broad Market",
                quantity=20,
                prices=tuple(cny_points),
            ),
        ),
        benchmark=instrument(3, "NASDAQ", "index"),
        benchmark_currency="USD",
        benchmark_prices=tuple(benchmark_points),
        fx_series=(
            FxSeries(
                base_currency="USD",
                quote_currency="CNY",
                values=tuple(fx_points),
            ),
        ),
    )


def test_calculate_risk_normalizes_fx_and_calculates_beta_exposure() -> None:
    data = build_risk_data()
    result = calculate_risk(
        data,
        run_id=7,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 4, 1),
        annual_risk_free_rate=0.0,
        minimum_observations=60,
        fx_max_staleness_days=3,
        maximum_absolute_beta=3.0,
    )

    expected_value = (
        1_000
        + data.positions[0].prices[-1].close * 7 * 10
        + data.positions[1].prices[-1].close * 20
    )
    assert result.total_value == pytest.approx(expected_value)
    assert result.observation_count == 90
    assert result.beta is not None
    assert 0.5 < result.beta < 1.2
    assert sum(result.industry_exposure.values()) == pytest.approx(1)
    assert sum(result.currency_exposure.values()) == pytest.approx(1)
    assert result.currency_exposure["USD"] > 0
    assert result.max_drawdown <= 0


def test_static_stress_combines_beta_and_fx_multiplicatively() -> None:
    data = build_risk_data()
    risk = calculate_risk(
        data,
        run_id=8,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 4, 1),
        annual_risk_free_rate=0.0,
        minimum_observations=60,
        fx_max_staleness_days=3,
        maximum_absolute_beta=3.0,
    )
    result = apply_stress(
        risk,
        StressScenario(
            name="NASDAQ -30 / USD +20",
            benchmark_shock=-0.30,
            currency_shocks={"USD": 0.20},
        ),
    )

    usd_impact = next(item for item in result.impacts if item.instrument.symbol == "US_EQ")
    assert usd_impact.beta == pytest.approx(1.2)
    assert usd_impact.market_return == pytest.approx(-0.36)
    assert usd_impact.currency_return == pytest.approx(0.20)
    assert usd_impact.combined_return == pytest.approx((1 - 0.36) * 1.20 - 1)
    assert result.stressed_value == pytest.approx(result.original_value + result.pnl_amount)
    assert result.uncovered_weight == pytest.approx(0)


def test_risk_rejects_small_common_sample() -> None:
    with pytest.raises(ValueError, match="minimum_observations|observations"):
        calculate_risk(
            build_risk_data(),
            run_id=9,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 20),
            annual_risk_free_rate=0.0,
            minimum_observations=60,
            fx_max_staleness_days=3,
            maximum_absolute_beta=3.0,
            price_max_staleness_days=100,
        )


def test_risk_rejects_negative_cash_leverage() -> None:
    with pytest.raises(ValueError, match="negative cash"):
        calculate_risk(
            replace(build_risk_data(), cash_balance=-1.0),
            run_id=10,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 4, 1),
            annual_risk_free_rate=0.0,
            minimum_observations=60,
            fx_max_staleness_days=3,
            maximum_absolute_beta=3.0,
        )


def test_risk_accepts_inverse_fx_pair_with_equivalent_valuation() -> None:
    data = build_risk_data()
    inverse = FxSeries(
        base_currency="CNY",
        quote_currency="USD",
        values=tuple(FxPoint(point.date, 1 / point.rate) for point in data.fx_series[0].values),
    )
    direct_result = calculate_risk(
        data,
        run_id=11,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 4, 1),
        annual_risk_free_rate=0.0,
        minimum_observations=60,
        fx_max_staleness_days=3,
        maximum_absolute_beta=3.0,
    )
    inverse_result = calculate_risk(
        replace(data, fx_series=(inverse,)),
        run_id=12,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 4, 1),
        annual_risk_free_rate=0.0,
        minimum_observations=60,
        fx_max_staleness_days=3,
        maximum_absolute_beta=3.0,
    )

    assert inverse_result.total_value == pytest.approx(direct_result.total_value)
    assert inverse_result.beta == pytest.approx(direct_result.beta)


def test_risk_rejects_stale_fx_history() -> None:
    data = build_risk_data()
    stale = FxSeries(
        base_currency="USD",
        quote_currency="CNY",
        values=(data.fx_series[0].values[0],),
    )

    with pytest.raises(ValueError, match="price or FX history"):
        calculate_risk(
            replace(data, fx_series=(stale,)),
            run_id=13,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 4, 1),
            annual_risk_free_rate=0.0,
            minimum_observations=60,
            fx_max_staleness_days=1,
            maximum_absolute_beta=3.0,
        )


def test_risk_rejects_stale_position_valuation() -> None:
    data = build_risk_data()

    with pytest.raises(ValueError, match="stale valuation price"):
        calculate_risk(
            replace(data, as_of_date=data.as_of_date + timedelta(days=10)),
            run_id=15,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 4, 1),
            annual_risk_free_rate=0.0,
            minimum_observations=60,
            fx_max_staleness_days=3,
            maximum_absolute_beta=3.0,
            price_max_staleness_days=5,
        )


def test_stress_reports_weight_without_estimated_beta_as_uncovered() -> None:
    risk = calculate_risk(
        build_risk_data(),
        run_id=14,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 4, 1),
        annual_risk_free_rate=0.0,
        minimum_observations=60,
        fx_max_staleness_days=3,
        maximum_absolute_beta=3.0,
    )
    missing_beta = replace(risk.positions[0], beta=None)
    stressed = apply_stress(
        replace(risk, positions=(missing_beta, *risk.positions[1:])),
        StressScenario(
            name="Market shock with incomplete beta",
            benchmark_shock=-0.3,
            currency_shocks={},
        ),
    )

    uncovered = next(
        impact for impact in stressed.impacts if impact.instrument.id == missing_beta.instrument.id
    )
    assert uncovered.market_return == 0
    assert not uncovered.beta_covered
    assert stressed.uncovered_weight == pytest.approx(missing_beta.weight)
