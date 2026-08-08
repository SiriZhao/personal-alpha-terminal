from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from personal_alpha_terminal.data.market_data.schemas import Market
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment


class CertificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    minimum_source_coverage: Decimal = Decimal("0.98")
    minimum_cross_source_match: Decimal = Decimal("0.98")
    maximum_price_relative_error: Decimal = Decimal("0.005")
    maximum_volume_relative_error: Decimal = Decimal("0.05")
    maximum_action_value_relative_error: Decimal = Decimal("0.01")
    minimum_random_sample: int = 104
    minimum_suspension_cases: int = 3
    minimum_delisted_cases: int = 3
    minimum_split_cases: int = 3
    minimum_dividend_cases: int = 10


@dataclass(frozen=True, slots=True)
class SourceBar:
    source: str
    provider: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adjusted_close: Decimal | None


@dataclass(frozen=True, slots=True)
class CorporateActionEvidence:
    source: str
    provider: str
    action_type: str
    effective_date: date
    cash_amount: Decimal | None = None
    split_ratio: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TradingStatusEvidence:
    source: str
    provider: str
    session_date: date
    status: str


@dataclass(frozen=True, slots=True)
class InstrumentEvidence:
    symbol: str
    market: Market
    segment: MarketSegment
    security_type: str
    expected_sessions: tuple[date, ...]
    bars: tuple[SourceBar, ...]
    action_coverage_sources: tuple[str, ...]
    actions: tuple[CorporateActionEvidence, ...] = ()
    trading_status: tuple[TradingStatusEvidence, ...] = ()
    listing_date: date | None = None
    delisting_date: date | None = None
    random_sample: bool = True


@dataclass(frozen=True, slots=True)
class CertificationFinding:
    code: str
    severity: str
    message: str
    trade_date: date | None = None


@dataclass(frozen=True, slots=True)
class InstrumentCertificationResult:
    symbol: str
    market: Market
    segment: MarketSegment
    security_type: str
    status: CertificationStatus
    source_count: int
    expected_sessions: int
    matched_sessions: int
    price_mismatches: int
    volume_mismatches: int
    findings: tuple[CertificationFinding, ...]
    has_suspension_case: bool
    has_delisting_case: bool
    has_split_case: bool
    has_dividend_case: bool
    random_sample: bool


@dataclass(frozen=True, slots=True)
class CertificationGateResult:
    status: CertificationStatus
    results: tuple[InstrumentCertificationResult, ...]
    blockers: tuple[str, ...]
    segment_counts: dict[str, int]

    @property
    def random_sample_size(self) -> int:
        return sum(item.random_sample for item in self.results)
