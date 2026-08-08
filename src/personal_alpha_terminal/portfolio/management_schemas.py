from dataclasses import dataclass
from datetime import date, datetime

from personal_alpha_terminal.portfolio.schemas import FxSeries


@dataclass(frozen=True, slots=True)
class ManagedAsset:
    id: int
    symbol: str
    name: str
    asset_class: str
    currency: str
    industry: str


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    id: int
    transaction_type: str
    trade_date: date
    settlement_date: date
    currency: str
    fx_rate_to_base: float
    available_time: datetime
    asset: ManagedAsset | None = None
    quantity: float | None = None
    unit_price: float | None = None
    cash_amount: float | None = None
    fee_amount: float = 0.0


@dataclass(frozen=True, slots=True)
class TransactionDraft:
    transaction_type: str
    trade_date: date
    settlement_date: date
    currency: str
    fx_rate_to_base: float
    event_time: datetime
    available_time: datetime
    stock_id: int | None = None
    quantity: float | None = None
    unit_price: float | None = None
    cash_amount: float | None = None
    fee_amount: float = 0.0
    source: str = "manual"
    external_id: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class AssetPricePoint:
    date: date
    close: float


@dataclass(frozen=True, slots=True)
class AssetPriceSeries:
    asset: ManagedAsset
    values: tuple[AssetPricePoint, ...]


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    key: str
    label: str
    target_weight: float


@dataclass(frozen=True, slots=True)
class PortfolioManagementData:
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    start_date: date
    end_date: date
    transactions: tuple[LedgerEvent, ...]
    prices: tuple[AssetPriceSeries, ...]
    fx_series: tuple[FxSeries, ...]
    benchmark: ManagedAsset
    benchmark_prices: tuple[AssetPricePoint, ...]
    targets: tuple[AllocationTarget, ...]


@dataclass(frozen=True, slots=True)
class PortfolioDailyPoint:
    date: date
    value: float
    external_flow: float
    daily_return: float | None
    cumulative_return: float
    drawdown: float


@dataclass(frozen=True, slots=True)
class PositionAllocation:
    key: str
    symbol: str
    name: str
    asset_class: str
    currency: str
    industry: str
    quantity: float
    market_value: float
    weight: float


@dataclass(frozen=True, slots=True)
class RebalanceSuggestion:
    key: str
    label: str
    action: str
    current_weight: float
    target_weight: float
    drift: float
    indicative_value: float


@dataclass(frozen=True, slots=True)
class PortfolioManagementResult:
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    start_date: date
    as_of_date: date
    opening_value: float
    total_value: float
    net_external_flow: float
    period_pnl: float
    latest_daily_return: float | None
    cumulative_return: float
    annualized_return: float | None
    annualized_volatility: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    beta: float | None
    alpha: float | None
    observation_count: int
    positions: tuple[PositionAllocation, ...]
    cash_values: dict[str, float]
    asset_class_exposure: dict[str, float]
    industry_exposure: dict[str, float]
    currency_exposure: dict[str, float]
    equity_curve: tuple[PortfolioDailyPoint, ...]
    rebalance_suggestions: tuple[RebalanceSuggestion, ...]
    data_fingerprint: str

    @property
    def largest_position_weight(self) -> float:
        return max((item.weight for item in self.positions), default=0.0)

    @property
    def concentration_hhi(self) -> float:
        """Herfindahl concentration across non-cash positions."""

        return sum(item.weight**2 for item in self.positions)
    warnings: tuple[str, ...]
