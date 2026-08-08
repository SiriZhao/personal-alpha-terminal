import random
from collections import Counter
from collections.abc import Callable

from personal_alpha_terminal.data.market_data_quality.schemas import (
    ListingAgeBucket,
    MarketSegment,
    SampleSelection,
    SamplingPlan,
    SizeBucket,
    UniverseCandidate,
)

DEFAULT_SAMPLING_PLAN = SamplingPlan(
    segment_quotas={
        MarketSegment.SSE_MAIN: 12,
        MarketSegment.SZSE_MAIN: 10,
        MarketSegment.CHINEXT: 8,
        MarketSegment.STAR: 8,
        MarketSegment.A_ETF: 4,
        MarketSegment.NYSE: 15,
        MarketSegment.NASDAQ: 15,
        MarketSegment.US_ETF: 4,
        MarketSegment.HK_MAIN: 20,
        MarketSegment.HK_ETF: 4,
    },
)

PRODUCTION_STOCK_CERTIFICATION_PLAN = SamplingPlan(
    segment_quotas={
        MarketSegment.SSE_MAIN: 20,
        MarketSegment.SZSE_MAIN: 15,
        MarketSegment.NYSE: 18,
        MarketSegment.NASDAQ: 17,
        MarketSegment.HK_MAIN: 30,
    },
    minimum_total=100,
    minimum_large_cap=0,
    minimum_mid_small_cap=0,
    minimum_new_listings=0,
    minimum_delisted=0,
)

REAL_MARKET_CERTIFICATION_PLAN = SamplingPlan(
    segment_quotas={
        MarketSegment.SSE_MAIN: 12,
        MarketSegment.SZSE_MAIN: 8,
        MarketSegment.CHINEXT: 10,
        MarketSegment.STAR: 10,
        MarketSegment.A_ETF: 10,
        MarketSegment.HK_MAIN: 15,
        MarketSegment.HK_ETF: 5,
        MarketSegment.NASDAQ: 12,
        MarketSegment.NYSE: 12,
        MarketSegment.US_ETF: 10,
    },
    minimum_total=104,
    minimum_large_cap=0,
    minimum_mid_small_cap=0,
    minimum_new_listings=0,
    minimum_delisted=3,
)


def select_stratified_sample(
    candidates: list[UniverseCandidate],
    *,
    plan: SamplingPlan = DEFAULT_SAMPLING_PLAN,
    seed: int = 20260731,
) -> SampleSelection:
    """Select a deterministic, auditable random sample from immutable snapshots."""

    rng = random.Random(seed)
    selected: list[UniverseCandidate] = []
    shortages: list[str] = []

    for segment, quota in plan.segment_quotas.items():
        segment_candidates = [item for item in candidates if item.segment == segment]
        segment_candidates.sort(key=lambda item: (item.symbol, item.stock_id))
        if len(segment_candidates) < quota:
            shortages.append(
                f"{segment.value}: requires {quota}, available {len(segment_candidates)}"
            )
            selected.extend(segment_candidates)
            continue
        selected.extend(rng.sample(segment_candidates, quota))

    unique = {item.stock_id: item for item in selected}
    selected = list(unique.values())
    selected_ids = set(unique)
    remaining = [item for item in candidates if item.stock_id not in selected_ids]
    remaining.sort(key=lambda item: (item.segment.value, item.symbol, item.stock_id))

    def ensure_bucket(
        *,
        label: str,
        minimum: int,
        predicate: Callable[[UniverseCandidate], bool],
    ) -> None:
        current = sum(predicate(item) for item in selected)
        eligible = [item for item in remaining if predicate(item)]
        needed = max(0, minimum - current)
        if len(eligible) < needed:
            shortages.append(f"{label}: requires {minimum}, selectable {current + len(eligible)}")
            needed = len(eligible)
        additions = rng.sample(eligible, needed) if needed else []
        selected.extend(additions)
        addition_ids = {item.stock_id for item in additions}
        remaining[:] = [item for item in remaining if item.stock_id not in addition_ids]

    ensure_bucket(
        label="large_cap",
        minimum=plan.minimum_large_cap,
        predicate=lambda item: item.size_bucket == SizeBucket.LARGE,
    )
    ensure_bucket(
        label="mid_small_cap",
        minimum=plan.minimum_mid_small_cap,
        predicate=lambda item: item.size_bucket == SizeBucket.MID_SMALL,
    )
    ensure_bucket(
        label="new_listings",
        minimum=plan.minimum_new_listings,
        predicate=lambda item: item.listing_age_bucket == ListingAgeBucket.NEW,
    )
    ensure_bucket(
        label="delisted",
        minimum=plan.minimum_delisted,
        predicate=lambda item: item.delist_date is not None,
    )

    if len(selected) < plan.minimum_total:
        needed = plan.minimum_total - len(selected)
        if len(remaining) < needed:
            shortages.append(
                f"total: requires {plan.minimum_total}, selectable {len(selected) + len(remaining)}"
            )
            needed = len(remaining)
        selected.extend(rng.sample(remaining, needed) if needed else [])

    selected.sort(key=lambda item: (item.market, item.segment.value, item.symbol))
    counts = Counter(item.stock_id for item in selected)
    if any(count > 1 for count in counts.values()):
        raise RuntimeError("Sampler produced duplicate stock ids.")
    return SampleSelection(
        selected=tuple(selected),
        seed=seed,
        plan=plan,
        shortages=tuple(sorted(set(shortages))),
    )
