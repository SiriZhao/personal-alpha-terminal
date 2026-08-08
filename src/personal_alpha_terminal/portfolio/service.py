from datetime import date
from decimal import Decimal

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    PortfolioRiskMetric,
    PortfolioRiskRun,
    PortfolioStressResult,
)
from personal_alpha_terminal.portfolio.engine import apply_stress, calculate_risk
from personal_alpha_terminal.portfolio.repository import PortfolioRiskRepository
from personal_alpha_terminal.portfolio.schemas import (
    PortfolioRiskAnalysis,
    PortfolioRiskResult,
    PositionRisk,
    PositionStressImpact,
    RiskPortfolioOption,
    RiskSeriesPoint,
    StressScenario,
    StressTestResult,
)


class PortfolioRiskService:
    """Orchestrate explainable historical risk and static stress scenarios."""

    def __init__(self, repository: PortfolioRiskRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def list_portfolios(self) -> tuple[RiskPortfolioOption, ...]:
        return self._repository.list_portfolios()

    def list_benchmarks(self) -> tuple[GraphInstrument, ...]:
        return self._repository.list_benchmarks()

    def run(
        self,
        *,
        portfolio_id: int,
        benchmark_stock_id: int,
        start_date: date,
        end_date: date,
        scenarios: tuple[StressScenario, ...] = (),
    ) -> PortfolioRiskAnalysis:
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        if len(scenarios) > self._settings.portfolio_stress_max_scenarios:
            raise ValueError(
                "too many stress scenarios; configured maximum is "
                f"{self._settings.portfolio_stress_max_scenarios}"
            )
        names = [scenario.name.strip() for scenario in scenarios]
        if any(not name for name in names):
            raise ValueError("stress scenario name cannot be empty")
        if len(set(names)) != len(names):
            raise ValueError("stress scenario names must be unique within a run")

        data = self._repository.load_data(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_stock_id,
            start_date=start_date,
            end_date=end_date,
            fx_max_staleness_days=self._settings.portfolio_fx_max_staleness_days,
        )
        run = PortfolioRiskRun(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_stock_id,
            as_of_date=data.as_of_date,
            start_date=start_date,
            end_date=end_date,
            status="running",
            parameters={
                "annual_risk_free_rate": (self._settings.portfolio_risk_annual_risk_free_rate),
                "minimum_observations": (self._settings.portfolio_risk_minimum_observations),
                "fx_max_staleness_days": (self._settings.portfolio_fx_max_staleness_days),
                "price_max_staleness_days": (self._settings.portfolio_price_max_staleness_days),
                "maximum_absolute_beta": (self._settings.portfolio_maximum_absolute_beta),
                "method": "current_weights_historical_returns",
                "stress_method": "position_beta_times_benchmark_plus_fx",
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()
        try:
            risk = calculate_risk(
                data,
                run_id=run.id,
                start_date=start_date,
                end_date=end_date,
                annual_risk_free_rate=(self._settings.portfolio_risk_annual_risk_free_rate),
                minimum_observations=(self._settings.portfolio_risk_minimum_observations),
                fx_max_staleness_days=(self._settings.portfolio_fx_max_staleness_days),
                maximum_absolute_beta=(self._settings.portfolio_maximum_absolute_beta),
                price_max_staleness_days=(self._settings.portfolio_price_max_staleness_days),
            )
            stress_tests = tuple(apply_stress(risk, scenario) for scenario in scenarios)
            self._persist_metric(risk)
            self._persist_stress_tests(stress_tests)
            run.status = "completed"
            self._repository.session.flush()
            return PortfolioRiskAnalysis(risk=risk, stress_tests=stress_tests)
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self, portfolio_id: int | None = None) -> PortfolioRiskAnalysis | None:
        run = self._repository.latest_run(portfolio_id)
        if run is None:
            return None
        metric = self._repository.metric_for_run(run.id)
        option = self._repository.portfolio_option(run.portfolio_id)
        if metric is None or option is None:
            return None
        position_rows = list(metric.position_risks)
        stock_ids = {_as_int(row["stock_id"]) for row in position_rows if "stock_id" in row}
        stock_ids.add(run.benchmark_stock_id)
        instruments = self._repository.instruments_by_ids(stock_ids)
        benchmark = instruments.get(run.benchmark_stock_id)
        if benchmark is None:
            return None
        positions = tuple(
            PositionRisk(
                instrument=instruments[_as_int(row["stock_id"])],
                currency=str(row["currency"]),
                industry=str(row["industry"]),
                market_value=_as_float(row["market_value"]),
                weight=_as_float(row["weight"]),
                beta=(_as_float(row["beta"]) if row.get("beta") is not None else None),
            )
            for row in position_rows
            if _as_int(row["stock_id"]) in instruments
        )
        risk = PortfolioRiskResult(
            run_id=run.id,
            portfolio_id=run.portfolio_id,
            portfolio_name=option.name,
            base_currency=option.base_currency,
            as_of_date=run.as_of_date,
            benchmark=benchmark,
            total_value=float(metric.total_value),
            annualized_return=float(metric.annualized_return),
            annualized_volatility=float(metric.annualized_volatility),
            max_drawdown=float(metric.max_drawdown),
            sharpe_ratio=(float(metric.sharpe_ratio) if metric.sharpe_ratio is not None else None),
            beta=float(metric.beta) if metric.beta is not None else None,
            observation_count=metric.observation_count,
            positions=positions,
            industry_exposure={
                str(key): float(value) for key, value in metric.industry_exposure.items()
            },
            currency_exposure={
                str(key): float(value) for key, value in metric.currency_exposure.items()
            },
            equity_curve=self._restore_curve(metric.equity_curve),
            drawdown_curve=self._restore_curve(metric.drawdown_curve),
        )
        stress_tests = tuple(
            self._restore_stress(risk, model)
            for model in self._repository.stress_results_for_run(run.id)
        )
        return PortfolioRiskAnalysis(risk=risk, stress_tests=stress_tests)

    def _persist_metric(self, risk: PortfolioRiskResult) -> None:
        self._repository.session.add(
            PortfolioRiskMetric(
                run_id=risk.run_id,
                total_value=self._decimal(risk.total_value),
                annualized_return=self._decimal(risk.annualized_return),
                annualized_volatility=self._decimal(risk.annualized_volatility),
                max_drawdown=self._decimal(risk.max_drawdown),
                sharpe_ratio=(
                    self._decimal(risk.sharpe_ratio) if risk.sharpe_ratio is not None else None
                ),
                beta=self._decimal(risk.beta) if risk.beta is not None else None,
                observation_count=risk.observation_count,
                industry_exposure=risk.industry_exposure,
                currency_exposure=risk.currency_exposure,
                position_weights={str(item.instrument.id): item.weight for item in risk.positions},
                position_risks=[
                    {
                        "stock_id": item.instrument.id,
                        "currency": item.currency,
                        "industry": item.industry,
                        "market_value": item.market_value,
                        "weight": item.weight,
                        "beta": item.beta,
                    }
                    for item in risk.positions
                ],
                equity_curve=self._serialize_curve(risk.equity_curve),
                drawdown_curve=self._serialize_curve(risk.drawdown_curve),
            )
        )

    def _persist_stress_tests(
        self,
        stress_tests: tuple[StressTestResult, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                PortfolioStressResult(
                    run_id=item.run_id,
                    scenario_name=item.scenario.name,
                    benchmark_shock=self._decimal(item.scenario.benchmark_shock),
                    currency_shocks=item.scenario.currency_shocks,
                    stressed_value=self._decimal(item.stressed_value),
                    pnl_amount=self._decimal(item.pnl_amount),
                    pnl_percent=self._decimal(item.pnl_percent),
                    uncovered_weight=self._decimal(item.uncovered_weight),
                    position_impacts=[
                        {
                            "stock_id": impact.instrument.id,
                            "weight": impact.weight,
                            "beta": impact.beta,
                            "market_return": impact.market_return,
                            "currency_return": impact.currency_return,
                            "combined_return": impact.combined_return,
                            "contribution": impact.contribution,
                            "pnl_amount": impact.pnl_amount,
                            "beta_covered": impact.beta_covered,
                        }
                        for impact in item.impacts
                    ],
                )
                for item in stress_tests
            ]
        )

    @staticmethod
    def _restore_stress(
        risk: PortfolioRiskResult,
        model: PortfolioStressResult,
    ) -> StressTestResult:
        instruments = {item.instrument.id: item.instrument for item in risk.positions}
        impacts = tuple(
            PositionStressImpact(
                instrument=instruments[_as_int(row["stock_id"])],
                weight=_as_float(row["weight"]),
                beta=(_as_float(row["beta"]) if row.get("beta") is not None else None),
                market_return=_as_float(row["market_return"]),
                currency_return=_as_float(row["currency_return"]),
                combined_return=_as_float(row["combined_return"]),
                contribution=_as_float(row["contribution"]),
                pnl_amount=_as_float(row["pnl_amount"]),
                beta_covered=bool(row["beta_covered"]),
            )
            for row in model.position_impacts
            if _as_int(row["stock_id"]) in instruments
        )
        scenario = StressScenario(
            name=model.scenario_name,
            benchmark_shock=float(model.benchmark_shock),
            currency_shocks={
                str(key): float(value) for key, value in model.currency_shocks.items()
            },
        )
        return StressTestResult(
            run_id=risk.run_id,
            scenario=scenario,
            original_value=risk.total_value,
            stressed_value=float(model.stressed_value),
            pnl_amount=float(model.pnl_amount),
            pnl_percent=float(model.pnl_percent),
            uncovered_weight=float(model.uncovered_weight),
            impacts=impacts,
        )

    @staticmethod
    def _serialize_curve(
        values: tuple[RiskSeriesPoint, ...],
    ) -> list[dict[str, object]]:
        return [{"date": item.date.isoformat(), "value": item.value} for item in values]

    @staticmethod
    def _restore_curve(
        values: list[dict[str, object]],
    ) -> tuple[RiskSeriesPoint, ...]:
        return tuple(
            RiskSeriesPoint(
                date=date.fromisoformat(str(item["date"])),
                value=_as_float(item["value"]),
            )
            for item in values
        )

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 12)))


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("persisted JSON value is not an integer")
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("persisted JSON value is not numeric")
    return float(value)
