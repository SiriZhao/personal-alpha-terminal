from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
from personal_alpha_terminal.data.market_data.providers.akshare import (
    AKShareIndexAdapter,
    AKShareStockAdapter,
)
from personal_alpha_terminal.data.market_data.providers.stooq import StooqStockAdapter
from personal_alpha_terminal.data.market_data.providers.yahoo import (
    YahooIndexAdapter,
    YahooStockAdapter,
)


class FakeColumns(list[str]):
    nlevels = 1


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.empty = not rows
        self.columns = FakeColumns(rows[0].keys() if rows else [])

    def reset_index(self) -> "FakeFrame":
        return self

    def iterrows(self) -> list[tuple[int, dict[str, object]]]:
        return list(enumerate(self._rows))


def test_akshare_stock_adapter_normalizes_chinese_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def stock_zh_a_hist(**kwargs: Any) -> FakeFrame:
        captured.append(kwargs)
        close = {"": 10.5, "qfq": 9.5, "hfq": 11.5}[kwargs["adjust"]]
        return FakeFrame(
            [
                {
                    "日期": "2026-07-29",
                    "开盘": 10,
                    "最高": 11,
                    "最低": 9,
                    "收盘": close,
                    "成交量": 1234,
                }
            ]
        )

    monkeypatch.setattr(
        AKShareStockAdapter,
        "_load_library",
        staticmethod(lambda: SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist)),
    )

    request = AssetPriceRequest(
        symbol="000001",
        market="A",
        asset_type="stock",
        price_currency="CNY",
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )
    raw = AKShareStockAdapter().fetch_raw(request)
    bars = PriceNormalizer().normalize(raw)

    assert captured[0]["symbol"] == "000001"
    assert [item["adjust"] for item in captured] == ["", "qfq", "hfq"]
    assert bars[0].close == Decimal("10.5")
    assert bars[0].adjusted_close == Decimal("9.5")
    assert bars[0].forward_adjusted_close == Decimal("9.5")
    assert bars[0].backward_adjusted_close == Decimal("11.5")
    assert bars[0].adjustment_method == "akshare_qfq_hfq_current_snapshot"
    assert raw.rows[0].volume == Decimal("1234")
    assert raw.rows[0].raw_volume_unit == "share"
    # Official AKShare daily-history documentation defines this field in shares.
    assert bars[0].volume == 1_234


def test_yahoo_adapter_uses_exclusive_end_and_hk_symbol_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    cache_locations: list[str] = []

    def download(**kwargs: Any) -> FakeFrame:
        captured.update(kwargs)
        return FakeFrame(
            [
                {
                    "Date": "2026-07-29",
                    "Open": 500,
                    "High": 510,
                    "Low": 495,
                    "Close": 505,
                    "Adj Close": 504,
                    "Volume": 5000,
                }
            ]
        )

    monkeypatch.setattr(
        YahooStockAdapter,
        "_load_library",
        staticmethod(
            lambda: SimpleNamespace(
                download=download,
                set_tz_cache_location=cache_locations.append,
            )
        ),
    )

    request = AssetPriceRequest(
        symbol="00700",
        market="HK",
        asset_type="stock",
        price_currency="HKD",
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )
    cache_dir = tmp_path / "yfinance"
    bars = PriceNormalizer().normalize(
        YahooStockAdapter(cache_dir=cache_dir).fetch_raw(request)
    )

    assert captured["tickers"] == "0700.HK"
    assert captured["end"] == "2026-07-30"
    assert captured["auto_adjust"] is False
    assert cache_locations == [str(cache_dir)]
    assert bars[0].symbol == "00700"
    assert bars[0].adjusted_close == Decimal("504")


def test_stooq_adapter_parses_daily_csv_without_inventing_adjusted_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from personal_alpha_terminal.data.market_data.providers import stooq as module

    payload = b"Date,Open,High,Low,Close,Volume\n2026-07-29,200,205,198,203,12345\n"
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: io.BytesIO(payload))
    raw = StooqStockAdapter().fetch_raw(
        AssetPriceRequest(
            symbol="AAPL",
            market="US",
            asset_type="stock",
            price_currency="USD",
            start_date=date(2026, 7, 29),
            end_date=date(2026, 7, 29),
        )
    )
    bars = PriceNormalizer().normalize(raw)

    assert bars[0].close == Decimal("203")
    assert bars[0].volume == 12345
    assert bars[0].adjusted_close is None


def test_akshare_index_capability_is_blocked_until_volume_contract_is_verified() -> None:
    request = AssetPriceRequest(
        symbol="sh000001",
        market="A",
        asset_type="index",
        price_currency="CNY",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 29),
    )
    with pytest.raises(ProviderRequestError, match="not certified"):
        AKShareIndexAdapter().fetch_raw(request)


def test_akshare_does_not_hide_cross_source_fallback_under_one_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_calls = 0

    def failing_primary(**_kwargs: Any) -> FakeFrame:
        raise RuntimeError("primary unavailable")

    def forbidden_fallback(**_kwargs: Any) -> FakeFrame:
        nonlocal fallback_calls
        fallback_calls += 1
        return FakeFrame([])

    monkeypatch.setattr(
        AKShareStockAdapter,
        "_load_library",
        staticmethod(
            lambda: SimpleNamespace(
                stock_zh_a_hist=failing_primary,
                stock_zh_a_daily=forbidden_fallback,
            )
        ),
    )

    with pytest.raises(ProviderRequestError, match="AKShare stock request failed"):
        AKShareStockAdapter().fetch_raw(
            AssetPriceRequest(
                symbol="000001",
                market="A",
                asset_type="stock",
                price_currency="CNY",
                start_date=date(2026, 7, 29),
                end_date=date(2026, 7, 29),
            )
        )
    assert fallback_calls == 0


def test_yahoo_index_keeps_provider_index_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def download(**kwargs: Any) -> FakeFrame:
        captured.update(kwargs)
        return FakeFrame([])

    monkeypatch.setattr(
        YahooIndexAdapter,
        "_load_library",
        staticmethod(lambda: SimpleNamespace(download=download)),
    )

    YahooIndexAdapter().fetch_raw(
        AssetPriceRequest(
            symbol="^HSI",
            market="HK",
            asset_type="index",
            price_currency="HKD",
            start_date=date(2026, 7, 29),
            end_date=date(2026, 7, 29),
        )
    )

    assert captured["tickers"] == "^HSI"
