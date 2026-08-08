from __future__ import annotations

from dataclasses import dataclass
from math import copysign

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class EventEffectValidation:
    horizon_effects: dict[int, float]
    peak_horizon: int | None
    approximate_half_life: float | None
    subperiod_effects: tuple[float | None, ...]
    regime_effects: dict[str, float | None]
    stable: bool
    blockers: tuple[str, ...]


def validate_event_effects(
    observations: pd.DataFrame,
    *,
    minimum_subperiod_sample: int = 30,
) -> EventEffectValidation:
    """Validate abnormal-return decay without reusing overlapping event ids."""

    required = {"event_id", "event_date", "horizon", "abnormal_return"}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"event validation misses columns: {sorted(missing)}")
    if observations.duplicated(subset=["event_id", "horizon"]).any():
        raise ValueError("event observations must be cooldown/overlap deduplicated")
    frame = observations.copy()
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="raise")
    frame["horizon"] = pd.to_numeric(frame["horizon"], errors="coerce")
    frame["abnormal_return"] = pd.to_numeric(
        frame["abnormal_return"], errors="coerce"
    )
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["horizon", "abnormal_return"]
    )
    frame = frame.loc[frame["horizon"] > 0].sort_values("event_date")
    if frame.empty:
        return EventEffectValidation({}, None, None, (), {}, False, ("no valid events",))
    effects = {
        int(horizon): float(group["abnormal_return"].mean())
        for horizon, group in frame.groupby("horizon", sort=True)
    }
    peak = max(effects, key=lambda horizon: abs(effects[horizon]))
    half_threshold = abs(effects[peak]) / 2
    later = [
        horizon
        for horizon in sorted(effects)
        if horizon > peak and abs(effects[horizon]) <= half_threshold
    ]
    half_life = float(later[0]) if later else None

    # Stability is evaluated at the peak horizon only; mixing horizons would
    # turn decay into an apparent subperiod effect.
    peak_frame = frame.loc[frame["horizon"] == peak]
    midpoint = len(peak_frame) // 2
    periods = (peak_frame.iloc[:midpoint], peak_frame.iloc[midpoint:])
    subperiods = tuple(
        float(group["abnormal_return"].mean())
        if len(group) >= minimum_subperiod_sample
        else None
        for group in periods
    )
    regimes: dict[str, float | None] = {}
    if "regime" in peak_frame:
        for regime, group in peak_frame.dropna(subset=["regime"]).groupby("regime"):
            regimes[str(regime)] = (
                float(group["abnormal_return"].mean())
                if len(group) >= minimum_subperiod_sample
                else None
            )
    blockers: list[str] = []
    valid_periods = [value for value in subperiods if value is not None]
    if len(valid_periods) != 2:
        blockers.append("insufficient event observations in chronological subperiods")
    elif copysign(1.0, valid_periods[0]) != copysign(1.0, valid_periods[1]):
        blockers.append("event effect changes sign across chronological subperiods")
    valid_regimes = [value for value in regimes.values() if value is not None]
    if valid_regimes and any(
        copysign(1.0, value) != copysign(1.0, effects[peak])
        for value in valid_regimes
    ):
        blockers.append("event effect changes sign across regimes")
    return EventEffectValidation(
        effects,
        peak,
        half_life,
        subperiods,
        regimes,
        not blockers,
        tuple(blockers),
    )
