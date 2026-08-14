"""ROUND24 deterministic instrument classification and ETF catalog tests (C1-C3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from personal_alpha_terminal.instruments import (
    BENCHMARK_UNAVAILABLE,
    BenchmarkRole,
    CatalogError,
    Sleeve,
    TradabilityTier,
    classify_instrument,
    default_catalog,
    load_catalog,
    sleeve_label,
)
from personal_alpha_terminal.instruments.master import InstrumentType


def test_catalog_loads_deterministically() -> None:
    catalog = default_catalog()
    assert len(catalog.entries) >= 60
    by_symbol = catalog.by_symbol()
    assert by_symbol["VOO"]["category"] == "US_BROAD_MARKET"
    assert by_symbol["QQQ"]["benchmark_role"] == "BOTH"
    assert by_symbol["TQQQ"]["leveraged"] is True
    assert by_symbol["SQQQ"]["inverse"] is True
    assert by_symbol["UVXY"]["category"] == "VOLATILITY_ETP"


def test_catalog_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "missing.json")


def test_voo_classified_tradable_with_benchmark_role() -> None:
    classification = classify_instrument(
        "VOO",
        directory_record=None,
        catalog_entry=default_catalog().by_symbol()["VOO"],
    )
    assert classification.instrument_type is InstrumentType.ETF
    assert classification.is_etf
    assert not classification.is_leveraged
    assert not classification.is_inverse
    assert classification.tradability_tier is TradabilityTier.STANDARD_TRADABLE
    assert classification.benchmark_role is BenchmarkRole.BOTH
    assert classification.sleeve is Sleeve.ETF_CORE
    assert classification.benchmark_policy == "BENCHMARK_UNAVAILABLE_SELF"


def test_leveraged_blocked_by_complex_policy() -> None:
    classification = classify_instrument(
        "TQQQ",
        directory_record=None,
        catalog_entry=default_catalog().by_symbol()["TQQQ"],
    )
    assert (
        classification.tradability_tier
        is TradabilityTier.BLOCKED_BY_COMPLEX_PRODUCT_POLICY
    )
    assert classification.sleeve is Sleeve.NONE


def test_uncatalogued_etf_is_research_only() -> None:
    from datetime import UTC, date, datetime

    from personal_alpha_terminal.data.us_market.broad_universe import (
        CurrentSecurityMasterRecord,
        CurrentSecurityType,
    )

    record = CurrentSecurityMasterRecord(
        security_id="NASDAQTRADER:XNAS:ABCD",
        symbol="ABCD",
        company_name="Unknown ETF",
        security_type=CurrentSecurityType.ETF,
        exchange="XNAS",
        currency="USD",
        country="US",
        listing_date=None,
        delisting_date=None,
        active_from=date(2020, 1, 1),
        active_to=None,
        is_common_stock=False,
        is_etf=True,
        is_adr=False,
        is_reit=False,
        is_preferred=False,
        is_warrant=False,
        is_unit=False,
        is_right=False,
        is_otc=False,
        sector=None,
        industry=None,
        test_issue=False,
        financial_status="N",
        source="test",
        effective_date=date(2026, 8, 13),
        available_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    classification = classify_instrument(
        "ABCD",
        directory_record=record,
        catalog_entry=None,
    )
    assert classification.tradability_tier is TradabilityTier.RESEARCH_ONLY
    assert classification.classification_reason == "UNCLASSIFIED_ETF"


def test_sleeve_labels() -> None:
    assert sleeve_label(Sleeve.ETF_CORE) == "ETF_CORE_SLEEVE"
    assert sleeve_label(Sleeve.ETF_TACTICAL) == "ETF_TACTICAL_SLEEVE"
    assert sleeve_label(Sleeve.EQUITY_ALPHA) == "EQUITY_ALPHA_SLEEVE"


def test_benchmark_unavailable_constant() -> None:
    assert BENCHMARK_UNAVAILABLE == "BENCHMARK_UNAVAILABLE"
