from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from personal_alpha_terminal.data.market_data.selection import (
    select_consistent_price_series,
)
from personal_alpha_terminal.models import Price


def price(identifier: int, day: int, source: str, close: str) -> Price:
    value = Decimal(close)
    return Price(
        id=identifier,
        stock_id=1,
        trade_date=date(2026, 1, day),
        open=value,
        high=value,
        low=value,
        close=value,
        adjusted_close=value,
        volume=1,
        source=source,
        ingested_at=datetime(2026, 1, day, tzinfo=UTC),
    )


def test_price_series_never_mixes_sources_across_dates() -> None:
    rows = [
        price(1, 2, "primary", "10"),
        price(2, 3, "primary", "11"),
        price(3, 3, "secondary", "99"),
        price(4, 4, "secondary", "100"),
    ]

    selected = select_consistent_price_series(rows, preferred="primary")

    assert [item.source for item in selected] == ["primary", "primary"]
    assert [item.trade_date.day for item in selected] == [2, 3]


def test_price_selection_rejects_cross_provider_fallback() -> None:
    rows = [
        price(1, 2, "short", "10"),
        price(2, 2, "complete", "10"),
        price(3, 3, "complete", "11"),
    ]

    with pytest.raises(ValueError, match="fallback is forbidden"):
        select_consistent_price_series(rows, preferred="missing")
