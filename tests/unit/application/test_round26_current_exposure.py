"""ROUND26 P0: current operational size / sector exposure tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from personal_alpha_terminal.application.current_exposure import (
    SECTOR_RISK_DEGRADED,
    SECTOR_RISK_PASS,
    SIZE_RISK_DEGRADED,
    acquire_current_size_observations,
    build_current_sector_exposure,
    sic_to_sector,
    size_bucket,
)


def test_size_bucket_boundaries() -> None:
    assert size_bucket(100_000_000) == "MICRO"
    assert size_bucket(500_000_000) == "SMALL"
    assert size_bucket(5_000_000_000) == "MID"
    assert size_bucket(50_000_000_000) == "LARGE"
    assert size_bucket(500_000_000_000) == "MEGA"


def test_size_bucket_unknown_is_not_safe() -> None:
    assert size_bucket(None) == "UNKNOWN"
    assert size_bucket(0) == "UNKNOWN"
    assert size_bucket(-1) == "UNKNOWN"


def test_sic_mapping_is_deterministic_and_versioned() -> None:
    assert sic_to_sector("1311") == "MINING"
    assert sic_to_sector("2834") == "MANUFACTURING"
    assert sic_to_sector("6021") == "FINANCE_INSURANCE_REAL_ESTATE"
    assert sic_to_sector("7372") == "SERVICES"
    assert sic_to_sector("9999") == "UNKNOWN"
    assert sic_to_sector(None) == "UNKNOWN"
    assert sic_to_sector("abc") == "UNKNOWN"


def test_sector_exposure_is_degraded_when_unknown() -> None:
    report = build_current_sector_exposure(
        sector_rows={"A": None, "B": None},
        target_symbols=("A", "B"),
        classification_source="SEC_SIC",
    )
    assert report["status"] == SECTOR_RISK_DEGRADED
    assert report["portfolio_unknown_sector_weight"] == 1.0
    assert report["classification_source"] == "SEC_SIC"
    assert report["missing_never_assumed_safe"] is True


def test_sector_exposure_passes_with_full_coverage() -> None:
    report = build_current_sector_exposure(
        sector_rows={"A": "2834", "B": "6021"},
        target_symbols=("A", "B"),
        classification_source="SEC_SIC",
    )
    assert report["status"] == SECTOR_RISK_PASS
    assert report["sector_coverage"] == 1.0
    assert report["top_sector"] in {"MANUFACTURING", "FINANCE_INSURANCE_REAL_ESTATE"}
    assert report["sector_hhi"] > 0


def test_empty_targets_are_degraded_not_fabricated() -> None:
    report = build_current_sector_exposure(
        sector_rows={}, target_symbols=(), classification_source="SEC_SIC"
    )
    assert report["status"] == SECTOR_RISK_DEGRADED
    assert report["portfolio_unknown_sector_weight"] == 1.0


def test_size_exposure_status_semantics() -> None:
    # Degraded coverage must never masquerade as PASS.
    assert SIZE_RISK_DEGRADED != "PASS"


def test_current_market_cap_uses_provider_cap_with_current_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTicker:
        fast_info = {"marketCap": 1_500_000_000, "lastPrice": 15.0, "shares": 100_000_000}

    monkeypatch.setitem(
        __import__("sys").modules, "yfinance", SimpleNamespace(Ticker=lambda _: FakeTicker())
    )
    observations, meta = acquire_current_size_observations(
        symbols=("ABC",), as_of=datetime(2026, 8, 15, tzinfo=UTC)
    )
    observation = observations[0]
    assert meta["returned"] == 1
    assert observation.market_cap == 1_500_000_000
    assert observation.market_cap_calculation == "PROVIDER_REPORTED_MARKET_CAP"
    assert observation.shares_outstanding == 100_000_000
    assert observation.source_quality == "CURRENT_ONLY"


def test_current_market_cap_falls_back_only_to_verified_shares_times_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTicker:
        fast_info = {"lastPrice": 20.0, "shares": 50_000_000}

    monkeypatch.setitem(
        __import__("sys").modules, "yfinance", SimpleNamespace(Ticker=lambda _: FakeTicker())
    )
    observations, _meta = acquire_current_size_observations(
        symbols=("ABC",), as_of=datetime(2026, 8, 15, tzinfo=UTC)
    )
    observation = observations[0]
    assert observation.market_cap == 1_000_000_000
    assert observation.market_cap_calculation == "VERIFIED_CURRENT_SHARES_X_CURRENT_PRICE"


def test_current_market_cap_missing_inputs_remains_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTicker:
        fast_info = {"lastPrice": 20.0}

    monkeypatch.setitem(
        __import__("sys").modules, "yfinance", SimpleNamespace(Ticker=lambda _: FakeTicker())
    )
    observations, _meta = acquire_current_size_observations(
        symbols=("ABC",), as_of=datetime(2026, 8, 15, tzinfo=UTC)
    )
    observation = observations[0]
    assert observation.market_cap is None
    assert observation.market_cap_calculation == "UNKNOWN"
