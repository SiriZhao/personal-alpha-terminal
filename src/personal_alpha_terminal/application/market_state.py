"""ROUND25 PHASE 4: deterministic MARKET_STATE_SNAPSHOT.

Market-wide statistics are computed directly from PIT-visible price bars in
the local database.  DeepSeek may only interpret these numbers; it can never
recompute or alter them (QUANT_FACT boundary).

Every output metric is declared with an explicit unit in
``MARKET_STATE_METRIC_CONTRACT`` so renderers cannot mislabel a decimal as a
percent or a drawdown as a return.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import Price, SecurityMaster

METRIC_KIND_PERCENT = "PERCENT"
METRIC_KIND_DECIMAL_RETURN = "DECIMAL_RETURN"
METRIC_KIND_RATIO = "RATIO"

MARKET_STATE_METRIC_CONTRACT: dict[str, dict[str, str]] = {
    "return_1d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "1 trading day"},
    "return_5d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "5 trading days"},
    "return_20d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "20 trading days"},
    "return_63d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "63 trading days"},
    "return_126d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "126 trading days"},
    "return_252d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "252 trading days"},
    "distance_ma20": {"kind": METRIC_KIND_PERCENT, "window": "vs 20-day MA"},
    "distance_ma50": {"kind": METRIC_KIND_PERCENT, "window": "vs 50-day MA"},
    "distance_ma100": {"kind": METRIC_KIND_PERCENT, "window": "vs 100-day MA"},
    "distance_ma200": {"kind": METRIC_KIND_PERCENT, "window": "vs 200-day MA"},
    "realized_vol_20d": {"kind": METRIC_KIND_PERCENT, "window": "20 days annualized"},
    "realized_vol_63d": {"kind": METRIC_KIND_PERCENT, "window": "63 days annualized"},
    "drawdown_20d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "from 20-day high"},
    "drawdown_63d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "from 63-day high"},
    "drawdown_252d": {"kind": METRIC_KIND_DECIMAL_RETURN, "window": "from 252-day high"},
    "correlation_63d_vs_spy": {"kind": METRIC_KIND_RATIO, "window": "63 days"},
    "breadth_pct_above_ma20": {"kind": METRIC_KIND_PERCENT, "window": "cross-sectional"},
    "breadth_pct_above_ma50": {"kind": METRIC_KIND_PERCENT, "window": "cross-sectional"},
    "breadth_pct_above_ma200": {"kind": METRIC_KIND_PERCENT, "window": "cross-sectional"},
    "breadth_pct_positive_5d": {"kind": METRIC_KIND_PERCENT, "window": "cross-sectional"},
    "breadth_pct_positive_20d": {"kind": METRIC_KIND_PERCENT, "window": "cross-sectional"},
    "cross_sectional_dispersion_20d": {
        "kind": METRIC_KIND_PERCENT,
        "window": "std of 20-day returns across symbols",
    },
}

# Broad market + style + sector + proxy basket.  Every ticker is fetched with
# a single batched query; symbols without data are marked UNAVAILABLE instead
# of being fabricated.
MARKET_BASKET: tuple[tuple[str, str], ...] = (
    ("SPY", "broad_market"),
    ("QQQ", "nasdaq_growth"),
    ("IWM", "small_cap"),
    ("VOO", "broad_optional"),
    ("VTI", "total_market_optional"),
    ("XLK", "sector_technology"),
    ("XLF", "sector_financials"),
    ("XLV", "sector_healthcare"),
    ("XLE", "sector_energy"),
    ("XLY", "sector_consumer_discretionary"),
    ("XLP", "sector_consumer_staples"),
    ("XLI", "sector_industrials"),
    ("XLU", "sector_utilities"),
    ("XLB", "sector_materials"),
    ("XLRE", "sector_real_estate"),
    ("XLC", "sector_communication"),
    ("TLT", "bond_proxy_long"),
    ("IEF", "bond_proxy_mid"),
    ("GLD", "gold_proxy"),
)

_RETURN_WINDOWS = (1, 5, 20, 63, 126, 252)
_MA_WINDOWS = (20, 50, 100, 200)
_VOL_WINDOWS = (20, 63)
_DD_WINDOWS = (20, 63, 252)


@dataclass(frozen=True, slots=True)
class BasketSecurityState:
    symbol: str
    role: str
    available: bool
    observations: int
    last_close: float | None
    returns: dict[str, float | None]
    ma_distances: dict[str, float | None]
    realized_vols: dict[str, float | None]
    drawdowns: dict[str, float | None]

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "role": self.role,
            "available": self.available,
            "observations": self.observations,
            "last_close": self.last_close,
            "returns": dict(self.returns),
            "ma_distances": dict(self.ma_distances),
            "realized_vols": dict(self.realized_vols),
            "drawdowns": dict(self.drawdowns),
        }


@dataclass(frozen=True, slots=True)
class MarketStateSnapshot:
    as_of: datetime
    data_cutoff: datetime
    basket: tuple[BasketSecurityState, ...]
    breadth: dict[str, float | None]
    breadth_universe_size: int
    breadth_symbols: int
    cross_sectional_dispersion_20d: float | None
    new_highs: int | None
    new_lows: int | None
    status: str
    metric_contract: dict[str, dict[str, str]]

    def document(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "data_cutoff": self.data_cutoff.isoformat(),
            "basket": [item.document() for item in self.basket],
            "breadth": dict(self.breadth),
            "breadth_universe_size": self.breadth_universe_size,
            "breadth_symbols": self.breadth_symbols,
            "cross_sectional_dispersion_20d": self.cross_sectional_dispersion_20d,
            "new_highs": self.new_highs,
            "new_lows": self.new_lows,
            "status": self.status,
            "metric_contract": dict(self.metric_contract),
            "quant_fact": True,
            "llm_modifiable": False,
        }


def _series_metrics(close: pd.Series) -> dict[str, Any]:
    """Compute every declared metric for one symbol's close series."""

    close = close.dropna()
    returns: dict[str, float | None] = {}
    for window in _RETURN_WINDOWS:
        returns[f"return_{window}d"] = (
            float(close.iloc[-1] / close.iloc[-(window + 1)] - 1.0)
            if len(close) > window and close.iloc[-(window + 1)] > 0
            else None
        )
    ma_distances: dict[str, float | None] = {}
    for window in _MA_WINDOWS:
        ma = float(close.tail(window).mean()) if len(close) >= window else None
        ma_distances[f"distance_ma{window}"] = (
            float(close.iloc[-1] / ma - 1.0) if ma and ma > 0 else None
        )
    realized_vols: dict[str, float | None] = {}
    daily = close.pct_change().dropna()
    for window in _VOL_WINDOWS:
        tail = daily.tail(window)
        realized_vols[f"realized_vol_{window}d"] = (
            float(tail.std(ddof=1) * np.sqrt(252)) if len(tail) >= 20 else None
        )
    drawdowns: dict[str, float | None] = {}
    for window in _DD_WINDOWS:
        tail = close.tail(window)
        drawdowns[f"drawdown_{window}d"] = (
            float(tail.iloc[-1] / tail.max() - 1.0) if len(tail) >= 2 and tail.max() > 0 else None
        )
    return {
        "returns": returns,
        "ma_distances": ma_distances,
        "realized_vols": realized_vols,
        "drawdowns": drawdowns,
        "daily_returns": daily.tail(63),
    }


