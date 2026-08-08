from dataclasses import replace
from datetime import date

import pytest

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.scenario_simulator.catalog import RISK_FACTORS
from personal_alpha_terminal.scenario_simulator.engine import ScenarioEngine
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorShock,
    ScenarioDefinition,
    ScenarioPortfolio,
    ScenarioPosition,
)


def _instrument(asset_id: int, symbol: str) -> GraphInstrument:
    return GraphInstrument(
        id=asset_id,
        key=f"etf:{asset_id}",
        symbol=symbol,
        name=symbol,
        market="US",
        asset_type="etf",
        industry=None,
    )


def _portfolio(
    *,
    position_value: float = 50_000,
    cash_value: float = 50_000,
    currency: str = "USD",
    base_currency: str = "USD",
) -> ScenarioPortfolio:
    total = position_value + cash_value
    return ScenarioPortfolio(
        portfolio_id=1,
        portfolio_name="Test",
        base_currency=base_currency,
        as_of_date=date(2026, 7, 30),
        total_value=total,
        cash_value=cash_value,
        positions=(
            ScenarioPosition(
                instrument=_instrument(1, "QQQM"),
                currency=currency,
                market_value=position_value,
                weight=position_value / total,
            ),
        ),
    )


def _scenario(
    shock: FactorShock,
    *,
    currency_shocks: dict[str, float] | None = None,
) -> ScenarioDefinition:
    return ScenarioDefinition(
        name="Test scenario",
        scenario_type="custom",
        description="Audited test assumption",
        factor_shocks=(shock,),
        currency_shocks=currency_shocks or {},
        evidence_level="user_assumption",
        data_sources=("test:user_assumption",),
    )


def _exposure(
    *,
    factor: str = "equity_nasdaq",
    sensitivity: float = 1.0,
    low: float = 0.8,
    high: float = 1.2,
) -> AssetFactorExposure:
    return AssetFactorExposure(
        asset_id=1,
        factor_code=factor,
        sensitivity=sensitivity,
        sensitivity_low=low,
        sensitivity_high=high,
        as_of_date=date(2026, 7, 30),
        method="test",
        source="test:manual",
        confidence_score=80,
    )


def test_nasdaq_shock_maps_to_asset_and_cash_stays_unchanged() -> None:
    result = ScenarioEngine().simulate(
        _portfolio(),
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.20,
                "decimal_return",
                "NASDAQ down 20%",
            )
        ),
        factors=RISK_FACTORS,
        exposures=(_exposure(low=1.0, high=1.0),),
    )

    assert result.impacts[0].combined_return == pytest.approx(-0.20)
    assert result.pnl_percent == pytest.approx(-0.10)
    assert result.pnl_amount == pytest.approx(-10_000)
    assert result.stressed_value == pytest.approx(90_000)
    assert result.risk_level == "High"


def test_rate_bp_unit_and_negative_duration_are_explicit() -> None:
    result = ScenarioEngine().simulate(
        _portfolio(position_value=100_000, cash_value=0),
        _scenario(
            FactorShock(
                "us_policy_rate",
                -100,
                "basis_points",
                "Fed cuts 100bp",
            )
        ),
        factors=RISK_FACTORS,
        exposures=(
            _exposure(
                factor="us_policy_rate",
                sensitivity=-0.05,
                low=-0.06,
                high=-0.04,
            ),
        ),
    )

    assert result.pnl_percent == pytest.approx(0.05)
    assert result.pnl_percent_low == pytest.approx(0.04)
    assert result.pnl_percent_high == pytest.approx(0.06)


def test_fx_translation_is_multiplicative_not_additive() -> None:
    result = ScenarioEngine().simulate(
        _portfolio(
            position_value=100_000,
            cash_value=0,
            currency="USD",
            base_currency="CNY",
        ),
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.20,
                "decimal_return",
                "NASDAQ down 20%",
            ),
            currency_shocks={"USD": 0.10},
        ),
        factors=RISK_FACTORS,
        exposures=(_exposure(low=1.0, high=1.0),),
    )

    assert result.impacts[0].combined_return == pytest.approx(-0.12)
    assert result.pnl_percent == pytest.approx(-0.12)


