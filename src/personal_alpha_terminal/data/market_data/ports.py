from typing import Protocol

from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBatch,
)


class MarketDataProvider(Protocol):
    """Raw-layer port implemented by one asset-specific provider adapter."""

    source: str
    provider_id: str
    capabilities: tuple[ProviderCapability, ...]

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch: ...
