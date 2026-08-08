from dataclasses import dataclass
from datetime import date, datetime

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


@dataclass(frozen=True, slots=True)
class FactorPricePoint:
    date: date
    # Adjusted for return calculations; raw_close is for valuation ratios.
    close: float
    raw_close: float | None = None


@dataclass(frozen=True, slots=True)
class FactorFinancialPoint:
    period_end: date
    period_type: str
    available_at: datetime
    revenue: float | None
    free_cash_flow: float | None
    roe: float | None
    roic: float | None
    pe: float | None
    pb: float | None
    eps: float | None
    shares_outstanding: float | None
    ps: float | None = None
    gross_margin: float | None = None
    debt_ratio: float | None = None
    source: str = "unknown"
    revision_id: str = "unknown"
    data_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class FactorAssetData:
    instrument: GraphInstrument
    prices: tuple[FactorPricePoint, ...]
    financials: tuple[FactorFinancialPoint, ...]


@dataclass(frozen=True, slots=True)
class FactorDataset:
    assets: tuple[FactorAssetData, ...]


@dataclass(frozen=True, slots=True)
class FactorStockScore:
    as_of_date: date
    instrument: GraphInstrument
    raw_factors: dict[str, float | None]
    normalized_factors: dict[str, float | None]
    category_scores: dict[str, float | None]
    factor_score: float
    category_coverage: int


@dataclass(frozen=True, slots=True)
class FactorSnapshotResult:
    run_id: int
    market: str
    as_of_date: date
    scores: tuple[FactorStockScore, ...]


@dataclass(frozen=True, slots=True)
class FactorBacktestPeriodResult:
    rebalance_date: date
    period_end_date: date
    selected: tuple[GraphInstrument, ...]
    portfolio_return: float
    benchmark_return: float
    excess_return: float


@dataclass(frozen=True, slots=True)
class FactorBacktestSummaryResult:
    period_count: int
    cumulative_return: float
    benchmark_cumulative_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    max_drawdown: float
    excess_hit_rate: float


@dataclass(frozen=True, slots=True)
class FactorBacktestResult:
    run_id: int
    market: str
    start_date: date
    end_date: date
    periods: tuple[FactorBacktestPeriodResult, ...]
    summary: FactorBacktestSummaryResult
