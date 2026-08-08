from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.models import (
    AssetRiskFactorExposure,
    Portfolio,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    ResearchReport,
    ScenarioAssetImpact,
    ScenarioDefinitionModel,
    ScenarioRiskFactor,
    ScenarioSimulationRun,
    Stock,
)
from personal_alpha_terminal.reports.service import ResearchReportService
from personal_alpha_terminal.scenario_simulator.repository import (
    ScenarioRepository,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorShock,
    ScenarioDefinition,
)
from personal_alpha_terminal.scenario_simulator.service import ScenarioService


def test_latest_portfolio_scenario_persists_mapping_impacts_and_report(
    session_factory: sessionmaker[Session],
) -> None:
    as_of = date(2026, 7, 30)
    with session_factory() as session:
        qqqm = _stock("QQQM", "etf")
        voo = _stock("VOO", "etf")
        benchmark = _stock("NDX", "index")
        session.add_all([qqqm, voo, benchmark])
        portfolio = Portfolio(
            name="Scenario Portfolio",
            base_currency="USD",
            cash_balance=Decimal("100"),
        )
        session.add(portfolio)
        session.flush()
        run = PortfolioRiskRun(
            portfolio_id=portfolio.id,
            benchmark_stock_id=benchmark.id,
            as_of_date=as_of,
            start_date=date(2025, 1, 1),
            end_date=as_of,
            status="completed",
            parameters={"method": "integration_fixture"},
        )
        session.add(run)
        session.flush()
        session.add(
            PortfolioRiskMetric(
                run_id=run.id,
                total_value=Decimal("1000"),
                annualized_return=Decimal("0.1"),
                annualized_volatility=Decimal("0.2"),
                max_drawdown=Decimal("-0.1"),
                sharpe_ratio=Decimal("0.5"),
                beta=Decimal("1"),
                observation_count=252,
                industry_exposure={"Technology": 0.9, "Cash": 0.1},
                currency_exposure={"USD": 1.0},
                position_weights={str(qqqm.id): 0.6, str(voo.id): 0.3},
                position_risks=[
                    {
                        "stock_id": qqqm.id,
                        "currency": "USD",
                        "industry": "Technology",
                        "market_value": 600.0,
                        "weight": 0.6,
                        "beta": 1.0,
                    },
                    {
                        "stock_id": voo.id,
                        "currency": "USD",
                        "industry": "Broad Market",
                        "market_value": 300.0,
                        "weight": 0.3,
                        "beta": 0.8,
                    },
                ],
                equity_curve=[],
                drawdown_curve=[],
            )
        )
        session.flush()
        service = ScenarioService(
            ScenarioRepository(session),
            ResearchReportService(session),
        )
        scenario = ScenarioDefinition(
            name="NASDAQ -20%",
            scenario_type="custom",
            description="Integration downside assumption",
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
            data_sources=("test:user_input",),
        )
        result, report = service.run_latest(
            portfolio_id=portfolio.id,
            scenario=scenario,
            exposure_overrides=(
                AssetFactorExposure(
                    asset_id=voo.id,
                    factor_code="equity_nasdaq",
                    sensitivity=0.5,
                    sensitivity_low=0.4,
                    sensitivity_high=0.6,
                    as_of_date=as_of,
                    method="manual",
                    source="test:manual_mapping",
                    confidence_score=70,
                ),
            ),
        )
        session.commit()

        assert result.pnl_percent == pytest.approx(-0.15)
        assert result.stressed_value == pytest.approx(850)
        assert result.risk_level == "High"
        assert result.mapped_weight == pytest.approx(0.9)
        assert result.uncovered_weight == pytest.approx(0)
        assert report.subject_key == str(result.run_id)
        assert session.scalar(select(func.count(ScenarioRiskFactor.id))) == 9
        assert session.scalar(select(func.count(ScenarioDefinitionModel.id))) == 1
        assert session.scalar(select(func.count(ScenarioSimulationRun.id))) == 1
        assert session.scalar(select(func.count(ScenarioAssetImpact.id))) == 2
        assert session.scalar(select(func.count(AssetRiskFactorExposure.id))) == 0
        assert (
            session.scalar(
                select(func.count(ResearchReport.id)).where(
                    ResearchReport.report_type == "portfolio_scenario"
                )
            )
            == 1
        )

        versioned_mapping = AssetFactorExposure(
            asset_id=voo.id,
            factor_code="equity_nasdaq",
            sensitivity=0.5,
            sensitivity_low=0.4,
            sensitivity_high=0.6,
            as_of_date=as_of,
            method="verified_regression",
            source="test:versioned_mapping",
            confidence_score=70,
        )
        service.register_exposures((versioned_mapping,))
        service.register_exposures((versioned_mapping,))
        with pytest.raises(ValueError, match="already exists"):
            service.register_exposures((replace(versioned_mapping, sensitivity=0.55),))
        snapshot, mappings = service.mapping_snapshot(portfolio.id)
        session.commit()

        assert snapshot.as_of_date == as_of
        assert {(item.asset_id, item.factor_code, item.source) for item in mappings} == {
            (qqqm.id, "equity_nasdaq", "identity_proxy:nasdaq_tracking_etf"),
            (voo.id, "equity_sp500", "identity_proxy:sp500_tracking_etf"),
            (voo.id, "equity_nasdaq", "test:versioned_mapping"),
        }
        assert session.scalar(select(func.count(AssetRiskFactorExposure.id))) == 1


def _stock(symbol: str, asset_type: str) -> Stock:
    return Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        asset_type=asset_type,
        currency="USD",
        timezone="America/New_York",
    )
