from datetime import date

import pytest

from personal_alpha_terminal.scenario_simulator.calibration import (
    calibrate_historical_scenario,
)
from personal_alpha_terminal.scenario_simulator.catalog import (
    RISK_FACTORS,
    built_in_scenarios,
    risk_committee_scenarios,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    HistoricalFactorPoint,
    HistoricalFactorSeries,
)


def test_builtin_history_is_labelled_illustrative_and_ai_is_hypothetical() -> None:
    scenarios = {item.name: item for item in built_in_scenarios()}

    assert scenarios["2008 Financial Crisis Proxy"].scenario_type == "historical"
    assert scenarios["2008 Financial Crisis Proxy"].evidence_level == "illustrative"
    assert scenarios["2020 Pandemic Drawdown Proxy"].evidence_level == "illustrative"
    assert scenarios["2022 Tightening Cycle Proxy"].evidence_level == "illustrative"
    assert scenarios["AI Valuation Unwind"].scenario_type == "hypothetical"
    assert "not a historical event" in scenarios["AI Valuation Unwind"].description


def test_risk_committee_scenarios_are_explicit_hypotheses() -> None:
    scenarios = {item.name: item for item in risk_committee_scenarios()}

    assert set(scenarios) == {
        "NASDAQ Down 30%",
        "US Dollar Index Up 20%",
        "Rapid US Rate Increase",
    }
    assert all(item.evidence_level == "user_assumption" for item in scenarios.values())
    rate_shocks = {
        item.factor_code: item.magnitude
        for item in scenarios["Rapid US Rate Increase"].factor_shocks
    }
    assert rate_shocks == {"us_policy_rate": 200, "us_10y_yield": 200}


def test_historical_calibration_uses_one_window_and_correct_units() -> None:
    scenario = calibrate_historical_scenario(
        name="Calibrated",
        description="Source-backed shared window",
        start_date=date(2022, 1, 1),
        end_date=date(2022, 12, 31),
        series=(
            HistoricalFactorSeries(
                factor_code="equity_nasdaq",
                unit="decimal_return",
                points=(
                    HistoricalFactorPoint(date(2022, 1, 3), 100),
                    HistoricalFactorPoint(date(2022, 12, 30), 70),
                ),
                source="verified:index",
            ),
            HistoricalFactorSeries(
                factor_code="us_10y_yield",
                unit="basis_points",
                points=(
                    HistoricalFactorPoint(date(2022, 1, 3), 1.5),
                    HistoricalFactorPoint(date(2022, 12, 30), 3.8),
                ),
                source="verified:yield",
            ),
        ),
        factors=RISK_FACTORS,
    )
    shocks = {item.factor_code: item.magnitude for item in scenario.factor_shocks}

    assert shocks["equity_nasdaq"] == pytest.approx(-0.30)
    assert shocks["us_10y_yield"] == pytest.approx(230)
    assert scenario.evidence_level == "calibrated_historical"
    assert len(scenario.data_sources) == 2


def test_historical_calibration_rejects_stale_boundaries() -> None:
    with pytest.raises(ValueError, match="boundary is stale"):
        calibrate_historical_scenario(
            name="Bad",
            description="Stale boundary",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
            series=(
                HistoricalFactorSeries(
                    factor_code="equity_nasdaq",
                    unit="decimal_return",
                    points=(
                        HistoricalFactorPoint(date(2022, 2, 1), 100),
                        HistoricalFactorPoint(date(2022, 12, 30), 70),
                    ),
                    source="test",
                ),
            ),
            factors=RISK_FACTORS,
        )


def test_historical_series_rejects_non_finite_duplicate_or_short_data() -> None:
    with pytest.raises(ValueError, match="finite"):
        HistoricalFactorPoint(date(2022, 1, 3), float("nan"))
    with pytest.raises(ValueError, match="at least two"):
        HistoricalFactorSeries(
            factor_code="equity_nasdaq",
            unit="decimal_return",
            points=(HistoricalFactorPoint(date(2022, 1, 3), 100),),
            source="verified:index",
        )
    with pytest.raises(ValueError, match="unique"):
        HistoricalFactorSeries(
            factor_code="equity_nasdaq",
            unit="decimal_return",
            points=(
                HistoricalFactorPoint(date(2022, 1, 3), 100),
                HistoricalFactorPoint(date(2022, 1, 3), 101),
            ),
            source="verified:index",
        )


def test_historical_calibration_rejects_invalid_level_and_gap_policy() -> None:
    series = (
        HistoricalFactorSeries(
            factor_code="equity_nasdaq",
            unit="decimal_return",
            points=(
                HistoricalFactorPoint(date(2022, 1, 3), 100),
                HistoricalFactorPoint(date(2022, 12, 30), 0),
            ),
            source="verified:index",
        ),
    )
    with pytest.raises(ValueError, match="index level"):
        calibrate_historical_scenario(
            name="Bad level",
            description="Invalid end index level",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
            series=series,
            factors=RISK_FACTORS,
        )
    with pytest.raises(ValueError, match="between 0 and 31"):
        calibrate_historical_scenario(
            name="Bad gap",
            description="Invalid boundary policy",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
            series=series,
            factors=RISK_FACTORS,
            maximum_boundary_gap_days=32,
        )
