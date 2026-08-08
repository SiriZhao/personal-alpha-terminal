from datetime import date, timedelta
from random import Random

import pytest

from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphInstrument,
    MarketSeries,
)
from personal_alpha_terminal.analysis.market_graph.statistics import (
    build_statistical_edges,
    signed_flow_proxy,
)


def instrument(instrument_id: int, symbol: str) -> GraphInstrument:
    return GraphInstrument(
        id=instrument_id,
        key=f"stock:{instrument_id}",
        symbol=symbol,
        name=symbol,
        market="US",
        asset_type="stock",
        industry=None,
    )


def pseudo_random_returns(count: int) -> list[float]:
    state = 17
    values = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % (2**31)
        values.append(((state / (2**31)) - 0.5) / 10)
    return values


def independent_returns(seed: int, count: int) -> list[float]:
    generator = Random(seed)
    return [generator.uniform(-0.05, 0.05) for _ in range(count)]


def series(
    instrument_id: int,
    symbol: str,
    returns: list[float],
    *,
    flow: list[float] | None = None,
) -> MarketSeries:
    start = date(2026, 1, 1)
    return MarketSeries(
        instrument=instrument(instrument_id, symbol),
        returns=tuple(
            (start + timedelta(days=index), value) for index, value in enumerate(returns)
        ),
        flow_proxy=tuple(
            (start + timedelta(days=index), value) for index, value in enumerate(flow or [])
        ),
    )


def test_lead_lag_direction_is_discovered() -> None:
    source_values = pseudo_random_returns(100)
    target_values = [0.0, *source_values[:-1]]
    source = series(1, "NVDA", source_values)
    target = series(2, "TSM", target_values)

    edges = build_statistical_edges(
        [source, target],
        minimum_observations=60,
        correlation_threshold=0.95,
        maximum_lag_days=3,
        lead_threshold=0.8,
        lead_improvement=0.1,
        capital_threshold=0.95,
    )

    lead = next(edge for edge in edges if edge.relationship_type == "lead_lag")
    assert lead.source.symbol == "NVDA"
    assert lead.target.symbol == "TSM"
    assert lead.lag_days == 1
    assert lead.weight == pytest.approx(1)
    assert lead.p_value == 0
    assert lead.significant_fdr
    assert lead.significant_bonferroni


def test_capital_transmission_is_explicitly_a_proxy() -> None:
    source_values = pseudo_random_returns(100)
    target_values = [0.0, *source_values[:-1]]
    source = series(1, "NVDA", source_values, flow=source_values)
    target = series(2, "TSM", target_values, flow=[0.0] * 100)

    edges = build_statistical_edges(
        [source, target],
        minimum_observations=60,
        correlation_threshold=1,
        maximum_lag_days=3,
        lead_threshold=1,
        lead_improvement=1,
        capital_threshold=0.8,
    )

    capital = next(edge for edge in edges if edge.relationship_type == "capital_transmission")
    assert capital.source.symbol == "NVDA"
    assert capital.details["is_actual_fund_flow"] is False


def test_signed_flow_proxy_uses_abnormal_volume() -> None:
    proxy = signed_flow_proxy(0.02, 200, [100] * 20)
    assert proxy is not None
    assert proxy > 0
    assert signed_flow_proxy(0.02, None, [100] * 20) is None


def test_multiple_testing_does_not_promote_the_largest_noise_correlation() -> None:
    noise_series = [
        series(
            instrument_id,
            f"N{instrument_id}",
            independent_returns(instrument_id, 120),
        )
        for instrument_id in range(1, 9)
    ]

    edges = build_statistical_edges(
        noise_series,
        minimum_observations=100,
        correlation_threshold=0.2,
        maximum_lag_days=3,
        lead_threshold=0.2,
        lead_improvement=0,
        capital_threshold=1,
        significance_alpha=0.01,
        significance_method="fdr",
    )

    assert edges == ()
