"""ROUND24 volatility-managed momentum research (D8).

A/B comparison of volatility-scaled momentum versus plain momentum.
Research-only: the Classical Champion is never overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

MODEL_VERSION = "vol-managed-momentum-v1"
MODEL_STATUS = "RESEARCH_CANDIDATE"


@dataclass(frozen=True, slots=True)
class VolManagedComparison:
    as_of_date: date
    symbols: int
    plain_momentum_mean: float | None
    vol_managed_momentum_mean: float | None
    rank_correlation: float | None
    volatility_plain: float | None
    volatility_managed: float | None
    turnover_reduction_ratio: float | None
    recommendation: str
    model_version: str = MODEL_VERSION
    model_status: str = MODEL_STATUS

    def document(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "symbols": self.symbols,
            "plain_momentum_mean": self.plain_momentum_mean,
            "vol_managed_momentum_mean": self.vol_managed_momentum_mean,
            "rank_correlation": self.rank_correlation,
            "volatility_plain": self.volatility_plain,
            "volatility_managed": self.volatility_managed,
            "turnover_reduction_ratio": self.turnover_reduction_ratio,
            "recommendation": self.recommendation,
            "model_version": self.model_version,
            "model_status": self.model_status,
        }


def compare_vol_managed_momentum(
    prices: pd.DataFrame,
    *,
    as_of_date: date,
    momentum_lookback: int = 252,
    momentum_skip: int = 21,
    volatility_window: int = 63,
) -> VolManagedComparison:
    """Compare plain vs volatility-scaled momentum cross-sectionally."""

    required = {"symbol", "trade_date", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"vol-managed momentum prices miss columns: {sorted(missing)}")
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame[frame["trade_date"].dt.date <= as_of_date]
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame[frame["close"] > 0].sort_values("trade_date")
    rows: list[dict[str, float]] = []
    for symbol, group in frame.groupby("symbol", sort=True):
        ordered = group.drop_duplicates("trade_date", keep="last")
        close = ordered["close"].astype(float)
        if len(close) <= momentum_lookback or momentum_lookback <= momentum_skip:
            continue
        plain = float(close.iloc[-(momentum_skip + 1)] / close.iloc[-(momentum_lookback + 1)] - 1)
        returns = close.pct_change().tail(volatility_window)
        volatility = float(returns.std(ddof=1) * np.sqrt(252))
        managed = plain / volatility if volatility > 1e-9 else 0.0
        rows.append({"symbol": symbol, "plain": plain, "managed": managed})
    if not rows:
        return VolManagedComparison(
            as_of_date=as_of_date,
            symbols=0,
            plain_momentum_mean=None,
            vol_managed_momentum_mean=None,
            rank_correlation=None,
            volatility_plain=None,
            volatility_managed=None,
            turnover_reduction_ratio=None,
            recommendation="INSUFFICIENT_DATA",
        )
    table = pd.DataFrame(rows).set_index("symbol")
    plain_rank = table["plain"].rank()
    managed_rank = table["managed"].rank()
    rank_corr = float(plain_rank.corr(managed_rank)) if len(table) > 2 else None
    plain_mean = float(table["plain"].mean())
    managed_mean = float(table["managed"].mean())
    vol_plain = float(table["plain"].std(ddof=1)) if len(table) > 1 else None
    vol_managed = float(table["managed"].std(ddof=1)) if len(table) > 1 else None
    turnover_ratio = (
        float((vol_managed / max(vol_plain, 1e-12)) * (vol_plain / max(vol_managed, 1e-12)))
        if vol_plain and vol_managed and vol_plain > 0 and vol_managed > 0
        else None
    )
    recommendation = (
        "NEEDS_WALK_FORWARD_EVIDENCE"
        if rank_corr is not None and rank_corr > 0.9
        else "DIVERGES_FROM_PLAIN_MOMENTUM_NEEDS_EVIDENCE"
    )
    return VolManagedComparison(
        as_of_date=as_of_date,
        symbols=len(table),
        plain_momentum_mean=round(plain_mean, 6),
        vol_managed_momentum_mean=round(managed_mean, 6),
        rank_correlation=round(rank_corr, 6) if rank_corr is not None else None,
        volatility_plain=round(vol_plain, 6) if vol_plain is not None else None,
        volatility_managed=round(vol_managed, 6) if vol_managed is not None else None,
        turnover_reduction_ratio=round(turnover_ratio, 6) if turnover_ratio is not None else None,
        recommendation=recommendation,
    )
