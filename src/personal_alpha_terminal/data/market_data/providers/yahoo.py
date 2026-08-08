import importlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import ModuleType

from personal_alpha_terminal.data.market_data.capabilities import capability_for
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    AssetType,
    ProviderCapability,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.exceptions import (
    ProviderDependencyError,
    ProviderRequestError,
    UnsupportedMarketError,
)
from personal_alpha_terminal.data.market_data.providers.common import frame_to_raw_bars

YAHOO_COLUMNS = {
    "date": ("Date", "Datetime", "index"),
    "open": ("Open", "open"),
    "high": ("High", "high"),
    "low": ("Low", "low"),
    "close": ("Close", "close"),
    "volume": ("Volume", "volume"),
    "adjusted_close": ("Adj Close", "Adjusted Close", "adj_close"),
}


class _YahooAssetAdapter:
    source = "yahoo_finance"
    asset_type: AssetType

    def __init__(
        self,
        *,
        timeout_seconds: int = 30,
        cache_dir: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache_dir = cache_dir
        self.capabilities = tuple(
            capability_for(self.source, market, self.asset_type) for market in ("HK", "US")
        )
        self.provider_id = f"yfinance.download.{self.asset_type}"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        capability = self._capability(request)
        if not capability.supported:
            raise ProviderRequestError(
                "provider capability is not certified: "
                f"{self.source}/{request.market}/{self.asset_type}"
            )
        provider_symbol = (
            self._index_symbol(request.symbol)
            if self.asset_type == "index"
            else self._provider_symbol(request.symbol, request.market)
        )
        library = self._load_library()
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            set_cache_location = getattr(
                library, "set_cache_location", None
            ) or getattr(library, "set_tz_cache_location", None)
            if callable(set_cache_location):
                set_cache_location(str(self.cache_dir))
        try:
            frame = library.download(
                tickers=provider_symbol,
                start=request.start_date.isoformat(),
                end=(request.end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                repair=False,
                progress=False,
                threads=False,
                timeout=self.timeout_seconds,
                multi_level_index=False,
            )
        except Exception as exc:
            raise ProviderRequestError(
                f"Yahoo Finance request failed for {request.symbol}: {exc}"
            ) from exc
        rows = frame_to_raw_bars(
            frame,
            request=request,
            capability=capability,
            columns=YAHOO_COLUMNS,
        )
        rows = [
            replace(
                item,
                adjustment_method=(
                    "yahoo_provider_total_return_current_snapshot"
                    if item.adjusted_close is not None
                    else None
                ),
            )
            for item in rows
        ]
        return ProviderRawBatch(capability, request, tuple(rows))

    def _capability(self, request: AssetPriceRequest) -> ProviderCapability:
        if request.market not in {"HK", "US"} or request.asset_type != self.asset_type:
            raise UnsupportedMarketError(
                f"{type(self).__name__} does not handle {request.market}/{request.asset_type}"
            )
        return capability_for(self.source, request.market, self.asset_type)

    @staticmethod
    def _load_library() -> ModuleType:
        try:
            return importlib.import_module("yfinance")
        except ModuleNotFoundError as exc:
            raise ProviderDependencyError(
                "yfinance is not installed. Install the market-data extra."
            ) from exc

    @staticmethod
    def _provider_symbol(symbol: str, market: str) -> str:
        normalized = symbol.strip().upper()
        if market == "US":
            return normalized
        if normalized.endswith(".HK"):
            raise ProviderRequestError(
                "Hong Kong stock-master symbols must not include provider suffixes"
            )
        if not normalized.isdigit():
            raise ProviderRequestError(
                f"Invalid Hong Kong symbol {symbol!r}; expected a numeric code."
            )
        return f"{str(int(normalized)).zfill(4)}.HK"

    @staticmethod
    def _index_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ProviderRequestError("Yahoo Finance index symbol cannot be empty.")
        return normalized


class YahooStockAdapter(_YahooAssetAdapter):
    asset_type: AssetType = "stock"


class YahooETFAdapter(_YahooAssetAdapter):
    asset_type: AssetType = "etf"


class YahooIndexAdapter(_YahooAssetAdapter):
    asset_type: AssetType = "index"


class YahooBondAdapter(_YahooAssetAdapter):
    asset_type: AssetType = "bond"
