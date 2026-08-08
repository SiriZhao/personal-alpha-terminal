from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from personal_alpha_terminal.data.market_data.schemas import Market
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment


@dataclass(frozen=True, slots=True)
class SecurityMasterRecord:
    symbol: str
    name: str
    market: Market
    exchange: str
    currency: str
    timezone: str
    listing_date: date | None
    delisting_date: date | None
    security_type: str
    is_active: bool
    segment: MarketSegment
    source: str
    provider: str
    available_time: datetime
    ingested_time: datetime

    @property
    def canonical_code(self) -> str:
        return f"{self.market}:{self.exchange}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class SecurityMasterBatch:
    market: Market
    snapshot_date: date
    source: str
    provider: str
    available_time: datetime
    ingested_time: datetime
    records: tuple[SecurityMasterRecord, ...]
    research_eligible: bool
    certification_basis: str

    def __post_init__(self) -> None:
        if not self.records:
            raise ValueError("security-master batch cannot be empty")
        if any(item.market != self.market for item in self.records):
            raise ValueError("security-master batch cannot mix markets")
        keys = [item.canonical_code for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("security-master batch contains duplicate canonical codes")
        if self.research_eligible and not self.certification_basis.strip():
            raise ValueError("research-eligible security master needs a certification basis")


class SecurityMasterProvider(Protocol):
    """Point-in-time provider contract for a single-market security master."""

    source: str
    provider: str

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch: ...
