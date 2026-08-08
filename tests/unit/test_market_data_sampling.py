from datetime import date

from personal_alpha_terminal.data.market_data_quality.sampling import (
    DEFAULT_SAMPLING_PLAN,
    REAL_MARKET_CERTIFICATION_PLAN,
    select_stratified_sample,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    ListingAgeBucket,
    SizeBucket,
    UniverseCandidate,
)


def candidates_for_default_plan() -> list[UniverseCandidate]:
    candidates: list[UniverseCandidate] = []
    stock_id = 1
    for segment, quota in DEFAULT_SAMPLING_PLAN.segment_quotas.items():
        market = (
            "A"
            if segment.value.startswith(("sse", "szse", "chinext", "star", "a_"))
            else "US"
            if segment.value.startswith(("nyse", "nasdaq", "us_"))
            else "HK"
        )
        for index in range(quota + 2):
            candidates.append(
                UniverseCandidate(
                    stock_id=stock_id,
                    symbol=f"S{stock_id:04d}",
                    market=market,
                    exchange=segment.value,
                    segment=segment,
                    asset_type="etf" if segment.value.endswith("etf") else "stock",
                    size_bucket=(
                        SizeBucket.LARGE if index % 2 == 0 else SizeBucket.MID_SMALL
                    ),
                    listing_age_bucket=(
                        ListingAgeBucket.NEW
                        if index == 0
                        else ListingAgeBucket.ESTABLISHED
                    ),
                    list_date=date(2025, 1, 1),
                    delist_date=date(2026, 1, 1) if index == 1 else None,
                )
            )
            stock_id += 1
    return candidates


def test_default_sampler_is_reproducible_and_covers_required_profiles() -> None:
    candidates = candidates_for_default_plan()

    first = select_stratified_sample(candidates, seed=7)
    second = select_stratified_sample(candidates, seed=7)

    assert first.passed
    assert len(first.selected) >= 100
    assert [item.stock_id for item in first.selected] == [
        item.stock_id for item in second.selected
    ]
    assert sum(item.size_bucket == SizeBucket.LARGE for item in first.selected) >= 10
    assert (
        sum(item.size_bucket == SizeBucket.MID_SMALL for item in first.selected)
        >= 10
    )
    assert (
        sum(
            item.listing_age_bucket == ListingAgeBucket.NEW
            for item in first.selected
        )
        >= 5
    )
    assert sum(item.delist_date is not None for item in first.selected) >= 5
    assert {item.segment for item in first.selected} == set(
        DEFAULT_SAMPLING_PLAN.segment_quotas
    )


def test_sampler_reports_shortages_instead_of_fabricating_rows() -> None:
    selection = select_stratified_sample(candidates_for_default_plan()[:3], seed=1)

    assert not selection.passed
    assert selection.shortages
    assert len(selection.selected) == 3


def test_real_market_certification_plan_covers_all_required_segments() -> None:
    required = {
        "sse_main",
        "szse_main",
        "chinext",
        "star",
        "a_etf",
        "hk_main",
        "hk_etf",
        "nasdaq",
        "nyse",
        "us_etf",
    }

    assert {
        segment.value for segment in REAL_MARKET_CERTIFICATION_PLAN.segment_quotas
    } == required
    assert sum(REAL_MARKET_CERTIFICATION_PLAN.segment_quotas.values()) == 104
    assert REAL_MARKET_CERTIFICATION_PLAN.minimum_delisted == 3
