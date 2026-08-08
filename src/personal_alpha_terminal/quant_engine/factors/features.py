from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


def compute_price_features(
    prices: pd.DataFrame,
    *,
    information_cutoff: datetime,
    momentum_lookback: int = 252,
    momentum_skip: int = 21,
    trend_window: int = 126,
    volatility_window: int = 63,
) -> pd.DataFrame:
    """Compute independent PIT price features from data visible at the cutoff."""

    if information_cutoff.tzinfo is None or information_cutoff.utcoffset() is None:
        raise ValueError("information_cutoff must be timezone-aware")
    required = {"permanent_security_id", "ticker", "trade_date", "available_time", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"price features miss columns: {sorted(missing)}")
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    cutoff = pd.Timestamp(information_cutoff).tz_convert("UTC")
    frame = frame.loc[
        (frame["trade_date"].dt.date <= information_cutoff.date())
        & (frame["available_time"] <= cutoff)
        & (frame["close"] > 0)
    ]
    rows: list[dict[str, object]] = []
    minimum = max(momentum_lookback + 1, trend_window, volatility_window + 1)
    for security_id, group in frame.groupby("permanent_security_id", sort=True):
        ordered = group.sort_values(["trade_date", "available_time"]).drop_duplicates(
            "trade_date", keep="last"
        )
        if len(ordered) < minimum or momentum_lookback <= momentum_skip:
            continue
        close = ordered["close"].astype(float).reset_index(drop=True)
        momentum = close.iloc[-(momentum_skip + 1)] / close.iloc[-(momentum_lookback + 1)] - 1
        trend_prices = np.log(close.tail(trend_window).to_numpy())
        x = np.arange(trend_window, dtype=float)
        slope, intercept = np.polyfit(x, trend_prices, 1)
        fitted = intercept + slope * x
        total = float(((trend_prices - trend_prices.mean()) ** 2).sum())
        residual = float(((trend_prices - fitted) ** 2).sum())
        trend_r2 = 0.0 if total <= 1e-15 else max(0.0, 1 - residual / total)
        returns = close.pct_change().tail(volatility_window)
        rows.append(
            {
                "permanent_security_id": security_id,
                "ticker": str(ordered["ticker"].iloc[-1]),
                "available_at": ordered["available_time"].max(),
                "momentum_12_1": float(momentum),
                "trend_slope": float(np.expm1(slope * 252)),
                "trend_consistency": trend_r2,
                "volatility": float(returns.std(ddof=1) * np.sqrt(252)),
                "price_observations": len(ordered),
            }
        )
    return pd.DataFrame(rows)
