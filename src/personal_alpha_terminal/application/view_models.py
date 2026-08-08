"""Presentation-neutral read models shared by reports and portfolio analytics."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class InstrumentOption:
    id: int
    symbol: str
    name: str
    market: str

    @property
    def label(self) -> str:
        return f"{self.symbol} - {self.name} ({self.market})"


@dataclass(frozen=True, slots=True)
class PricePoint:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    source: str


@dataclass(frozen=True, slots=True)
class MarketIndexSnapshot:
    instrument: InstrumentOption
    date: date
    close: Decimal
    change_pct: float | None
    volume: int | None
    currency: str
    source: str


@dataclass(frozen=True, slots=True)
class StockDetail:
    instrument: InstrumentOption
    exchange: str
    currency: str
    industry: str | None
    list_date: date | None
    is_active: bool
    prices: tuple[PricePoint, ...]

    @property
    def latest(self) -> PricePoint | None:
        return self.prices[-1] if self.prices else None

    @property
    def period_change_pct(self) -> float | None:
        if len(self.prices) < 2 or self.prices[0].close == 0:
            return None
        return float(self.prices[-1].close / self.prices[0].close - 1)


@dataclass(frozen=True, slots=True)
class PortfolioOption:
    id: int
    name: str
    base_currency: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.base_currency})"


@dataclass(frozen=True, slots=True)
class PositionView:
    stock_id: int
    symbol: str
    name: str
    market: str
    industry: str | None
    currency: str
    quantity: Decimal
    average_cost: Decimal | None
    last_price: Decimal | None
    price_date: date | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    weight: float | None


@dataclass(frozen=True, slots=True)
class CurrencyTotal:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    portfolio: PortfolioOption
    description: str | None
    as_of_date: date | None
    cash_balance: Decimal
    total_value: Decimal | None
    invested_value: Decimal | None
    valuation_complete: bool
    positions: tuple[PositionView, ...]
    currency_totals: tuple[CurrencyTotal, ...]


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    date: date
    value: float


@dataclass(frozen=True, slots=True)
class Exposure:
    name: str
    weight: float


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    max_drawdown: float
    daily_var_95: float
    top_position_weight: float
    effective_positions: float
    observations: int


@dataclass(frozen=True, slots=True)
class PortfolioRiskView:
    portfolio: PortfolioOption
    available: bool
    reason: str | None
    metrics: RiskMetrics | None
    equity_curve: tuple[SeriesPoint, ...] = ()
    drawdown_curve: tuple[SeriesPoint, ...] = ()
    market_exposure: tuple[Exposure, ...] = ()
    industry_exposure: tuple[Exposure, ...] = ()
