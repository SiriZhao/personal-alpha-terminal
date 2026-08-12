"""Chunked multi-ticker Yahoo Finance downloads for the broad US equity universe.

The provider intentionally mirrors the certified single-ticker Yahoo adapter's
capability contract (``yahoo_finance`` / ``unadjusted_ohlcv`` / share volume) but
issues one batched request per chunk instead of thousands of serial requests.
Each returned row keeps the exact same PIT three-time lineage as the certified
adapter, so downstream certification and daily PIT checks treat the rows the
same way.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import ModuleType
from typing import Any

import pandas as pd

from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.capabilities import capability_for
from personal_alpha_terminal.data.market_data.exceptions import (
    ProviderDependencyError,
    ProviderRequestError,
)
from personal_alpha_terminal.data.market_data.schemas import PriceBar, StockPriceBar


@dataclass(frozen=True, slots=True)
class BatchDownloadReport:
    requested_symbols: tuple[str, ...]
    received_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    quarantined_symbols: tuple[str, ...]
    bar_count: int
    chunk_count: int
    bars: tuple[PriceBar, ...] = ()

    @property
    def coverage(self) -> float:
        if not self.requested_symbols:
            return 0.0
        return len(self.received_symbols) / len(self.requested_symbols)


class YahooBatchStockProvider:
    """Batch US-stock daily OHLCV downloader with chunked, thread-parallel calls."""

    source = "yahoo_finance"
    provider_id = "yahoo_finance.broad_universe_batch"
    asset_type = "stock"
    market = "US"

    def __init__(
        self,
        *,
        chunk_size: int = 400,
        timeout_seconds: int = 30,
        cache_dir: Any = None,
    ) -> None:
        if chunk_size < 1 or chunk_size > 1000:
            raise ValueError("broad universe batch chunk size must be in [1, 1000]")
        self.chunk_size = chunk_size
        self.timeout_seconds = timeout_seconds
        self.cache_dir = cache_dir
        self._capability = capability_for(self.source, self.market, self.asset_type)
        if not self._capability.supported:
            raise ProviderRequestError(
                "yahoo broad-universe capability is not certified for US stocks"
            )

    def download(
        self,
        symbols: tuple[str, ...],
        *,
        start_date: date,
        end_date: date,
        ingested_at: datetime | None = None,
    ) -> BatchDownloadReport:
        """Download OHLCV for ``symbols`` in bounded chunks.

        Failures are isolated per symbol: a delisted or invalid symbol is
        reported without aborting the batch, and the caller decides whether the
        overall coverage is sufficient.
        """

        if not symbols:
            return BatchDownloadReport((), (), (), (), 0, 0, ())
        if start_date > end_date:
            raise ValueError("broad universe download start cannot follow end")
        library = self._load_library()
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            set_cache_location = getattr(library, "set_cache_location", None) or getattr(
                library, "set_tz_cache_location", None
            )
            if callable(set_cache_location):
                set_cache_location(str(self.cache_dir))

        unique = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        original_by_provider = {
            _provider_ticker(symbol): symbol for symbol in unique
        }
        provider_symbols = tuple(original_by_provider)
        received: set[str] = set()
        failed: set[str] = set()
        bars: list[PriceBar] = []
        chunks = [
            provider_symbols[index : index + self.chunk_size]
            for index in range(0, len(provider_symbols), self.chunk_size)
        ]
        for chunk in chunks:
            try:
                chunk_failed = self._download_chunk(
                    library,
                    chunk,
                    start_date=start_date,
                    end_date=end_date,
                    bars=bars,
                    ingested_at=ingested_at,
                )
            except ProviderRequestError:
                # Isolate a provider/chunk failure. A few unavailable symbols or
                # one failed request must not discard successful chunks.
                chunk_failed = set(chunk)
            normalized_failed = {
                original_by_provider.get(item, item) for item in chunk_failed
            }
            normalized_chunk = {
                original_by_provider.get(item, item) for item in chunk
            }
            failed.update(normalized_failed)
            received.update(normalized_chunk - normalized_failed)
        normalized_bars = tuple(
            replace(bar, symbol=original_by_provider.get(bar.symbol, bar.symbol))
            for bar in bars
        )
        return BatchDownloadReport(
            requested_symbols=unique,
            received_symbols=tuple(sorted(received)),
            failed_symbols=tuple(sorted(failed)),
            quarantined_symbols=(),
            bar_count=len(normalized_bars),
            chunk_count=len(chunks),
            bars=normalized_bars,
        )

    def _download_chunk(
        self,
        library: ModuleType,
        symbols: tuple[str, ...],
        *,
        start_date: date,
        end_date: date,
        bars: list[PriceBar],
        ingested_at: datetime | None,
    ) -> set[str]:
        try:
            frame = library.download(
                tickers=list(symbols),
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                repair=False,
                progress=False,
                threads=False,
                timeout=self.timeout_seconds,
                multi_level_index=True,
            )
        except Exception as exc:
            # A fully failed chunk is quarantined as a batch; the caller can
            # retry it later.  Individual symbols within the chunk are reported
            # failed so coverage accounting stays conservative.
            raise ProviderRequestError(
                f"Yahoo broad-universe batch failed for {len(symbols)} symbols: {exc}"
            ) from exc
        if frame is None or frame.empty:
            return set(symbols)
        if not isinstance(frame.columns, pd.MultiIndex):
            # Degenerate single-ticker frame; keep the certified per-symbol path.
            symbol = symbols[0]
            return self._extract_single(
                frame,
                symbol,
                start_date=start_date,
                end_date=end_date,
                bars=bars,
                ingested_at=ingested_at,
            )
        tickers = tuple(
            str(name)
            for name in dict.fromkeys(frame.columns.get_level_values(1))
            if name not in {"Price", ""}
        )
        failed: set[str] = set()
        for symbol in symbols:
            if symbol not in tickers:
                failed.add(symbol)
                continue
            try:
                sub = frame.xs(symbol, axis=1, level=1)
                failed.update(
                    self._extract_single(
                        sub,
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                        bars=bars,
                        ingested_at=ingested_at,
                    )
                )
            except (KeyError, TypeError, ValueError):
                failed.add(symbol)
        return failed

    def _extract_single(
        self,
        frame: pd.DataFrame,
        symbol: str,
        *,
        start_date: date,
        end_date: date,
        bars: list[PriceBar],
        ingested_at: datetime | None,
    ) -> set[str]:
        if frame.empty:
            return {symbol}
        if "Close" not in frame.columns:
            return {symbol}
        cleaned = frame.dropna(subset=["Close"])
        if cleaned.empty:
            return {symbol}
        timestamps = {
            row_date: daily_bar_timestamps(row_date, self.market, ingested_time=ingested_at)
            for row_date in cleaned.index
        }
        for row_date in sorted(cleaned.index):
            trade_date = row_date.date() if hasattr(row_date, "date") else row_date
            if not start_date <= trade_date <= end_date:
                continue
            row = cleaned.loc[row_date]
            bars.append(
                StockPriceBar(
                    symbol=symbol,
                    market="US",
                    date=trade_date,
                    open=_decimal(row.get("Open")),
                    high=_decimal(row.get("High")),
                    low=_decimal(row.get("Low")),
                    close=_decimal(row.get("Close")),
                    volume=_volume(row.get("Volume")),
                    adjusted_close=_decimal_or_none(row.get("Adj Close")),
                    event_time=timestamps[row_date].event_time,
                    available_time=timestamps[row_date].available_time,
                    ingested_time=timestamps[row_date].ingested_time,
                    adjustment_method="yahoo_provider_total_return_current_snapshot",
                    price_currency="USD",
                    volume_unit="share",
                    share_unit=Decimal("1"),
                    price_type="unadjusted_ohlcv",
                    data_contract_version="market-data-v1",
                )
            )
        return set()

    @staticmethod
    def _load_library() -> ModuleType:
        try:
            return importlib.import_module("yfinance")
        except ModuleNotFoundError as exc:
            raise ProviderDependencyError(
                "yfinance is not installed. Install the market-data extra."
            ) from exc


def _decimal(value: Any) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        raise ProviderRequestError(f"missing required price field: {value!r}")
    return parsed


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number != number or number.is_nan():
        return None
    return number


def _volume(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number != number or number.is_nan() or number < 0:
        return None
    return int(number)


def _provider_ticker(symbol: str) -> str:
    """Map Nasdaq-style dotted share classes to Yahoo Finance tickers."""

    return symbol.replace(".", "-")
