import importlib
from dataclasses import replace
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

AKSHARE_COLUMNS = {
    "date": ("日期", "date"),
    "open": ("开盘", "open"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "close": ("收盘", "close"),
    "volume": ("成交量", "volume"),
}


class _AKShareAdapter:
    source = "akshare"
    asset_type: AssetType

    def __init__(self) -> None:
        self.capabilities: tuple[ProviderCapability, ...] = (
            capability_for(self.source, "A", self.asset_type),
        )
        self.provider_id = f"akshare.{self.capabilities[0].endpoint}"

    @property
    def capability(self) -> ProviderCapability:
        return self.capabilities[0]

    def _validate_request(self, request: AssetPriceRequest) -> None:
        if request.market != "A" or request.asset_type != self.asset_type:
            raise UnsupportedMarketError(
                f"{type(self).__name__} handles only A/{self.asset_type}"
            )
        if not self.capability.supported:
            raise ProviderRequestError(
                "provider capability is not certified: "
                f"{self.source}/A/{self.asset_type}/{self.capability.endpoint}"
            )

    @staticmethod
    def _load_library() -> ModuleType:
        try:
            return importlib.import_module("akshare")
        except ModuleNotFoundError as exc:
            raise ProviderDependencyError(
                "AKShare is not installed. Install the market-data extra."
            ) from exc

    @staticmethod
    def _six_digit_symbol(symbol: str) -> str:
        normalized = symbol.strip().lower()
        for suffix in (".sh", ".sz", ".bj"):
            normalized = normalized.removesuffix(suffix)
        if normalized.startswith(("sh", "sz", "bj")):
            normalized = normalized[2:]
        if len(normalized) != 6 or not normalized.isdigit():
            raise ProviderRequestError(
                f"Invalid A-market symbol {symbol!r}; expected a six-digit code."
            )
        return normalized


class AKShareStockAdapter(_AKShareAdapter):
    asset_type: AssetType = "stock"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        self._validate_request(request)
        symbol = self._six_digit_symbol(request.symbol)
        library = self._load_library()
        arguments = {
            "symbol": symbol,
            "period": "daily",
            "start_date": request.start_date.strftime("%Y%m%d"),
            "end_date": request.end_date.strftime("%Y%m%d"),
        }
        try:
            raw_frame = library.stock_zh_a_hist(adjust="", **arguments)
            forward_frame = library.stock_zh_a_hist(adjust="qfq", **arguments)
            backward_frame = library.stock_zh_a_hist(adjust="hfq", **arguments)
        except Exception as exc:
            raise ProviderRequestError(
                f"AKShare stock request failed for {request.symbol}: {exc}"
            ) from exc
        raw = frame_to_raw_bars(
            raw_frame,
            request=request,
            capability=self.capability,
            columns=AKSHARE_COLUMNS,
        )
        forward = frame_to_raw_bars(
            forward_frame,
            request=request,
            capability=self.capability,
            columns=AKSHARE_COLUMNS,
        )
        backward = frame_to_raw_bars(
            backward_frame,
            request=request,
            capability=self.capability,
            columns=AKSHARE_COLUMNS,
        )
        forward_by_date = {item.date: item.close for item in forward}
        backward_by_date = {item.date: item.close for item in backward}
        raw_dates = {item.date for item in raw}
        if raw and (set(forward_by_date) != raw_dates or set(backward_by_date) != raw_dates):
            raise ProviderRequestError(
                f"AKShare raw/qfq/hfq date mismatch for {request.symbol}; "
                "refusing partial adjustment."
            )
        rows = tuple(
            replace(
                item,
                adjusted_close=forward_by_date[item.date],
                forward_adjusted_close=forward_by_date[item.date],
                backward_adjusted_close=backward_by_date[item.date],
                adjustment_method="akshare_qfq_hfq_current_snapshot",
            )
            for item in raw
        )
        return ProviderRawBatch(self.capability, request, rows)


class AKShareETFAdapter(_AKShareAdapter):
    asset_type: AssetType = "etf"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        self._validate_request(request)
        raise AssertionError("unreachable until the ETF volume contract is certified")


class AKShareIndexAdapter(_AKShareAdapter):
    asset_type: AssetType = "index"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        self._validate_request(request)
        raise AssertionError("unreachable until the index volume contract is certified")


class AKShareBondAdapter(_AKShareAdapter):
    asset_type: AssetType = "bond"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        self._validate_request(request)
        raise AssertionError("unreachable until the bond endpoint is certified")
