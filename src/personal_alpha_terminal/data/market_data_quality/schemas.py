from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from personal_alpha_terminal.data.market_data.schemas import Market


class MarketSegment(StrEnum):
    SSE_MAIN = "sse_main"
    SZSE_MAIN = "szse_main"
    CHINEXT = "chinext"
    STAR = "star"
    A_ETF = "a_etf"
    NYSE = "nyse"
    NASDAQ = "nasdaq"
    US_ETF = "us_etf"
    US_INDEX = "us_index"
    HK_MAIN = "hk_main"
    HK_ETF = "hk_etf"


class SizeBucket(StrEnum):
    LARGE = "large"
    MID_SMALL = "mid_small"
    UNKNOWN = "unknown"


class ListingAgeBucket(StrEnum):
    NEW = "new"
    ESTABLISHED = "established"
    UNKNOWN = "unknown"


class AdjustmentMode(StrEnum):
    RAW = "raw"
    FORWARD = "qfq"
    BACKWARD = "hfq"
    PROVIDER_TOTAL_RETURN = "provider_total_return"
    POINT_IN_TIME_TOTAL_RETURN = "point_in_time_total_return"


class PriceUseCase(StrEnum):
    DISPLAY = "display"
    VALUATION = "valuation"
    EXECUTION = "execution"
    BACKTEST = "backtest"
    CROSS_SOURCE_VALIDATION = "cross_source_validation"


class CorporateActionType(StrEnum):
    CASH_DIVIDEND = "cash_dividend"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    RIGHTS = "rights"
    DELISTING = "delisting"
    SYMBOL_CHANGE = "symbol_change"


class RunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class UniverseCandidate:
    stock_id: int
    symbol: str
    market: Market
    exchange: str
    segment: MarketSegment
    asset_type: str
    size_bucket: SizeBucket
    listing_age_bucket: ListingAgeBucket
    list_date: date | None
    delist_date: date | None
    market_cap: Decimal | None = None
    reason: str = "listed_on_snapshot_date"
    source: str = "legacy_unknown"
    provider: str = "legacy_unknown"
    available_time: datetime | None = None
    ingested_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class SamplingPlan:
    segment_quotas: dict[MarketSegment, int]
    minimum_total: int = 100
    minimum_large_cap: int = 10
    minimum_mid_small_cap: int = 10
    minimum_new_listings: int = 5
    minimum_delisted: int = 5

    def __post_init__(self) -> None:
        if self.minimum_total < 100:
            raise ValueError("A research-grade sample must contain at least 100 instruments.")
        if any(quota < 1 for quota in self.segment_quotas.values()):
            raise ValueError("Every configured market segment must have a positive quota.")
        if sum(self.segment_quotas.values()) < self.minimum_total:
            raise ValueError("Segment quotas must cover the minimum total sample size.")


@dataclass(frozen=True, slots=True)
class SampleSelection:
    selected: tuple[UniverseCandidate, ...]
    seed: int
    plan: SamplingPlan
    shortages: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.shortages and len(self.selected) >= self.plan.minimum_total


@dataclass(frozen=True, slots=True)
class CorporateActionRecord:
    stock_id: int
    action_type: CorporateActionType
    effective_date: date
    announcement_date: date
    available_date: date
    event_time: datetime
    available_time: datetime
    ingested_time: datetime
    source: str
    provider: str
    split_ratio: Decimal | None = None
    cash_amount: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarSession:
    exchange: str
    session_date: date
    is_open: bool
    open_time: datetime | None
    close_time: datetime | None
    timezone: str
    source: str
    provider: str
    available_time: datetime
    ingested_time: datetime


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    trade_date: date
    close: Decimal
    adjusted_close: Decimal | None
    source: str
    provider: str
    event_time: datetime | None = None
    available_time: datetime | None = None
    ingested_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoricalQualityIssue:
    code: str
    severity: str
    message: str
    trade_date: date | None = None


@dataclass(frozen=True, slots=True)
class InstrumentQualityMetrics:
    stock_id: int
    symbol: str
    market: Market
    segment: MarketSegment
    expected_sessions: int
    observed_sessions: int
    missing_sessions: int
    missing_rate: float
    anomalous_observations: int
    anomaly_rate: float
    first_date: date | None
    last_date: date | None
    issues: tuple[HistoricalQualityIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class QualityReport:
    generated_at: datetime
    history_start: date
    history_end: date
    status: RunStatus
    sample: SampleSelection | None
    instrument_results: tuple[InstrumentQualityMetrics, ...] = ()
    source_counts: dict[str, int] = field(default_factory=dict)
    provider_counts: dict[str, int] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    @property
    def expected_sessions(self) -> int:
        return sum(item.expected_sessions for item in self.instrument_results)

    @property
    def observed_sessions(self) -> int:
        return sum(item.observed_sessions for item in self.instrument_results)

    @property
    def missing_rate(self) -> float | None:
        expected = self.expected_sessions
        if expected == 0:
            return None
        return sum(item.missing_sessions for item in self.instrument_results) / expected

    @property
    def anomaly_rate(self) -> float | None:
        observed = self.observed_sessions
        if observed == 0:
            return None
        return sum(item.anomalous_observations for item in self.instrument_results) / observed
