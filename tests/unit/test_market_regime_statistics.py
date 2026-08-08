from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.market_regime.schemas import RawRegimeFeatures
from personal_alpha_terminal.analysis.market_regime.statistics import classify_regimes


def row(index: int, values: dict[str, float]) -> RawRegimeFeatures:
    return RawRegimeFeatures(
        as_of_date=date(2025, 1, 1) + timedelta(days=index),
        values=values,
        breadth_constituent_count=100,
    )


def test_statistical_model_identifies_risk_off_shift() -> None:
    rows: list[RawRegimeFeatures] = []
    for index in range(70):
        cycle = (index % 7 - 3) / 10
        rows.append(
            row(
                index,
                {
                    "vix_level": 20 + cycle,
                    "rate_change": cycle / 100,
                    "dollar_trend": cycle / 100,
                    "index_trend": -cycle / 100,
                    "market_breadth": 0.5 - cycle / 10,
                    "volume_breadth": -cycle / 5,
                },
            )
        )
    rows.append(
        row(
            70,
            {
                "vix_level": 35,
                "rate_change": 0.5,
                "dollar_trend": 0.08,
                "index_trend": -0.15,
                "market_breadth": 0.1,
                "volume_breadth": -0.9,
            },
        )
    )

    results = classify_regimes(
        rows,
        calibration_window=60,
        minimum_calibration_observations=40,
        softmax_temperature=0.75,
        neutral_bias=0.5,
    )

    current = results[-1]
    assert current.regime == "risk_off"
    assert current.risk_off_score > 0.9
    assert current.composite_score < 0
    assert sum(
        (
            current.risk_on_score,
            current.risk_off_score,
            current.neutral_score,
        )
    ) == pytest.approx(1)


def test_constant_features_produce_neutral_state() -> None:
    values = {
        "vix_level": 20.0,
        "rate_change": 0.0,
        "dollar_trend": 0.0,
        "index_trend": 0.0,
        "market_breadth": 0.5,
        "volume_breadth": 0.0,
    }
    results = classify_regimes(
        [row(index, values) for index in range(25)],
        calibration_window=20,
        minimum_calibration_observations=20,
        softmax_temperature=0.75,
        neutral_bias=0.5,
    )

    assert results[-1].regime == "neutral"
    assert results[-1].composite_score == pytest.approx(0)
    assert results[-1].probabilities is None
