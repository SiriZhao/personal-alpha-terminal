from dataclasses import dataclass
from math import isclose
from typing import Protocol

from personal_alpha_terminal.analysis.event_study.schemas import EventMatch, PriceBar


class EventRule(Protocol):
    """Point-in-time rule: a match may only use the current and prior bars."""

    def detect(self, bars: tuple[PriceBar, ...]) -> tuple[EventMatch, ...]: ...


@dataclass(frozen=True, slots=True)
class PriceReturnRule:
    threshold: float
    direction: str = "above"

    def detect(self, bars: tuple[PriceBar, ...]) -> tuple[EventMatch, ...]:
        if self.threshold < 0:
            raise ValueError("price return threshold must be nonnegative")
        if self.direction not in {"above", "below"}:
            raise ValueError("price return direction must be above or below")
        matches: list[EventMatch] = []
        for previous, current in zip(bars, bars[1:], strict=False):
            if previous.close <= 0:
                continue
            daily_return = current.close / previous.close - 1
            matched = (
                _strictly_greater(daily_return, self.threshold)
                if self.direction == "above"
                else _strictly_greater(-daily_return, self.threshold)
            )
            if matched:
                matches.append(
                    EventMatch(
                        date=current.date,
                        trigger_value=daily_return,
                        reference_value=(
                            self.threshold if self.direction == "above" else -self.threshold
                        ),
                        details={
                            "previous_close": previous.close,
                            "current_close": current.close,
                            "direction": self.direction,
                        },
                        available_time=current.available_time,
                    )
                )
        return tuple(matches)


@dataclass(frozen=True, slots=True)
class VolumeSpikeRule:
    lookback_days: int = 20
    multiplier: float = 2.0

    def detect(self, bars: tuple[PriceBar, ...]) -> tuple[EventMatch, ...]:
        if self.lookback_days < 2:
            raise ValueError("volume lookback must be at least 2")
        if self.multiplier <= 0:
            raise ValueError("volume multiplier must be positive")
        matches: list[EventMatch] = []
        for index in range(self.lookback_days, len(bars)):
            current = bars[index]
            history = bars[index - self.lookback_days : index]
            prior_volumes = [bar.volume for bar in history if bar.volume is not None]
            if current.volume is None or len(prior_volumes) != self.lookback_days:
                continue
            average_volume = sum(prior_volumes) / self.lookback_days
            if average_volume <= 0:
                continue
            ratio = current.volume / average_volume
            if _strictly_greater(ratio, self.multiplier):
                matches.append(
                    EventMatch(
                        date=current.date,
                        trigger_value=ratio,
                        reference_value=self.multiplier,
                        details={
                            "current_volume": current.volume,
                            "prior_average_volume": average_volume,
                            "lookback_days": self.lookback_days,
                        },
                        available_time=current.available_time,
                    )
                )
        return tuple(matches)


@dataclass(frozen=True, slots=True)
class NewHighRule:
    lookback_days: int = 252
    breakout_buffer: float = 0.0

    def detect(self, bars: tuple[PriceBar, ...]) -> tuple[EventMatch, ...]:
        if self.lookback_days < 2:
            raise ValueError("new-high lookback must be at least 2")
        if self.breakout_buffer < 0:
            raise ValueError("breakout buffer must be nonnegative")
        matches: list[EventMatch] = []
        for index in range(self.lookback_days, len(bars)):
            current = bars[index]
            history = bars[index - self.lookback_days : index]
            prior_high = max(bar.close for bar in history)
            threshold_price = prior_high * (1 + self.breakout_buffer)
            if _strictly_greater(current.close, threshold_price):
                matches.append(
                    EventMatch(
                        date=current.date,
                        trigger_value=current.close / prior_high - 1,
                        reference_value=prior_high,
                        details={
                            "current_close": current.close,
                            "prior_high": prior_high,
                            "lookback_days": self.lookback_days,
                            "breakout_buffer": self.breakout_buffer,
                        },
                        available_time=current.available_time,
                    )
                )
        return tuple(matches)


def build_rule(rule_type: str, parameters: dict[str, object]) -> EventRule:
    if rule_type == "price_return":
        return PriceReturnRule(
            threshold=_number(parameters, "threshold", 0.08),
            direction=str(parameters.get("direction", "above")),
        )
    if rule_type == "volume_spike":
        return VolumeSpikeRule(
            lookback_days=_integer(parameters, "lookback_days", 20),
            multiplier=_number(parameters, "multiplier", 2.0),
        )
    if rule_type == "new_high":
        return NewHighRule(
            lookback_days=_integer(parameters, "lookback_days", 252),
            breakout_buffer=_number(parameters, "breakout_buffer", 0.0),
        )
    raise ValueError(f"unsupported event rule type: {rule_type}")


def apply_cooldown(
    matches: tuple[EventMatch, ...],
    bars: tuple[PriceBar, ...],
    cooldown_days: int,
) -> tuple[EventMatch, ...]:
    if cooldown_days < 0:
        raise ValueError("event cooldown must be nonnegative")
    if cooldown_days == 0:
        return matches
    index_by_date = {bar.date: index for index, bar in enumerate(bars)}
    selected: list[EventMatch] = []
    last_candidate_index: int | None = None
    for match in matches:
        current_index = index_by_date[match.date]
        if (
            last_candidate_index is None
            or current_index - last_candidate_index > cooldown_days
        ):
            selected.append(match)
        # Advance on every raw match, including rejected matches.  This treats a
        # continuous trigger run as one event episode instead of periodically
        # accepting another observation inside the same episode.
        last_candidate_index = current_index
    return tuple(selected)


def _number(parameters: dict[str, object], key: str, default: float) -> float:
    value = parameters.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _integer(parameters: dict[str, object], key: str, default: int) -> int:
    value = parameters.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _strictly_greater(value: float, threshold: float) -> bool:
    return value > threshold and not isclose(
        value,
        threshold,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )
