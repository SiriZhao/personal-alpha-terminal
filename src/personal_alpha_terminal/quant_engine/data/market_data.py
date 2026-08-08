from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from personal_alpha_terminal.research.data_gate import ResearchDataAuthorization


@dataclass(frozen=True, slots=True)
class MarketDataQuery:
    permanent_security_id: str
    ticker: str
    market: str
    asset_type: str
    start_date: date
    end_date: date
    currency: str
    adjustment_mode: str

    def __post_init__(self) -> None:
        if not self.permanent_security_id.strip():
            raise ValueError("permanent_security_id is required")
        if not self.ticker.strip():
            raise ValueError("ticker is required")
        if self.start_date > self.end_date:
            raise ValueError("market-data start_date cannot follow end_date")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise ValueError("currency must be a three-letter uppercase code")


@dataclass(frozen=True, slots=True)
class MarketBar:
    permanent_security_id: str
    ticker: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None
    currency: str
    event_time: datetime
    available_time: datetime
    ingested_time: datetime
    source: str
    provider: str
    adjustment_mode: str
    open_tradable: bool = True

    def __post_init__(self) -> None:
        if not self.permanent_security_id.strip() or not self.ticker.strip():
            raise ValueError("market bar requires permanent identity and ticker")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise ValueError("market bar currency must be a three-letter uppercase code")
        if not self.adjustment_mode.strip():
            raise ValueError("market bar adjustment_mode is required")
        if any(value.tzinfo is None for value in self.timestamps):
            raise ValueError("market-data timestamps must be timezone-aware")
        if self.available_time < self.event_time:
            raise ValueError("available_time cannot precede event_time")
        if self.ingested_time < self.available_time:
            raise ValueError("ingested_time cannot precede available_time")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC envelope")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")
        if not self.source.strip() or not self.provider.strip():
            raise ValueError("market-data lineage is required")

    @property
    def timestamps(self) -> tuple[datetime, datetime, datetime]:
        return self.event_time, self.available_time, self.ingested_time


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series: str
    observation_date: date
    value: float
    available_time: datetime
    ingested_time: datetime
    source: str
    provider: str

    def __post_init__(self) -> None:
        if self.available_time.tzinfo is None or self.ingested_time.tzinfo is None:
            raise ValueError("macro timestamps must be timezone-aware")
        if self.ingested_time < self.available_time:
            raise ValueError("macro ingested_time cannot precede available_time")


@dataclass(frozen=True, slots=True)
class QuantMarketDataset:
    query: MarketDataQuery
    authorization: ResearchDataAuthorization
    bars: tuple[MarketBar, ...]
    data_version: str
    from_cache: bool

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("quant market dataset cannot be empty")
        dates = [bar.trade_date for bar in self.bars]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("market bars must be unique and sorted by trade_date")
