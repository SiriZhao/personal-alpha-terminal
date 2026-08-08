from dataclasses import replace

import pytest

from personal_alpha_terminal.data.market_data_quality.classification import (
    validate_symbol_mapping,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    ListingAgeBucket,
    MarketSegment,
    SizeBucket,
    UniverseCandidate,
)


def a_share() -> UniverseCandidate:
    return UniverseCandidate(
        stock_id=1,
        symbol="688001",
        market="A",
        exchange="SSE",
        segment=MarketSegment.STAR,
        asset_type="stock",
        size_bucket=SizeBucket.LARGE,
        listing_age_bucket=ListingAgeBucket.ESTABLISHED,
        list_date=None,
        delist_date=None,
    )


def test_a_share_mapping_requires_explicit_compatible_exchange() -> None:
    validate_symbol_mapping(a_share())

    with pytest.raises(ValueError, match="inconsistent"):
        validate_symbol_mapping(
            replace(
                a_share(),
                exchange="SZSE",
            )
        )


def test_hong_kong_mapping_rejects_yahoo_suffix_in_stock_master() -> None:
    candidate = UniverseCandidate(
        stock_id=2,
        symbol="0700.HK",
        market="HK",
        exchange="HKEX",
        segment=MarketSegment.HK_MAIN,
        asset_type="stock",
        size_bucket=SizeBucket.LARGE,
        listing_age_bucket=ListingAgeBucket.ESTABLISHED,
        list_date=None,
        delist_date=None,
    )

    with pytest.raises(ValueError, match="numeric"):
        validate_symbol_mapping(candidate)
