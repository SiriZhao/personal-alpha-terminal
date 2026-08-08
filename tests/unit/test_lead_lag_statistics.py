from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.lead_lag.statistics import (
    benjamini_hochberg,
    bonferroni_adjust,
    calculate_lag_metrics,
    cross_correlation,
)
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphInstrument,
    MarketSeries,
)


def pseudo_random_values(count: int, seed: int) -> list[float]:
    state = seed
    values: list[float] = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % (2**31)
        values.append((state / (2**31) - 0.5) / 20)
    return values


def build_series(instrument_id: int, symbol: str, values: list[float]) -> MarketSeries:
    start = date(2025, 1, 1)
    instrument = GraphInstrument(
        id=instrument_id,
        key=f"stock:{instrument_id}",
        symbol=symbol,
        name=symbol,
        market="US",
        asset_type="stock",
        industry=None,
    )
    return MarketSeries(
        instrument=instrument,
        returns=tuple((start + timedelta(days=index), value) for index, value in enumerate(values)),
        flow_proxy=(),
    )


def test_cross_correlation_and_granger_recover_two_period_lead() -> None:
    source_values = pseudo_random_values(300, 17)
    noise = pseudo_random_values(300, 71)
    target_values = [
        0.15 * noise[index] + (0.9 * source_values[index - 2] if index >= 2 else noise[index])
        for index in range(300)
    ]
    source = build_series(1, "NVDA", source_values)
    target = build_series(2, "TSM", target_values)

    metrics = calculate_lag_metrics(
        source,
        target,
        maximum_lag_days=5,
        minimum_observations=120,
    )

    best = min(metrics, key=lambda item: item.granger_p_value)
    strongest = max(metrics, key=lambda item: abs(item.cross_correlation))
    assert best.granger_p_value < 0.001
    assert strongest.lag_days == 2
    assert strongest.cross_correlation > 0.95


def test_cross_correlation_positive_lag_means_source_leads_target() -> None:
    source = [0.2, -0.1, 0.4, 0.3, -0.2, 0.1]
    target = [0.0, 0.0, *source[:-2]]
    assert cross_correlation(source, target, 2) == pytest.approx(1)


def test_multiple_testing_adjustments_are_bounded_and_monotone() -> None:
    assert bonferroni_adjust(0.02, 5) == pytest.approx(0.1)
    assert benjamini_hochberg([0.01, 0.04, 0.03]) == pytest.approx((0.03, 0.04, 0.04))
