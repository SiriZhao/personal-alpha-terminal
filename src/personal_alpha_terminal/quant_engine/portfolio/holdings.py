from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Holding:
    permanent_security_id: str
    ticker: str
    quantity: float
    cost_basis: float
    market_price: float
    sector: str

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.market_price - self.cost_basis)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    as_of: datetime
    holdings: tuple[Holding, ...]
    cash: float

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("portfolio as_of must be timezone-aware")
        if self.cash < 0 or any(item.quantity < 0 for item in self.holdings):
            raise ValueError("initial quant portfolio is long-only without negative cash")

    @property
    def total_value(self) -> float:
        return self.cash + sum(item.market_value for item in self.holdings)

    @property
    def weights(self) -> dict[str, float]:
        total = self.total_value
        return {
            item.permanent_security_id: item.market_value / total
            for item in self.holdings
            if total > 0
        }
