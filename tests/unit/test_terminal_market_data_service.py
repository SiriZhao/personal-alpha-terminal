from __future__ import annotations

import hashlib
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from personal_alpha_terminal.terminal.cache import DailyPriceCache
from personal_alpha_terminal.terminal.market_data_service import MarketDataService
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar
from personal_alpha_terminal.terminal.providers import (
    ProviderError,
    ProviderResult,
    YahooProvider,
)
from personal_alpha_terminal.terminal.quality import DataQualityValidator, DataSafetyStatus


def _frame(*, close_shift: float = 0.0, duplicate: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-01", "2026-08-07")
    close = pd.Series(range(100, 100 + len(dates)), dtype=float) + close_shift
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adjusted_close": close,
            "volume": 1_000_000,
        }
    )
    return pd.concat((frame, frame.tail(1)), ignore_index=True) if duplicate else frame


class Provider:
    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        close_shift: float = 0.0,
        duplicate: bool = False,
        adjustment_policy: str = "raw_with_adjusted_close;corporate_actions_certified",
        error_message: str = "timeout",
        price_spike: bool = False,
    ) -> None:
        self.name = name
        self.fail = fail
        self.close_shift = close_shift
        self.duplicate = duplicate
        self.adjustment_policy = adjustment_policy
        self.error_message = error_message
        self.price_spike = price_spike

    def fetch_daily(self, symbol: str, start: date, end: date) -> ProviderResult:
        if self.fail:
            raise ProviderError(self.error_message)
        frame = _frame(close_shift=self.close_shift, duplicate=self.duplicate)
        if self.price_spike:
            frame.loc[frame.index[-1], ["open", "high", "low", "close", "adjusted_close"]] = (
                500.0,
                505.0,
                495.0,
                500.0,
                500.0,
            )
        return ProviderResult(
            symbol,
            frame,
            self.name,
            f"fixture://{self.name}",
            datetime.now(UTC),
            datetime.now(UTC),
            self.adjustment_policy,
            hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest(),
            "XNAS",
            "stock",
        )


def _service(tmp_path: Path, *providers: Provider) -> MarketDataService:
    return MarketDataService(
        providers=providers,
        cache=DailyPriceCache(tmp_path / "cache"),
        calendar=MarketSessionCalendar(),
    )


def test_yahoo_end_date_is_exclusive_without_date_type_crash(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    cache_locations: list[str] = []

    def download(**kwargs: object) -> pd.DataFrame:
        captured.update(kwargs)
        return _frame().set_index("date")

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(
            download=download,
            set_tz_cache_location=cache_locations.append,
        ),
    )
    cache_dir = tmp_path / "provider-cache"
    provider = YahooProvider(
        timeout_seconds=1, max_retries=0, cache_dir=cache_dir
    )

    result = provider.fetch_daily("AAPL", date(2026, 7, 1), date(2026, 8, 7))

    assert captured["end"] == "2026-08-08"
    assert cache_locations == [str(cache_dir)]
    assert not result.frame.empty


def test_primary_failure_uses_secondary_and_records_degraded(tmp_path: Path) -> None:
    result = _service(tmp_path, Provider("primary", fail=True), Provider("secondary")).sync(
        ("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True
    )
    assert result.data["AAPL"][1].provider == "secondary"
    assert result.provider_health[0].status == "UNAVAILABLE"
    assert result.provider_health[1].status == "READY"
    assert result.degraded_symbols == ("AAPL",)


def test_all_provider_failure_uses_cache_but_never_hides_error(tmp_path: Path) -> None:
    service = _service(tmp_path, Provider("primary"), Provider("secondary"))
    service.sync(("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True)
    offline = _service(tmp_path, Provider("primary", fail=True), Provider("secondary", fail=True))
    result = offline.sync(
        ("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True
    )
    assert "AAPL" in result.data
    assert result.used_cache == ("AAPL",)
    assert "using cached data" in result.errors["AAPL"]


def test_all_provider_failure_without_cache_fails_closed(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        Provider("primary", fail=True),
        Provider("secondary", fail=True),
    ).sync(("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True)
    report = DataQualityValidator().validate(
        result.data, required_symbols=("AAPL",), as_of=date(2026, 8, 7)
    )
    assert report.safety_status is DataSafetyStatus.BLOCKED
    assert not report.permits_executable_actions


def test_provider_disagreement_blocks_symbol(tmp_path: Path) -> None:
    result = _service(tmp_path, Provider("primary"), Provider("secondary", close_shift=20)).sync(
        ("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True
    )
    report = DataQualityValidator(maximum_provider_difference=0.02).validate(
        result.data,
        required_symbols=("AAPL",),
        as_of=date(2026, 8, 7),
        provider_disagreements=result.provider_disagreements,
    )
    assert report.safety_status is DataSafetyStatus.BLOCKED
    assert any("provider_disagreement" in issue for issue in report.symbols[0].issues)


def test_malformed_provider_is_rejected_before_cache(tmp_path: Path) -> None:
    result = _service(tmp_path, Provider("bad", duplicate=True)).sync(
        ("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True
    )
    assert "AAPL" not in result.data
    assert "duplicate" in result.errors["AAPL"]


def test_canonical_schema_keeps_nullable_quotes(tmp_path: Path) -> None:
    result = _service(tmp_path, Provider("primary"), Provider("secondary")).sync(
        ("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True
    )
    frame = result.data["AAPL"][0]
    assert {
        "symbol",
        "exchange",
        "asset_type",
        "timestamp_utc",
        "timestamp_et",
        "calendar_date",
        "trade_date",
        "session",
        "market_structure_version",
        "adj_close",
        "bid",
        "ask",
        "mid",
        "spread",
        "source",
        "retrieved_at",
        "data_age",
        "is_adjusted",
        "quality_score",
    } <= set(frame)
    assert frame["bid"].isna().all()


def test_uncertified_corporate_action_lineage_blocks_executable_data(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        Provider("primary", adjustment_policy="provider adjusted snapshot only"),
        Provider("secondary", adjustment_policy="provider adjusted snapshot only"),
    ).sync(("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True)
    report = DataQualityValidator().validate(
        result.data,
        required_symbols=("AAPL",),
        as_of=date(2026, 8, 7),
        provider_disagreements=result.provider_disagreements,
    )
    assert report.safety_status is DataSafetyStatus.BLOCKED
    assert "corporate_action_lineage_not_certified" in report.symbols[0].issues


def test_rate_limit_is_visible_in_provider_health(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        Provider("primary", fail=True, error_message="HTTP 429 rate limit"),
        Provider("secondary"),
    ).sync(("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True)
    assert result.provider_health[0].rate_limited
    assert result.provider_health[0].status == "UNAVAILABLE"
    assert result.data["AAPL"][1].provider == "secondary"


def test_stale_cache_and_unexplained_price_spike_fail_closed(tmp_path: Path) -> None:
    result = _service(
        tmp_path,
        Provider("primary", price_spike=True),
        Provider("secondary", price_spike=True),
    ).sync(("AAPL",), start=date(2026, 6, 1), end=date(2026, 8, 7), refresh=True)
    report = DataQualityValidator(max_stale_trading_days=3).validate(
        result.data,
        required_symbols=("AAPL",),
        as_of=date(2026, 8, 20),
        provider_disagreements=result.provider_disagreements,
    )
    assert report.safety_status is DataSafetyStatus.BLOCKED
    assert any("anomalies=" in issue for issue in report.symbols[0].issues)
    assert any("stale_trading_days=" in issue for issue in report.symbols[0].issues)
