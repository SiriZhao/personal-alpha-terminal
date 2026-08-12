"""ROUND 10: canonical normalization failure-injection tests."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from personal_alpha_terminal.data.market_data.capabilities import capability_for
from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.providers.canonical import (
    normalize_provider_frame,
)
from personal_alpha_terminal.data.market_data.providers.yahoo import YAHOO_COLUMNS

START = date(2026, 7, 1)
END = date(2026, 7, 3)


def _request(symbol: str = "AFRM") -> AssetPriceRequest:
    return AssetPriceRequest(
        symbol=symbol,
        market="US",
        asset_type="stock",
        start_date=START,
        end_date=END,
        price_currency="USD",
    )


def _capability():
    return capability_for("yahoo_finance", "US", "stock")


def _single_level_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Adj Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
        },
        index=pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
    )


def _multiindex_price_ticker() -> pd.DataFrame:
    """Columns ordered (Price, Ticker) as yfinance group_by='column'."""
    frame = _single_level_frame()
    symbols = ["AFRM", "SPY"]
    # Correctly aligned per-ticker columns: each (Price, Ticker) pair carries the
    # right values, mirroring yfinance's real batch output.
    parts = []
    for ticker in symbols:
        for price in frame.columns:
            parts.append((price, ticker))
    columns = pd.MultiIndex.from_tuples(parts, names=["Price", "Ticker"])
    data = pd.concat([frame] * 2, axis=1)
    data.columns = columns
    return data


def _multiindex_ticker_price() -> pd.DataFrame:
    """Columns ordered (Ticker, Price) as yfinance concat default."""
    frame = _single_level_frame()
    symbols = ["AFRM", "SPY"]
    parts = []
    for ticker in symbols:
        for price in frame.columns:
            parts.append((ticker, price))
    columns = pd.MultiIndex.from_tuples(parts, names=["Ticker", "Price"])
    data = pd.concat([frame] * 2, axis=1)
    data.columns = columns
    return data


def test_single_level_frame_normalizes_with_real_close() -> None:
    bars = normalize_provider_frame(
        _single_level_frame(),
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert len(bars) == 3
    assert all(b.close is not None and str(b.close) != "NaN" for b in bars)
    assert bars[0].symbol == "AFRM"
    assert bars[-1].close == 102.5


def test_multiindex_price_ticker_normalizes_per_symbol() -> None:
    bars = normalize_provider_frame(
        _multiindex_price_ticker(),
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    afrm = [b for b in bars if b.symbol == "AFRM"]
    spy = [b for b in bars if b.symbol == "SPY"]
    assert len(afrm) == 3 and len(spy) == 3
    assert afrm[-1].close == 102.5
    assert spy[-1].close == 102.5


def test_multiindex_ticker_price_order_also_works() -> None:
    bars = normalize_provider_frame(
        _multiindex_ticker_price(),
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    afrm = [b for b in bars if b.symbol == "AFRM"]
    assert len(afrm) == 3
    assert afrm[0].close == 100.5


def test_batch_frame_never_produces_nan_close() -> None:
    bars = normalize_provider_frame(
        _multiindex_price_ticker(),
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert all(b.close is not None and str(b.close) != "NaN" for b in bars)


def test_missing_close_raises_instead_of_silent_nan() -> None:
    frame = _single_level_frame().drop(columns=["Close"])
    with pytest.raises(ProviderRequestError, match="missing columns"):
        normalize_provider_frame(
            frame,
            request=_request(),
            capability=_capability(),
            columns=YAHOO_COLUMNS,
        )


def test_nan_close_raises_data_quality_instead_of_silent_nan() -> None:
    frame = _single_level_frame()
    frame.loc[frame.index[1], "Close"] = float("nan")
    with pytest.raises(ProviderRequestError, match="non-finite Close"):
        normalize_provider_frame(
            frame,
            request=_request(),
            capability=_capability(),
            columns=YAHOO_COLUMNS,
        )


def test_empty_frame_returns_no_bars() -> None:
    bars = normalize_provider_frame(
        pd.DataFrame(),
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert bars == []


def test_lowercase_columns_are_supported() -> None:
    frame = _single_level_frame()
    frame.columns = [str(c).lower() for c in frame.columns]
    bars = normalize_provider_frame(
        frame,
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert len(bars) == 3
    assert bars[0].close == 100.5


def test_missing_adj_close_is_optional() -> None:
    frame = _single_level_frame().drop(columns=["Adj Close"])
    bars = normalize_provider_frame(
        frame,
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert len(bars) == 3
    assert all(b.adjusted_close is None for b in bars)


def test_timezone_aware_index_is_normalized() -> None:
    frame = _single_level_frame()
    frame.index = pd.to_datetime(
        ["2026-07-01", "2026-07-02", "2026-07-03"]
    ).tz_localize("America/New_York")
    bars = normalize_provider_frame(
        frame,
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    assert len(bars) == 3


def test_duplicate_rows_are_preserved_for_downstream_dedup() -> None:
    frame = pd.concat([_single_level_frame(), _single_level_frame()])
    bars = normalize_provider_frame(
        frame,
        request=_request(),
        capability=_capability(),
        columns=YAHOO_COLUMNS,
    )
    # Both copies remain; the quality checker is responsible for dedup.
    assert len(bars) == 6
