from datetime import UTC, date, datetime

import pytest

from personal_alpha_terminal.data.us_market import (
    PITCorporateAction,
    PITRawBar,
    PointInTimeTotalReturnBuilder,
)


def _bar(day: int, close: float) -> PITRawBar:
    return PITRawBar(
        "US-FIGI-1",
        date(2026, 1, day),
        close,
        f"bar-{day}",
        datetime(2026, 1, day, 22, tzinfo=UTC),
    )


def _action(action_type: str, *, ratio: float | None = None, cash: float | None = None):
    return PITCorporateAction(
        action_id=f"action-{action_type}",
        revision_id="r1",
        permanent_security_id="US-FIGI-1",
        action_type=action_type,
        effective_date=date(2026, 1, 3),
        announcement_at=datetime(2026, 1, 1, 13, tzinfo=UTC),
        available_at=datetime(2026, 1, 1, 13, tzinfo=UTC),
        source_id="action-ledger-1",
        split_ratio=ratio,
        cash_amount=cash,
        currency="USD" if cash is not None else None,
    )


def test_builder_uses_raw_prices_and_actions_without_split_jump() -> None:
    series = PointInTimeTotalReturnBuilder().build(
        bars=(_bar(2, 100), _bar(3, 50), _bar(4, 51)),
        actions=(_action("split", ratio=2),),
        as_of_time=datetime(2026, 1, 4, 23, tzinfo=UTC),
    )
    assert series.points[1].period_return == pytest.approx(0)
    assert series.points[2].period_return == pytest.approx(0.02)
    assert series.adjustment_method == "point_in_time_total_return"
    assert len(series.version_id) == 64


def test_builder_includes_cash_dividend_and_is_reproducible() -> None:
    kwargs = {
        "bars": (_bar(2, 100), _bar(3, 99)),
        "actions": (_action("cash_dividend", cash=2),),
        "as_of_time": datetime(2026, 1, 3, 23, tzinfo=UTC),
    }
    first = PointInTimeTotalReturnBuilder().build(**kwargs)
    second = PointInTimeTotalReturnBuilder().build(**kwargs)
    assert first.points[-1].period_return == pytest.approx(0.01)
    assert first.version_id == second.version_id


def test_builder_rejects_future_bar_and_unvalued_spin_off() -> None:
    with pytest.raises(ValueError, match="unavailable"):
        PointInTimeTotalReturnBuilder().build(
            bars=(_bar(2, 100), _bar(3, 101)),
            actions=(),
            as_of_time=datetime(2026, 1, 2, 23, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="explicit valuation"):
        PointInTimeTotalReturnBuilder().build(
            bars=(_bar(2, 100), _bar(3, 101)),
            actions=(_action("spin_off"),),
            as_of_time=datetime(2026, 1, 3, 23, tzinfo=UTC),
        )
