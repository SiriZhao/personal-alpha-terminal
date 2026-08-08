from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from personal_alpha_terminal.data.market_data.schemas import Market

type AssetType = Literal["stock", "etf", "index", "bond"]
type RawVolumeUnit = Literal["share", "hand", "face_value", "none", "unknown"]
type VolumeUnit = Literal["share", "face_value", "none"]
type PriceType = Literal[
    "unadjusted_ohlcv",
    "index_level_ohlcv",
    "clean_price_ohlcv",
]

DATA_CONTRACT_VERSION = "market-data-v1"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider: str
    market: Market
    asset_type: AssetType
    endpoint: str
    raw_volume_unit: RawVolumeUnit
    volume_unit: VolumeUnit
    price_type: PriceType
    supported: bool
    volume_multiplier: Decimal
    raw_share_unit: Decimal

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.endpoint.strip():
            raise ValueError("provider capability requires provider and endpoint")
        if self.volume_multiplier <= 0 or self.raw_share_unit <= 0:
            raise ValueError("volume multiplier and raw share unit must be positive")
        if self.raw_volume_unit == "unknown" and self.supported:
            raise ValueError("a capability with unknown raw volume units cannot be supported")
        if self.raw_volume_unit == "none" and self.volume_unit != "none":
            raise ValueError("a no-volume endpoint cannot normalize to a volume unit")
        if self.volume_unit == "none" and self.raw_volume_unit != "none":
            raise ValueError("a volume-bearing endpoint cannot normalize to none")

    @property
    def key(self) -> tuple[str, Market, AssetType]:
        return (self.provider, self.market, self.asset_type)


@dataclass(frozen=True, slots=True)
class AssetPriceRequest:
    symbol: str
    market: Market
    asset_type: AssetType
    price_currency: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be later than end_date")
        if len(self.price_currency) != 3 or self.price_currency != self.price_currency.upper():
            raise ValueError("price_currency must be an uppercase ISO-style code")


@dataclass(frozen=True, slots=True)
class ProviderRawBar:
    symbol: str
    market: Market
    asset_type: AssetType
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    raw_volume_unit: RawVolumeUnit
    price_currency: str
    raw_share_unit: Decimal
    price_type: PriceType
    adjusted_close: Decimal | None = None
    forward_adjusted_close: Decimal | None = None
    backward_adjusted_close: Decimal | None = None
    adjustment_method: str | None = None
    open_tradable: bool | None = None
    event_time: datetime | None = None
    available_time: datetime | None = None
    ingested_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProviderRawBatch:
    capability: ProviderCapability
    request: AssetPriceRequest
    rows: tuple[ProviderRawBar, ...]

    def __post_init__(self) -> None:
        expected = (
            self.capability.market,
            self.capability.asset_type,
        )
        actual = (self.request.market, self.request.asset_type)
        if expected != actual:
            raise ValueError(
                f"raw batch capability/request mismatch: expected={expected}, actual={actual}"
            )
