from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt

import pandas as pd

from personal_alpha_terminal.intelligence.schemas import IntelligenceStatus, _aware


@dataclass(frozen=True, slots=True)
class CrossAssetDefinition:
    role: str
    symbol: str
    minimum_history: int = 60


@dataclass(frozen=True, slots=True)
class CrossAssetState:
    role: str
    symbol: str
    status: IntelligenceStatus
    return_20d: float | None
    realized_volatility_20d: float | None
    trend_60d: float | None
    last_observation: datetime | None
    data_cutoff: datetime
    reason: str | None


@dataclass(frozen=True, slots=True)
class CrossAssetContext:
    states: tuple[CrossAssetState, ...]
    status: IntelligenceStatus
    data_cutoff: datetime
    model_version: str = "cross-asset-context-v1"


DEFAULT_CROSS_ASSETS = (
    CrossAssetDefinition("BROAD_MARKET", "SPY"),
    CrossAssetDefinition("GROWTH", "QQQ"),
    CrossAssetDefinition("SMALL_CAP", "IWM"),
    CrossAssetDefinition("VOLATILITY", "^VIX"),
    CrossAssetDefinition("TREASURY", "TLT"),
    CrossAssetDefinition("USD", "UUP"),
    CrossAssetDefinition("GOLD", "GLD"),
    CrossAssetDefinition("OIL", "USO"),
    CrossAssetDefinition("BTC", "BTC-USD"),
)


class CrossAssetContextEngine:
    """Computes PIT context from supplied series; it never calls a provider."""

    def __init__(
        self,
        definitions: tuple[CrossAssetDefinition, ...] = DEFAULT_CROSS_ASSETS,
    ) -> None:
        if len({item.role for item in definitions}) != len(definitions):
            raise ValueError("cross-asset roles must be unique")
        self.definitions = definitions

    def evaluate(
        self,
        prices: dict[str, pd.Series],
        *,
        data_cutoff: datetime,
    ) -> CrossAssetContext:
        _aware(data_cutoff, "data_cutoff")
        states = tuple(
            self._state(definition, prices.get(definition.symbol), data_cutoff)
            for definition in self.definitions
        )
        ready = sum(item.status is IntelligenceStatus.READY for item in states)
        status = (
            IntelligenceStatus.UNAVAILABLE
            if ready == 0
            else IntelligenceStatus.READY
            if ready == len(states)
            else IntelligenceStatus.DEGRADED
        )
        return CrossAssetContext(states, status, data_cutoff)

    @staticmethod
    def _state(
        definition: CrossAssetDefinition,
        series: pd.Series | None,
        cutoff: datetime,
    ) -> CrossAssetState:
        if series is None or series.empty:
            return CrossAssetState(
                definition.role,
                definition.symbol,
                IntelligenceStatus.UNAVAILABLE,
                None,
                None,
                None,
                None,
                cutoff,
                "series unavailable",
            )
        if not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is None:
            raise ValueError("cross-asset series requires timezone-aware DatetimeIndex")
        if not series.index.is_monotonic_increasing or series.index.has_duplicates:
            raise ValueError("cross-asset timestamps must be sorted and unique")
        if series.index.max().to_pydatetime() > cutoff:
            raise ValueError("cross-asset series contains future data")
        clean = series.astype(float).dropna()
        if len(clean) < definition.minimum_history or bool((clean <= 0).any()):
            return CrossAssetState(
                definition.role,
                definition.symbol,
                IntelligenceStatus.INSUFFICIENT_SAMPLE,
                None,
                None,
                None,
                clean.index.max().to_pydatetime() if len(clean) else None,
                cutoff,
                "insufficient valid price history",
            )
        returns = clean.pct_change().dropna()
        return_20d = float(clean.iloc[-1] / clean.iloc[-21] - 1)
        volatility = float(returns.iloc[-20:].std(ddof=1) * sqrt(252))
        trend = float(clean.iloc[-1] / clean.iloc[-60:].mean() - 1)
        if any(not isfinite(value) for value in (return_20d, volatility, trend)):
            raise ValueError("cross-asset metrics are not finite")
        return CrossAssetState(
            definition.role,
            definition.symbol,
            IntelligenceStatus.READY,
            return_20d,
            volatility,
            trend,
            clean.index.max().to_pydatetime(),
            cutoff,
            None,
        )