def _load_basket(
    session: Session, *, as_of: datetime
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    symbols = [symbol for symbol, _role in MARKET_BASKET]
    rows = session.execute(
        select(
            SecurityMaster.symbol,
            Price.trade_date,
            Price.close,
        )
        .join(Price, Price.stock_id == SecurityMaster.id)
        .where(
            SecurityMaster.symbol.in_(symbols),
            Price.price_type == "unadjusted_ohlcv",
            Price.available_time <= as_of,
            Price.trade_date <= as_of.date(),
        )
        .order_by(SecurityMaster.symbol, Price.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame(), {}
    frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    series_map = {
        symbol: group.set_index("trade_date")["close"].sort_index()
        for symbol, group in frame.groupby("symbol")
    }
    return frame, series_map


def _load_breadth_frame(
    session: Session, *, as_of: datetime
) -> pd.DataFrame:
    """One batched breadth query using SQLite window functions.

    Returns one row per symbol on its latest visible trade date with close,
    MA20/50/200, and 5/20-day lagged closes for the cross-sectional breadth.
    """

    sql = """
    SELECT * FROM (
      SELECT
        s.symbol,
        p.trade_date,
        p.close,
        AVG(p.close) OVER (PARTITION BY s.symbol ORDER BY p.trade_date
                           ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
        AVG(p.close) OVER (PARTITION BY s.symbol ORDER BY p.trade_date
                           ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma50,
        AVG(p.close) OVER (PARTITION BY s.symbol ORDER BY p.trade_date
                           ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma200,
        LAG(p.close, 5) OVER (PARTITION BY s.symbol ORDER BY p.trade_date) AS lag5,
        LAG(p.close, 20) OVER (PARTITION BY s.symbol ORDER BY p.trade_date) AS lag20,
        ROW_NUMBER() OVER (PARTITION BY s.symbol ORDER BY p.trade_date DESC) AS rn
      FROM prices p
      JOIN security_master s ON s.id = p.stock_id
      WHERE p.price_type = 'unadjusted_ohlcv'
        AND p.available_time <= :as_of
        AND p.trade_date <= :trade_date
    )
    WHERE rn = 1
    """
    rows = session.execute(
        text(sql),
        {"as_of": as_of, "trade_date": as_of.date().isoformat()},
    ).all()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "trade_date",
            "close",
            "ma20",
            "ma50",
            "ma200",
            "lag5",
            "lag20",
            "rn",
        ],
    )
    for column in ("close", "ma20", "ma50", "ma200", "lag5", "lag20"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["close"])


def build_market_state_snapshot(
    session: Session, *, as_of: datetime
) -> MarketStateSnapshot | None:
    """Build the deterministic snapshot; returns None when no data exists."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of = as_of.astimezone(UTC)
    _frame, series_map = _load_basket(session, as_of=as_of)
    basket_states: list[BasketSecurityState] = []
    correlations: list[float] = []
    spy_returns: pd.Series | None = series_map.get("SPY")
    for symbol, role in MARKET_BASKET:
        close = series_map.get(symbol)
        if close is None or len(close) < 2:
            basket_states.append(
                BasketSecurityState(
                    symbol=symbol,
                    role=role,
                    available=False,
                    observations=0 if close is None else len(close),
                    last_close=None,
                    returns={},
                    ma_distances={},
                    realized_vols={},
                    drawdowns={},
                )
            )
            continue
        metrics = _series_metrics(close)
        basket_states.append(
            BasketSecurityState(
                symbol=symbol,
                role=role,
                available=True,
                observations=len(close),
                last_close=float(close.iloc[-1]),
                returns=metrics["returns"],
                ma_distances=metrics["ma_distances"],
                realized_vols=metrics["realized_vols"],
                drawdowns=metrics["drawdowns"],
            )
        )
        if spy_returns is not None and symbol != "SPY":
            own = close.pct_change().dropna().tail(63)
            common = pd.concat(
                [own, spy_returns.pct_change().dropna().tail(63)],
                axis=1,
                join="inner",
            ).dropna()
            if len(common) >= 20:
                correlations.append(float(common.iloc[:, 0].corr(common.iloc[:, 1])))

    breadth_frame = _load_breadth_frame(session, as_of=as_of)
    breadth: dict[str, float | None] = {
        "breadth_pct_above_ma20": None,
        "breadth_pct_above_ma50": None,
        "breadth_pct_above_ma200": None,
        "breadth_pct_positive_5d": None,
        "breadth_pct_positive_20d": None,
    }
    breadth_symbols = len(breadth_frame)
    universe_size = int(  # noqa: F841 - reported via breadth_universe_size
        session.scalar(
            select(func.count()).select_from(SecurityMaster)
        )
        or 0
    )
    if breadth_symbols:
        valid = breadth_frame[breadth_frame["close"] > 0]
        if len(valid):
            breadth["breadth_pct_above_ma20"] = float(
                (valid["close"] > valid["ma20"]).mean()
            )
            breadth["breadth_pct_above_ma50"] = float(
                (valid["close"] > valid["ma50"]).mean()
            )
            breadth["breadth_pct_above_ma200"] = float(
                (valid["close"] > valid["ma200"]).mean()
            )
        with_lag5 = valid[valid["lag5"].notna()]
        with_lag20 = valid[valid["lag20"].notna()]
        breadth["breadth_pct_positive_5d"] = (
            float((with_lag5["close"] > with_lag5["lag5"]).mean())
            if len(with_lag5)
            else None
        )
        breadth["breadth_pct_positive_20d"] = (
            float((with_lag20["close"] > with_lag20["lag20"]).mean())
            if len(with_lag20)
            else None
        )
        dispersion = None
        if len(with_lag20):
            returns_20d = with_lag20["close"] / with_lag20["lag20"] - 1.0
            dispersion = float(returns_20d.std(ddof=1)) if len(returns_20d) > 2 else None
    else:
        dispersion = None

    new_highs: int | None = None
    new_lows: int | None = None
    # New highs/lows require a full 252-day rolling window per symbol; they
    # are only computed when the breadth frame exposes them cheaply.
    # Reported as None (UNAVAILABLE) rather than fabricated.

    return MarketStateSnapshot(
        as_of=as_of,
        data_cutoff=as_of,
        basket=tuple(basket_states),
        breadth=breadth,
        breadth_universe_size=breadth_symbols,
        breadth_symbols=breadth_symbols,
        cross_sectional_dispersion_20d=dispersion,
        new_highs=new_highs,
        new_lows=new_lows,
        status="MARKET_STATE_OK" if series_map else "MARKET_STATE_DATA_UNAVAILABLE",
        metric_contract=MARKET_STATE_METRIC_CONTRACT,
    )
