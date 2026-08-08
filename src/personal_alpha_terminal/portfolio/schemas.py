from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


@dataclass(frozen=True, slots=True)
class RiskPortfolioOption:
    id: int
    name: str
    base_currency: str

    @property
    def label(self) -> str:
        return f"{self.name} · {self.base_currency}"


@dataclass(frozen=True, slots=True)
class RiskPricePoint:
    date: date
    close: float


@dataclass(frozen=True, slots=True)
class FxPoint:
    date: date
    rate: float


@dataclass(frozen=True, slots=True)
class FxSeries:
    base_currency: str
    quote_currency: str
    values: tuple[FxPoint, ...]


@dataclass(frozen=True, slots=True)
class RiskPositionData:
    instrument: GraphInstrument
    currency: str
    industry: str
    quantity: float
    prices: tuple[RiskPricePoint, ...]


@dataclass(frozen=True, slots=True)
class PortfolioRiskData:
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    cash_balance: float
    as_of_date: date
    positions: tuple[RiskPositionData, ...]
    benchmark: GraphInstrument
    benchmark_currency: str
    benchmark_prices: tuple[RiskPricePoint, ...]
    fx_series: tuple[FxSeries, ...]


@dataclass(frozen=True, slots=True)
class PositionRisk:
    instrument: GraphInstrument
    currency: str
    industry: str
    market_value: float
    weight: float
    beta: float | None


@dataclass(frozen=True, slots=True)
class RiskSeriesPoint:
    date: date
    value: float


@dataclass(frozen=True, slots=True)
class PortfolioRiskResult:
    run_id: int
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    as_of_date: date
    benchmark: GraphInstrument
    total_value: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_ratio: float | None
    beta: float | None
    observation_count: int
    positions: tuple[PositionRisk, ...]
    industry_exposure: dict[str, float]
    currency_exposure: dict[str, float]
    equity_curve: tuple[RiskSeriesPoint, ...]
    drawdown_curve: tuple[RiskSeriesPoint, ...]

    @property
    def largest_position_weight(self) -> float:
        return max((item.weight for item in self.positions), default=0.0)

    @property
    def concentration_hhi(self) -> float:
        """Herfindahl concentration across risky positions; cash is excluded."""

        return sum(item.weight**2 for item in self.positions)


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    benchmark_shock: float
    currency_shocks: dict[str, float]


@dataclass(frozen=True, slots=True)
class PositionStressImpact:
    instrument: GraphInstrument
    weight: float
    beta: float | None
    market_return: float
    currency_return: float
    combined_return: float
    contribution: float
    pnl_amount: float
    beta_covered: bool


@dataclass(frozen=True, slots=True)
class StressTestResult:
    run_id: int
    scenario: StressScenario
    original_value: float
    stressed_value: float
    pnl_amount: float
    pnl_percent: float
    uncovered_weight: float
    impacts: tuple[PositionStressImpact, ...]


@dataclass(frozen=True, slots=True)
class PortfolioRiskAnalysis:
    risk: PortfolioRiskResult
    stress_tests: tuple[StressTestResult, ...]
