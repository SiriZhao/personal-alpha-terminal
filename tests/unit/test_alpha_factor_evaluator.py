from datetime import date, timedelta

import pytest

from personal_alpha_terminal.alpha_discovery.factor_evaluator import (
    benjamini_hochberg,
    evaluate_factor,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    FactorDefinition,
    FactorObservation,
    FactorPanel,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


def _panel(scope: str = "cross_sectional") -> FactorPanel:
    definition = FactorDefinition(
        name="quality",
        category="quality",
        direction="high",
        scope=scope,  # type: ignore[arg-type]
        description="Synthetic quality.",
        formula="rank",
    )
    observations: list[FactorObservation] = []
    for date_index in range(20):
        as_of_date = date(2020, 1, 1) + timedelta(days=date_index * 10)
        for asset_index in range(10):
            factor_value = float(date_index) if scope == "time_series" else float(asset_index)
            forward_return = (
                date_index / 100
                if scope == "time_series"
                else asset_index / 100 + date_index / 10000
            )
            observations.append(
                FactorObservation(
                    as_of_date=as_of_date,
                    forward_end_date=as_of_date + timedelta(days=5),
                    instrument=GraphInstrument(
                        id=asset_index,
                        key=f"stock:{asset_index}",
                        symbol=f"S{asset_index}",
                        name=f"S{asset_index}",
                        market="US",
                        asset_type="stock",
                        industry=None,
                    ),
                    factor_values={"quality": factor_value},
                    forward_return=forward_return,
                )
            )
    return FactorPanel(
        market="US",
        horizon_days=5,
        definitions=(definition,),
        observations=tuple(observations),
        data_fingerprint="test",
    )


def test_cross_sectional_ic_counts_dates_not_only_stock_rows() -> None:
    result = evaluate_factor(
        _panel(),
        "quality",
        minimum_cross_section=5,
        minimum_dates=5,
    )

    assert result.date_count == 20
    assert result.observation_count == 200
    assert result.raw_mean_ic == pytest.approx(1)
    assert result.directional_mean_ic == pytest.approx(1)
    assert result.p_value == 0


def test_market_factor_uses_one_observation_per_date_without_pseudo_replication() -> None:
    result = evaluate_factor(
        _panel("time_series"),
        "quality",
        minimum_dates=5,
    )

    assert result.date_count == 20
    assert result.observation_count == 20
    assert result.raw_mean_ic == pytest.approx(1)


def test_benjamini_hochberg_is_monotone_and_restores_input_order() -> None:
    adjusted = benjamini_hochberg((0.04, 0.001, 0.03, 0.50))

    assert adjusted == pytest.approx((0.0533333333, 0.004, 0.0533333333, 0.50))


def test_constant_factor_is_not_presented_as_valid_ic() -> None:
    panel = _panel()
    constant = FactorPanel(
        market=panel.market,
        horizon_days=panel.horizon_days,
        definitions=panel.definitions,
        observations=tuple(
            FactorObservation(
                as_of_date=item.as_of_date,
                forward_end_date=item.forward_end_date,
                instrument=item.instrument,
                factor_values={"quality": 1.0},
                forward_return=item.forward_return,
            )
            for item in panel.observations
        ),
        data_fingerprint=panel.data_fingerprint,
    )

    result = evaluate_factor(
        constant,
        "quality",
        minimum_cross_section=5,
        minimum_dates=5,
    )

    assert result.raw_mean_ic is None
    assert result.confidence_score == 0
    assert result.warning is not None
