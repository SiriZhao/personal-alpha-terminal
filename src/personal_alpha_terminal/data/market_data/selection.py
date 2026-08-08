from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from personal_alpha_terminal.data.market_data.policies import policy_for_market
from personal_alpha_terminal.models import Price


def preferred_source(market: str) -> str | None:
    try:
        return policy_for_market(market).primary_source
    except ValueError:
        return None


def select_consistent_price_series(
    prices: Iterable[Price],
    *,
    preferred: str | None,
) -> list[Price]:
    """Select one provider for an entire series, then deduplicate by date."""
    by_source: defaultdict[str, list[Price]] = defaultdict(list)
    for price in prices:
        source = price.source
        if not source:
            raise ValueError("price source must be present")
        by_source[source].append(price)
    if not by_source:
        return []
    if preferred is not None:
        if preferred not in by_source:
            raise ValueError(
                f"required primary price source {preferred!r} is unavailable; "
                "cross-provider fallback is forbidden"
            )
        selected_source = preferred
    else:
        selected_source = max(
            by_source,
            key=lambda source: (
                len({item.trade_date for item in by_source[source]}),
                max(item.ingested_at for item in by_source[source]),
                source,
            ),
        )
    distinct: dict[date, Price] = {}
    for item in sorted(
        by_source[selected_source],
        key=lambda value: (
            value.trade_date,
            value.ingested_at,
            value.id,
        ),
        reverse=True,
    ):
        distinct.setdefault(item.trade_date, item)
    return [distinct[item] for item in sorted(distinct)]
