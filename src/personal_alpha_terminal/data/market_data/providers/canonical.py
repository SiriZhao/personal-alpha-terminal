"""Canonical provider-frame normalization for ROUND 10.

The single source of truth for converting raw provider DataFrames into canonical
OHLCV bars.  It robustly handles single-level and MultiIndex columns (both
(Price, Ticker) and (Ticker, Price) orders), single and batch tickers, casing
variants, missing Adj Close, empty/partial responses, timezone-aware indexes,
duplicate rows and NaN final rows.  A real Close that exists must never be
misreported as missing, and a genuinely missing Close must fail loudly instead
of silently storing NaN.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBar,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError

ColumnCandidates = Mapping[str, tuple[str, ...]]

PRICE_LEVEL_NAMES = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "adj close",
        "adjusted close",
        "volume",
        "adj_close",
        "closeadj",
    }
)


def normalize_provider_frame(
    frame: Any,
    *,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
    provider_symbol: str | None = None,
) -> list[ProviderRawBar]:
    """Normalize any provider frame into canonical bars.

    - Single-level columns -> the classic per-symbol extraction.
    - MultiIndex columns -> extract each ticker independently so one real Close
      can never be lost to a column-structure ambiguity.
    - A row whose Close is genuinely missing is dropped only when the whole
      response for that symbol is empty; otherwise a NaN Close raises a
      DATA_QUALITY failure instead of silently persisting NaN.
    """
    if frame is None or bool(getattr(frame, "empty", False)):
        return []
    if isinstance(frame.columns, pd.MultiIndex):
        by_ticker = extract_multi_ticker(frame, request, capability, columns)
        if provider_symbol is not None:
            return by_ticker.get(provider_symbol, [])
        return [bar for _ticker in sorted(by_ticker) for bar in by_ticker[_ticker]]
    return extract_single_frame(
        frame,
        request=request,
        capability=capability,
        columns=columns,
        symbol=provider_symbol or request.symbol,
    )


def extract_multi_ticker(
    frame: pd.DataFrame,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
) -> dict[str, list[ProviderRawBar]]:
    """Extract per-ticker canonical bars from a MultiIndex-column frame.

    Supports both ``(Price, Ticker)`` (yfinance group_by='column') and
    ``(Ticker, Price)`` (yfinance concat default) orderings by inspecting the
    level contents instead of assuming a fixed level order.
    """
    levels = frame.columns.levels
    level_names = [str(name).lower() for name in frame.columns.names]
    price_level, ticker_level = _identify_levels(levels, level_names)
    ticker_values = [str(value) for value in levels[ticker_level]]
    ticker_values = [value for value in ticker_values if value and value != "Price"]
    output: dict[str, list[ProviderRawBar]] = defaultdict(list)
    for ticker in ticker_values:
        try:
            sub = frame.xs(ticker, axis=1, level=ticker_level)
        except (KeyError, TypeError, ValueError):
            continue
        sub.columns = [str(column) for column in sub.columns]
        output[ticker] = extract_single_frame(
            sub,
            request=request,
            capability=capability,
            columns=columns,
            symbol=ticker,
        )
    return dict(output)


def _identify_levels(levels: Any, level_names: list[str]) -> tuple[int, int]:
    """Return ``(price_level, ticker_level)`` for a MultiIndex column frame."""
    for index, values in enumerate(levels):
        normalized = {str(value).lower() for value in values}
        if normalized & PRICE_LEVEL_NAMES:
            return index, 1 - index if len(levels) == 2 else index
        if index == 0 and level_names and "ticker" in level_names[index].lower():
            return 1, 0
    raise ProviderRequestError(
        "Provider response uses an unsupported MultiIndex column layout"
    )


def extract_single_frame(
    frame: pd.DataFrame,
    *,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
    symbol: str,
) -> list[ProviderRawBar]:
    """Extract canonical bars from a single-level-column frame for one symbol."""
    normalized_frame = frame.reset_index()
    normalized_frame.columns = [str(column) for column in normalized_frame.columns]
    bars: list[ProviderRawBar] = []
    for _, row in normalized_frame.iterrows():
        bar_date = _to_date(_pick(row, columns["date"]))
        if not request.start_date <= bar_date <= request.end_date:
            continue
        close_value = _pick_optional(row, columns["close"])
        if close_value is None:
            if _key_present(row, columns["close"]):
                raise ProviderRequestError(
                    f"Provider response contains a non-finite Close for {symbol} on {bar_date}"
                )
            raise ProviderRequestError(
                f"Provider response is missing columns: {columns['close']}"
            )
        close = _to_optional_decimal(close_value)
        if close is None:
            # A present-but-NaN close means the response row is incomplete.
            raise ProviderRequestError(
                f"Provider response contains a non-finite Close for {symbol} on {bar_date}"
            )
        bars.append(
            ProviderRawBar(
                symbol=symbol,
                market=request.market,
                asset_type=request.asset_type,
                date=bar_date,
                open=_to_decimal(_pick(row, columns["open"])),
                high=_to_decimal(_pick(row, columns["high"])),
                low=_to_decimal(_pick(row, columns["low"])),
                close=close,
                volume=_to_optional_decimal(_pick_optional(row, columns["volume"])),
                raw_volume_unit=capability.raw_volume_unit,
                price_currency=request.price_currency,
                raw_share_unit=capability.raw_share_unit,
                price_type=capability.price_type,
                adjusted_close=_to_optional_decimal(
                    _pick_optional(row, columns.get("adjusted_close", ()))
                ),
            )
        )
    return bars


def frame_to_raw_bars(
    frame: Any,
    *,
    request: AssetPriceRequest,
    capability: ProviderCapability,
    columns: ColumnCandidates,
) -> list[ProviderRawBar]:
    """Backwards-compatible per-symbol entry point used by existing adapters."""
    return normalize_provider_frame(
        frame,
        request=request,
        capability=capability,
        columns=columns,
    )


def _key_present(row: Any, candidates: tuple[str, ...]) -> bool:
    for candidate in candidates:
        try:
            if candidate in row:
                return True
        except (KeyError, TypeError):
            continue
    return False


def _pick(row: Any, candidates: tuple[str, ...]) -> Any:
    value = _pick_optional(row, candidates)
    if value is None:
        raise ProviderRequestError(f"Provider response is missing columns: {candidates}")
    return value


def _pick_optional(row: Any, candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        try:
            if candidate in row:
                value = row[candidate]
                return None if _is_missing(value) else value
        except (KeyError, TypeError):
            continue
    return None


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        return converted.date() if isinstance(converted, datetime) else converted
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ProviderRequestError(f"Invalid provider date: {value!r}") from exc


def _to_decimal(value: Any) -> Decimal:
    if _is_missing(value):
        return Decimal("NaN")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("NaN")


def _to_optional_decimal(value: Any | None) -> Decimal | None:
    if _is_missing(value):
        return None
    parsed = _to_decimal(value)
    return parsed if parsed.is_finite() else None


def _is_missing(value: Any | None) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, pd.Series):
        # A Series under a duplicate column name is an ambiguous schema signal.
        return True
    try:
        result = value != value
        return bool(result) if isinstance(result, bool) else False
    except (TypeError, ValueError):
        return False
