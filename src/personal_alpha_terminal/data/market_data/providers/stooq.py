from __future__ import annotations

import io
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from personal_alpha_terminal.data.market_data.capabilities import capability_for
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    AssetType,
    ProviderCapability,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.exceptions import (
    ProviderRequestError,
    UnsupportedMarketError,
)
from personal_alpha_terminal.data.market_data.providers.common import frame_to_raw_bars

STOOQ_COLUMNS = {
    "date": ("Date", "date", "index"),
    "open": ("Open", "open"),
    "high": ("High", "high"),
    "low": ("Low", "low"),
    "close": ("Close", "close"),
    "volume": ("Volume", "volume"),
    "adjusted_close": (),
}


class _StooqAssetAdapter:
    source = "stooq"
    asset_type: AssetType

    def __init__(self, *, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.capabilities: tuple[ProviderCapability, ...] = (
            capability_for(self.source, "US", self.asset_type),
        )
        self.provider_id = f"stooq.daily_csv.{self.asset_type}"

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        capability = self._capability(request)
        parameters = urlencode(
            {
                "s": f"{request.symbol.strip().lower()}.us",
                "d1": request.start_date.strftime("%Y%m%d"),
                "d2": request.end_date.strftime("%Y%m%d"),
                "i": "d",
            }
        )
        endpoint = f"https://stooq.com/q/d/l/?{parameters}"
        request_object = Request(endpoint, headers={"User-Agent": "PersonalAlphaTerminal/1"})
        try:
            with urlopen(request_object, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = response.read()
            frame = pd.read_csv(io.BytesIO(payload))
            rows = frame_to_raw_bars(
                frame,
                request=request,
                capability=capability,
                columns=STOOQ_COLUMNS,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ProviderRequestError(
                f"Stooq request failed for {request.symbol}: {exc}"
            ) from exc
        if not rows:
            raise ProviderRequestError(f"Stooq returned no rows for {request.symbol}")
        return ProviderRawBatch(capability, request, tuple(rows))

    def _capability(self, request: AssetPriceRequest) -> ProviderCapability:
        if request.market != "US" or request.asset_type != self.asset_type:
            raise UnsupportedMarketError(
                f"{type(self).__name__} does not handle "
                f"{request.market}/{request.asset_type}"
            )
        return capability_for(self.source, request.market, self.asset_type)


class StooqStockAdapter(_StooqAssetAdapter):
    asset_type: AssetType = "stock"


class StooqETFAdapter(_StooqAssetAdapter):
    asset_type: AssetType = "etf"
