from datetime import date, timedelta

import pytest

from personal_alpha_terminal.analysis.event_study.rules import (
    NewHighRule,
    PriceReturnRule,
    VolumeSpikeRule,
    apply_cooldown,
)
from personal_alpha_terminal.analysis.event_study.schemas import PriceBar


def bars(
    closes: list[float],
    volumes: list[int | None] | None = None,
) -> tuple[PriceBar, ...]:
    start = date(2026, 1, 1)
    resolved_volumes = volumes or [100] * len(closes)
    return tuple(
        PriceBar(
            date=start + timedelta(days=index),
            close=close,
            volume=resolved_volumes[index],
        )
        for index, close in enumerate(closes)
    )


def test_price_return_rule_uses_only_previous_close() -> None:
    matches = PriceReturnRule(threshold=0.08).detect(bars([100, 108, 109, 118]))

    assert len(matches) == 1
    assert matches[0].date == date(2026, 1, 4)
    assert matches[0].trigger_value == pytest.approx(118 / 109 - 1)


def test_volume_spike_excludes_event_day_from_average() -> None:
    matches = VolumeSpikeRule(lookback_days=3, multiplier=2).detect(
        bars([10, 10, 10, 10], [100, 100, 100, 250])
    )

    assert len(matches) == 1
    assert matches[0].trigger_value == pytest.approx(2.5)
    assert matches[0].details["prior_average_volume"] == 100


def test_new_high_compares_with_prior_window_only() -> None:
    matches = NewHighRule(lookback_days=3).detect(bars([10, 11, 12, 12.1, 11]))

    assert len(matches) == 1
    assert matches[0].reference_value == 12
    assert matches[0].date == date(2026, 1, 4)


def test_cooldown_uses_trigger_trading_observations() -> None:
    history = bars([100, 110, 121, 133.1, 146.41])
    matches = PriceReturnRule(threshold=0.08).detect(history)

    selected = apply_cooldown(matches, history, cooldown_days=2)

    assert [match.date for match in selected] == [date(2026, 1, 2)]


def test_cooldown_clusters_a_continuous_trigger_episode() -> None:
    history = bars([100, 110, 121, 133.1, 146.41, 146.41, 161.051])
    matches = PriceReturnRule(threshold=0.08).detect(history)

    selected = apply_cooldown(matches, history, cooldown_days=1)

    assert [match.date for match in selected] == [
        date(2026, 1, 2),
        date(2026, 1, 7),
    ]
