from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

type Market = Literal["A", "HK", "US"]


@dataclass(frozen=True, slots=True)
class PriceBar:
    """Provider-independent daily OHLCV record.

    ``volume`` is normalized to traded shares/units, never provider-specific
    lots or hands.  Monetary turnover must still use instrument currency and
    must not be aggregated across currencies without FX conversion.
    """

    symbol: str
    market: Market
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    event_time: datetime
    available_time: datetime
    ingested_time: datetime
    adjusted_close: Decimal | None = None
    forward_adjusted_close: Decimal | None = None
    backward_adjusted_close: Decimal | None = None
    adjustment_method: str | None = None
    open_tradable: bool | None = None
    asset_type: Literal["stock", "etf", "index", "bond"] = "stock"
    volume_unit: Literal["share", "face_value", "none"] = "share"
    price_currency: str = ""
    share_unit: Decimal = Decimal("1")
    price_type: Literal[
        "unadjusted_ohlcv",
        "index_level_ohlcv",
        "clean_price_ohlcv",
    ] = "unadjusted_ohlcv"
    data_contract_version: str = "market-data-v1"

    def __post_init__(self) -> None:
        from personal_alpha_terminal.core.data_timestamps import DataTimestamps

        DataTimestamps(
            event_time=self.event_time,
            available_time=self.available_time,
            ingested_time=self.ingested_time,
        )
        if not self.price_currency:
            defaults = {"A": "CNY", "HK": "HKD", "US": "USD"}
            object.__setattr__(self, "price_currency", defaults[self.market])
        if len(self.price_currency) != 3 or self.price_currency != self.price_currency.upper():
            raise ValueError("price_currency must be an uppercase ISO-style code")
        if self.share_unit != Decimal("1"):
            raise ValueError("normalized price rows require share_unit=1")
        if self.asset_type in {"stock", "etf"} and self.volume_unit != "share":
            raise ValueError(f"{self.asset_type} volume_unit must be share")
        if self.asset_type == "bond" and self.volume_unit != "face_value":
            raise ValueError("bond volume_unit must be face_value")
        if self.asset_type == "index" and self.volume_unit not in {"share", "none"}:
            raise ValueError("index volume_unit must be share or none")
        if self.volume_unit == "none" and self.volume is not None:
            raise ValueError("volume must be absent when volume_unit is none")
        if self.data_contract_version != "market-data-v1":
            raise ValueError("unsupported market-data contract version")


@dataclass(frozen=True, slots=True)
class StockPriceBar(PriceBar):
    asset_type: Literal["stock"] = field(default="stock", init=False)


@dataclass(frozen=True, slots=True)
class ETFPriceBar(PriceBar):
    asset_type: Literal["etf"] = field(default="etf", init=False)


@dataclass(frozen=True, slots=True)
class IndexPriceBar(PriceBar):
    asset_type: Literal["index"] = field(default="index", init=False)


@dataclass(frozen=True, slots=True)
class BondPriceBar(PriceBar):
    asset_type: Literal["bond"] = field(default="bond", init=False)


class QualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    severity: QualitySeverity
    date: date | None = None


@dataclass(frozen=True, slots=True)
class DataQualityResult:
    bars: tuple[PriceBar, ...]
    issues: tuple[QualityIssue, ...]
    input_count: int
    rejected_count: int

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == QualitySeverity.ERROR for issue in self.issues)


type UpdateStatus = Literal["success", "cached", "no_data", "failed"]


@dataclass(frozen=True, slots=True)
class InstrumentUpdateResult:
    symbol: str
    market: Market
    source: str
    status: UpdateStatus
    start_date: date
    end_date: date
    provider: str = "unknown"
    fetched_count: int = 0
    valid_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    quality_issues: tuple[QualityIssue, ...] = ()
    error: str | None = None
    refresh_class: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DailyUpdateReport:
    started_on: date
    results: tuple[InstrumentUpdateResult, ...] = field(default_factory=tuple)
    provider_reconciled: bool = False
    corporate_action_certified: bool = False
    batch_timings: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        return sum(result.status == "success" for result in self.results)

    @property
    def no_data_count(self) -> int:
        return sum(result.status == "no_data" for result in self.results)

    @property
    def cached_count(self) -> int:
        return sum(result.status == "cached" for result in self.results)

    @property
    def failure_count(self) -> int:
        return sum(result.status == "failed" for result in self.results)

    @property
    def inserted_count(self) -> int:
        return sum(result.inserted_count for result in self.results)

    @property
    def updated_count(self) -> int:
        return sum(result.updated_count for result in self.results)

    @property
    def analysis_safe(self) -> bool:
        return bool(self.results) and all(
            result.status == "success"
            and not any(issue.severity == QualitySeverity.ERROR for issue in result.quality_issues)
            for result in self.results
        )


@dataclass(frozen=True, slots=True)
class UpsertResult:
    inserted_count: int
    updated_count: int
