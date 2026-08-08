from __future__ import annotations

import hashlib
import io
import random
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd


class ProviderError(RuntimeError):
    """A provider failed without producing a trustworthy data frame."""


class ProviderTimeoutError(ProviderError):
    """A provider exceeded the bounded request time."""


class ProviderRateLimitError(ProviderError):
    """A provider explicitly rejected the request due to throttling."""


@dataclass(frozen=True, slots=True)
class ProviderResult:
    symbol: str
    frame: pd.DataFrame
    provider: str
    endpoint: str
    requested_at: datetime
    completed_at: datetime
    adjustment_policy: str
    content_hash: str
    exchange: str = "UNKNOWN"
    asset_type: str = "stock"
    verified_sources: tuple[str, ...] = ()
    provider_disagreement: float | None = None


class DataProvider(Protocol):
    name: str

    def fetch_daily(self, symbol: str, start: date, end: date) -> ProviderResult: ...


def normalize_ohlcv(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize raw provider output. No price adjustment is manufactured here."""

    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [str(column[0]) for column in normalized.columns]
    normalized = normalized.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adjusted_close",
            "Volume": "volume",
            "Date": "date",
        }
    )
    if "date" not in normalized:
        normalized = normalized.reset_index().rename(
            columns={normalized.index.name or "index": "date"}
        )
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(normalized.columns)
    if missing:
        raise ProviderError(f"{symbol}: provider response misses required fields {sorted(missing)}")
    normalized["date"] = pd.to_datetime(
        normalized["date"], utc=True, errors="coerce"
    ).dt.tz_convert(None)
    for column in ("open", "high", "low", "close", "volume", "adjusted_close"):
        if column in normalized:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    columns = ("date", "open", "high", "low", "close", "adjusted_close", "volume")
    normalized = normalized.loc[:, [column for column in columns if column in normalized]]
    normalized = normalized.dropna(subset=["date"]).sort_values("date")
    if normalized.empty:
        raise ProviderError(f"{symbol}: provider returned no daily OHLCV rows")
    return normalized.reset_index(drop=True)


def _retry_delay(attempt: int, base: float = 0.5) -> float:
    return float(
        min(8.0, base * (2**attempt)) + random.uniform(0.0, min(0.25, base))
    )


def _classified_error(provider: str, symbol: str, error: Exception) -> ProviderError:
    message = str(error).lower()
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return ProviderRateLimitError(f"{provider} rate limited {symbol}: {error}")
    if "timeout" in message or "timed out" in message:
        return ProviderTimeoutError(f"{provider} timed out for {symbol}: {error}")
    return ProviderError(f"{provider} failed for {symbol}: {error}")


class YahooProvider:
    name = "yahoo"

    def __init__(
        self,
        *,
        timeout_seconds: int,
        max_retries: int,
        retry_backoff_seconds: float = 0.5,
        cache_dir: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.cache_dir = cache_dir

    def fetch_daily(self, symbol: str, start: date, end: date) -> ProviderResult:
        try:
            import yfinance as yf
        except ModuleNotFoundError as error:  # pragma: no cover - dependency contract
            raise ProviderError("yfinance is not installed") from error
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            set_cache_location = getattr(yf, "set_cache_location", None) or getattr(
                yf, "set_tz_cache_location", None
            )
            if callable(set_cache_location):
                set_cache_location(str(self.cache_dir))
        requested = datetime.now(UTC)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = yf.download(
                    tickers=symbol,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    interval="1d",
                    auto_adjust=False,
                    actions=False,
                    repair=False,
                    progress=False,
                    threads=False,
                    timeout=self.timeout_seconds,
                    multi_level_index=False,
                )
                frame = normalize_ohlcv(raw, symbol)
                completed = datetime.now(UTC)
                return ProviderResult(
                    symbol=symbol,
                    frame=frame,
                    provider=self.name,
                    endpoint="yfinance.download",
                    requested_at=requested,
                    completed_at=completed,
                    adjustment_policy="raw_ohlcv_with_provider_adjusted_close_snapshot",
                    content_hash=hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest(),
                )
            except Exception as error:  # yfinance raises provider-specific exceptions
                last_error = _classified_error(self.name, symbol, error)
                if attempt < self.max_retries:
                    time.sleep(_retry_delay(attempt, self.retry_backoff_seconds))
        raise ProviderError(f"Yahoo Finance failed for {symbol}: {last_error}") from last_error


class StooqProvider:
    """Free historical fallback. It intentionally does not support index symbols."""

    name = "stooq"

    def __init__(
        self,
        *,
        timeout_seconds: int,
        max_retries: int,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        if symbol.startswith("^"):
            raise ProviderError(f"Stooq fallback does not support index symbol {symbol}")
        return f"{symbol.lower()}.us"

    def fetch_daily(self, symbol: str, start: date, end: date) -> ProviderResult:
        provider_symbol = self._stooq_symbol(symbol)
        endpoint = f"https://stooq.com/q/d/l/?s={provider_symbol}&i=d"
        requested = datetime.now(UTC)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(endpoint, timeout=self.timeout_seconds) as response:  # noqa: S310
                    raw = response.read()
                frame = pd.read_csv(io.BytesIO(raw))
                frame = normalize_ohlcv(frame, symbol)
                frame = frame.loc[(frame["date"].dt.date >= start) & (frame["date"].dt.date <= end)]
                if frame.empty:
                    raise ProviderError(f"Stooq returned no requested rows for {symbol}")
                completed = datetime.now(UTC)
                return ProviderResult(
                    symbol=symbol,
                    frame=frame.reset_index(drop=True),
                    provider=self.name,
                    endpoint=endpoint,
                    requested_at=requested,
                    completed_at=completed,
                    adjustment_policy="provider_raw_daily_ohlcv; adjustment_policy_not_certified",
                    content_hash=hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest(),
                )
            except (URLError, OSError, ValueError, ProviderError) as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(_retry_delay(attempt, self.retry_backoff_seconds))
        raise ProviderError(f"Stooq failed for {symbol}: {last_error}") from last_error


def build_provider(
    name: str,
    *,
    timeout_seconds: int,
    max_retries: int,
    retry_backoff_seconds: float = 0.5,
    cache_dir: Path | None = None,
) -> DataProvider:
    if name == "yahoo":
        return YahooProvider(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            cache_dir=cache_dir,
        )
    if name == "stooq":
        return StooqProvider(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
    if name == "polygon":
        raise ProviderError(
            "Polygon is optional and requires an explicitly configured API adapter."
        )
    raise ProviderError(f"Unsupported provider: {name}")
