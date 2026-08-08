from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class SessionFeatures:
    previous_regular_close: float | None
    night_return: float | None
    premarket_return: float | None
    overnight_return: float | None
    overnight_range: float | None
    overnight_gap: float | None
    overnight_volume_ratio: float | None
    overnight_realized_volatility: float | None
    overnight_vwap_deviation: float | None
    overnight_relative_strength: float | None
    reliability_score: float
    status: str
    unavailable: tuple[str, ...]


class SessionFeatureEngine:
    """Optional 23H information features; missing sessions are never fabricated."""

    def calculate(
        self,
        bars: pd.DataFrame,
        *,
        provider_confidence: float,
        market_confirmation: float | None = None,
        sector_confirmation: float | None = None,
    ) -> SessionFeatures:
        required = {"session", "open", "high", "low", "close", "volume"}
        if bars.empty or not required.issubset(bars.columns):
            return self._unavailable("session bars unavailable")
        grouped = {str(name): frame for name, frame in bars.groupby("session")}
        regular = grouped.get("REGULAR")
        night = grouped.get("NIGHT")
        premarket = grouped.get("PREMARKET")
        previous_close = self._last(regular, "close")
        night_return = self._return(night)
        premarket_return = self._return(premarket)
        final_extended = self._last(premarket, "close") or self._last(night, "close")
        overnight_return = None
        if previous_close is not None and previous_close > 0 and final_extended is not None:
            overnight_return = final_extended / previous_close - 1
        premarket_open = self._first(premarket, "open")
        overnight_gap = night_return
        if previous_close is not None and previous_close > 0 and premarket_open is not None:
            overnight_gap = premarket_open / previous_close - 1
        extended = pd.concat(
            [frame for frame in (night, premarket) if frame is not None],
            ignore_index=True,
        ) if night is not None or premarket is not None else pd.DataFrame()
        overnight_range = None
        realized = None
        vwap_deviation = None
        if not extended.empty:
            low = float(extended["low"].min())
            high = float(extended["high"].max())
            overnight_range = high / low - 1 if low > 0 else None
            returns = extended["close"].astype(float).pct_change().dropna()
            realized = float(returns.std(ddof=1)) if len(returns) >= 2 else None
            volume = extended["volume"].astype(float)
            total_volume = float(volume.sum())
            if total_volume > 0:
                vwap = float((extended["close"].astype(float) * volume).sum() / total_volume)
                last = float(extended["close"].iloc[-1])
                vwap_deviation = last / vwap - 1 if vwap else None
        regular_volume = (
            float(regular["volume"].mean())
            if regular is not None and not regular.empty
            else 0.0
        )
        extended_volume = float(extended["volume"].sum()) if not extended.empty else 0.0
        volume_ratio = extended_volume / regular_volume if regular_volume > 0 else None
        confirmations = [
            value
            for value in (market_confirmation, sector_confirmation)
            if value is not None
        ]
        relative_strength = (
            (overnight_return - sum(confirmations) / len(confirmations))
            if overnight_return is not None and confirmations
            else None
        )
        unavailable = tuple(
            name
            for name, value in {
                "night_return": night_return,
                "premarket_return": premarket_return,
                "overnight_return": overnight_return,
                "overnight_volume_ratio": volume_ratio,
            }.items()
            if value is None
        )
        liquidity_score = min(100.0, max(0.0, (volume_ratio or 0.0) * 200.0))
        coverage_score = 100.0 * (4 - len(unavailable)) / 4
        confirmation_score = 100.0 if confirmations else 50.0
        reliability = round(
            0.40 * max(0.0, min(100.0, provider_confidence))
            + 0.30 * coverage_score
            + 0.20 * liquidity_score
            + 0.10 * confirmation_score,
            2,
        )
        status = "READY" if reliability >= 75 and not unavailable else "DEGRADED"
        return SessionFeatures(
            previous_close,
            night_return,
            premarket_return,
            overnight_return,
            overnight_range,
            overnight_gap,
            volume_ratio,
            realized,
            vwap_deviation,
            relative_strength,
            reliability,
            status,
            unavailable,
        )

    @staticmethod
    def _first(frame: pd.DataFrame | None, column: str) -> float | None:
        return float(frame[column].iloc[0]) if frame is not None and not frame.empty else None

    @staticmethod
    def _last(frame: pd.DataFrame | None, column: str) -> float | None:
        return float(frame[column].iloc[-1]) if frame is not None and not frame.empty else None

    def _return(self, frame: pd.DataFrame | None) -> float | None:
        first = self._first(frame, "open")
        last = self._last(frame, "close")
        return last / first - 1 if first and last else None

    @staticmethod
    def _unavailable(reason: str) -> SessionFeatures:
        return SessionFeatures(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0.0,
            "UNAVAILABLE",
            (reason,),
        )