def test_negative_shock_reverses_sensitivity_interval_order() -> None:
    result = ScenarioEngine().simulate(
        _portfolio(position_value=100_000, cash_value=0),
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.20,
                "decimal_return",
                "NASDAQ down 20%",
            )
        ),
        factors=RISK_FACTORS,
        exposures=(_exposure(low=0.8, high=1.2),),
    )

    assert result.pnl_percent_low == pytest.approx(-0.24)
    assert result.pnl_percent_high == pytest.approx(-0.16)


def test_unmapped_weight_is_not_silently_treated_as_covered() -> None:
    result = ScenarioEngine().simulate(
        _portfolio(position_value=100_000, cash_value=0),
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.20,
                "decimal_return",
                "NASDAQ down 20%",
            )
        ),
        factors=RISK_FACTORS,
        exposures=(),
    )

    assert result.pnl_percent == 0
    assert result.uncovered_weight == pytest.approx(1)
    assert result.confidence_score <= 60
    assert any("no mapping" in item for item in result.warnings)


def test_unit_mismatch_and_future_exposure_are_rejected() -> None:
    with pytest.raises(ValueError, match="unit mismatch"):
        ScenarioEngine().simulate(
            _portfolio(),
            _scenario(
                FactorShock(
                    "us_policy_rate",
                    0.01,
                    "decimal_return",
                    "wrong unit",
                )
            ),
            factors=RISK_FACTORS,
            exposures=(),
        )

    future = replace(_exposure(), as_of_date=date(2026, 7, 31))
    with pytest.raises(ValueError, match="dated after"):
        ScenarioEngine().simulate(
            _portfolio(),
            _scenario(
                FactorShock(
                    "equity_nasdaq",
                    -0.2,
                    "decimal_return",
                    "shock",
                )
            ),
            factors=RISK_FACTORS,
            exposures=(future,),
        )


def test_portfolio_reconciliation_and_currency_conventions_are_enforced() -> None:
    with pytest.raises(ValueError, match="weight does not reconcile"):
        replace(
            _portfolio(),
            positions=(
                ScenarioPosition(
                    instrument=_instrument(1, "QQQM"),
                    currency="USD",
                    market_value=50_000,
                    weight=0.6,
                ),
            ),
        )
    with pytest.raises(ValueError, match="uppercase"):
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.2,
                "decimal_return",
                "shock",
            ),
            currency_shocks={"usd": 0.1},
        )
    with pytest.raises(ValueError, match="base currency"):
        ScenarioEngine().simulate(
            _portfolio(position_value=100_000, cash_value=0),
            _scenario(
                FactorShock(
                    "equity_nasdaq",
                    -0.2,
                    "decimal_return",
                    "shock",
                ),
                currency_shocks={"USD": 0.1},
            ),
            factors=RISK_FACTORS,
            exposures=(_exposure(),),
        )


def test_irrelevant_exposure_is_rejected_and_unused_fx_is_disclosed() -> None:
    unrelated = replace(_exposure(), asset_id=999)
    with pytest.raises(ValueError, match="not in the portfolio"):
        ScenarioEngine().simulate(
            _portfolio(),
            _scenario(
                FactorShock(
                    "equity_nasdaq",
                    -0.2,
                    "decimal_return",
                    "shock",
                )
            ),
            factors=RISK_FACTORS,
            exposures=(unrelated,),
        )

    result = ScenarioEngine().simulate(
        _portfolio(),
        _scenario(
            FactorShock(
                "equity_nasdaq",
                -0.2,
                "decimal_return",
                "shock",
            ),
            currency_shocks={"HKD": 0.1},
        ),
        factors=RISK_FACTORS,
        exposures=(_exposure(),),
    )

    assert any("no matching" in item for item in result.warnings)
