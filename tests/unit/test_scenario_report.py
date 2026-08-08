from datetime import date

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.dashboard.charts import (
    asset_sensitivity_heatmap,
    scenario_comparison_chart,
    scenario_risk_map_chart,
)
from personal_alpha_terminal.scenario_simulator.catalog import RISK_FACTORS
from personal_alpha_terminal.scenario_simulator.engine import ScenarioEngine
from personal_alpha_terminal.scenario_simulator.report import (
    comparison_payload,
    render_scenario_report,
    visualization_payload,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorShock,
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioPortfolio,
    ScenarioPosition,
    ScenarioResult,
)


def _result() -> ScenarioResult:
    instrument = GraphInstrument(
        id=1,
        key="etf:1",
        symbol="QQQM",
        name="QQQM",
        market="US",
        asset_type="etf",
        industry=None,
    )
    portfolio = ScenarioPortfolio(
        portfolio_id=1,
        portfolio_name="Growth",
        base_currency="USD",
        as_of_date=date(2026, 7, 30),
        total_value=100_000,
        cash_value=20_000,
        positions=(ScenarioPosition(instrument, "USD", 80_000, 0.8),),
    )
    scenario = ScenarioDefinition(
        name="NASDAQ -20%",
        scenario_type="custom",
        description="User-defined downside",
        factor_shocks=(
            FactorShock(
                "equity_nasdaq",
                -0.20,
                "decimal_return",
                "user assumption",
            ),
        ),
        currency_shocks={},
        evidence_level="user_assumption",
        data_sources=("user_input:scenario",),
    )
    exposure = AssetFactorExposure(
        asset_id=1,
        factor_code="equity_nasdaq",
        sensitivity=1,
        sensitivity_low=0.9,
        sensitivity_high=1.1,
        as_of_date=portfolio.as_of_date,
        method="identity_proxy",
        source="test",
        confidence_score=90,
    )
    return ScenarioEngine().simulate(
        portfolio,
        scenario,
        factors=RISK_FACTORS,
        exposures=(exposure,),
    )


def test_report_contains_assumptions_sources_risk_and_limits() -> None:
    result = _result()
    report = render_scenario_report(result)

    assert report.report_type == "portfolio_scenario"
    assert "## Scenario Assumptions" in report.markdown
    assert "## Asset Impact" in report.markdown
    assert "## Data Sources and Assumption Labels" in report.markdown
    assert "not a probability" in report.markdown
    assert "not a forecast" in report.markdown


def test_visualizations_include_risk_map_comparison_and_sensitivity() -> None:
    result = _result()
    payload = visualization_payload(result)
    comparison_model = ScenarioComparison(
        portfolio_id=1,
        as_of_date=date(2026, 7, 30),
        results=(result,),
    )
    comparison = comparison_payload(comparison_model)

    assert payload["risk_map"][0]["asset"] == "QQQM"
    assert payload["asset_sensitivity"][0]["factor"] == "equity_nasdaq"
    assert comparison["scenarios"][0]["scenario"] == "NASDAQ -20%"
    assert len(scenario_risk_map_chart(result).data) == 1
    assert len(asset_sensitivity_heatmap(result).data) == 1
    assert len(scenario_comparison_chart(comparison_model).data) == 1
