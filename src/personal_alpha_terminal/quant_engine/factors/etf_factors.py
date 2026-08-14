"""ROUND24 ETF price-only factor engine (C4-C6).

ETF factors are computed exclusively from PIT-visible price/volume data.
Company-level fundamental factors (value, quality, profitability) are never
applied to ETFs.  The engine is labeled RESEARCH_CANDIDATE: it does not
certify alpha and it never overwrites the Classical Champion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from personal_alpha_terminal.instruments.sleeves import ETF_SLEEVE_MODEL_STATUS

MODEL_VERSION = "etf-price-factors-v1"
MODEL_STATUS = ETF_SLEEVE_MODEL_STATUS

# ROUND25 PHASE 2 -- ETF_METRIC_SEMANTIC_CONTRACT.
#
# Every numeric metric emitted by this engine is declared with an explicit
# unit so no renderer may implicitly multiply by 100, label a ratio as
# "Alpha", or mix annualized and cumulative returns.  Values are NEVER
# clamped to look reasonable; NaN/Inf/extreme values are surfaced as-is and
# flagged by ``describe_metric_issue``.
METRIC_KIND_PERCENT = "PERCENT"
METRIC_KIND_DECIMAL_RETURN = "DECIMAL_RETURN"
METRIC_KIND_ZSCORE = "ZSCORE"
METRIC_KIND_RANK = "RANK"
METRIC_KIND_RAW_PRICE_RETURN = "RAW_PRICE_RETURN"
METRIC_KIND_ANNUALIZED_RETURN = "ANNUALIZED_RETURN"
METRIC_KIND_RATIO = "RATIO"

ETF_METRIC_SEMANTIC_CONTRACT: dict[str, dict[str, str]] = {
    # (close[t-21] / close[t-252]) - 1 over the lookback, expressed as a
    # decimal return (0.12 == +12%).  Cumulative, not annualized.
    "momentum_252_21": {
        "kind": METRIC_KIND_DECIMAL_RETURN,
        "definition": "cumulative price return from t-252 to t-21 (21-day skip)",
        "display_name": "12M_MOMENTUM",
        "never_label": "ALPHA",
    },
    "trend_slope_126": {
        "kind": METRIC_KIND_RAW_PRICE_RETURN,
        "definition": "OLS slope of log price over 126 days (per-day log return)",
        "display_name": "TREND_SLOPE_126D",
    },
    "trend_consistency_126": {
        "kind": METRIC_KIND_PERCENT,
        "definition": "fraction of positive 5-day forward slices over 126 days (0..1 decimal)",
        "display_name": "TREND_CONSISTENCY_126D",
    },
    "volatility_63": {
        "kind": METRIC_KIND_PERCENT,
        "definition": "annualized standard deviation of daily returns over 63 days (0.12 == 12%)",
        "display_name": "ANNUALIZED_VOL_63D",
    },
    "max_drawdown_252": {
        "kind": METRIC_KIND_DECIMAL_RETURN,
        "definition": "worst close/rolling-max - 1 over 252 days (negative decimal)",
        "display_name": "MAX_DRAWDOWN_252D",
    },
    "risk_adjusted_momentum": {
        "kind": METRIC_KIND_RATIO,
        "definition": "momentum_252_21 (decimal return) / volatility_63 (annualized vol)",
        "display_name": "MOMENTUM_TO_VOL_RATIO",
        "never_label": "ALPHA",
    },
    "relative_strength_252": {
        "kind": METRIC_KIND_RATIO,
        "definition": "fund return over 252 days divided by benchmark return over the same window",
        "display_name": "RELATIVE_STRENGTH_252D",
    },
    "correlation_63_benchmark": {
        "kind": METRIC_KIND_RATIO,
        "definition": "pearson correlation of daily returns vs benchmark over 63 days (-1..1)",
        "display_name": "CORRELATION_63D",
    },
    "average_dollar_volume_20": {
        "kind": METRIC_KIND_RAW_PRICE_RETURN,
        "definition": "mean close*volume in USD over 20 days",
        "display_name": "ADV_20D_USD",
    },
    "volume_ratio_20_63": {
        "kind": METRIC_KIND_RATIO,
        "definition": "20-day average volume divided by 63-day average volume",
        "display_name": "VOLUME_RATIO_20_63",
    },
}


def metric_kind(name: str) -> str:
    """Return the declared unit kind for a metric, or 'UNKNOWN'."""

    entry = ETF_METRIC_SEMANTIC_CONTRACT.get(name)
    return str(entry["kind"]) if entry else "UNKNOWN"


def describe_metric_issue(name: str, value: float | None) -> str | None:
    """Describe NaN/Inf/extreme values honestly; never clamp them."""

    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"{name}: NON_NUMERIC metric value ({type(value).__name__})"
    import math

    if math.isnan(value):
        return f"{name}: NaN metric value surfaced without clamping"
    if math.isinf(value):
        return f"{name}: infinite metric value surfaced without clamping"
    kind = metric_kind(name)
    if kind in {METRIC_KIND_PERCENT, METRIC_KIND_DECIMAL_RETURN} and abs(value) > 10.0:
        return (
            f"{name}: extreme {kind} value {value!r} kept as-is "
            "(no clamp per ETF_METRIC_SEMANTIC_CONTRACT)"
        )
    return None


@dataclass(frozen=True, slots=True)
class EtfFactorSnapshot:
    symbol: str
    as_of_date: date
    momentum_252_21: float | None
    trend_slope_126: float | None
    trend_consistency_126: float | None
    volatility_63: float | None
    max_drawdown_252: float | None
    risk_adjusted_momentum: float | None
    relative_strength_252: float | None
    relative_strength_benchmark: str | None
    correlation_63_benchmark: float | None
    average_dollar_volume_20: float | None
    volume_ratio_20_63: float | None
    price_observations: int
    model_version: str = MODEL_VERSION
    model_status: str = MODEL_STATUS

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date.isoformat(),
            "momentum_252_21": self.momentum_252_21,
            "trend_slope_126": self.trend_slope_126,
            "trend_consistency_126": self.trend_consistency_126,
            "volatility_63": self.volatility_63,
            "max_drawdown_252": self.max_drawdown_252,
            "risk_adjusted_momentum": self.risk_adjusted_momentum,
            "relative_strength_252": self.relative_strength_252,
            "relative_strength_benchmark": self.relative_strength_benchmark,
            "correlation_63_benchmark": self.correlation_63_benchmark,
            "average_dollar_volume_20": self.average_dollar_volume_20,
            "volume_ratio_20_63": self.volume_ratio_20_63,
            "price_observations": self.price_observations,
            "model_version": self.model_version,
            "model_status": self.model_status,
        }


def compute_etf_factors(
    prices: pd.DataFrame,
    *,
    information_cutoff: datetime,
    benchmark_symbol: str,
    benchmark_policy: dict[str, str],
    momentum_lookback: int = 252,
    momentum_skip: int = 21,
    trend_window: int = 126,
    volatility_window: int = 63,
) -> tuple[EtfFactorSnapshot, ...]:
    """Compute ETF factors from bars visible at the PIT information cutoff."""

    if information_cutoff.tzinfo is None:
        raise ValueError("ETF factor information_cutoff must be timezone-aware")
    required = {"symbol", "trade_date", "close", "volume"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"ETF factor prices miss columns: {sorted(missing)}")
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    cutoff = pd.Timestamp(information_cutoff.astimezone(UTC)).tz_localize(None)
    frame = frame.loc[
        (frame["trade_date"].dt.date <= information_cutoff.date())
        & (frame["close"] > 0)
        & (frame["trade_date"] <= cutoff)
    ]
    frame = frame.sort_values("trade_date")
    benchmark_frame = (
        frame.loc[frame["symbol"] == benchmark_symbol]
        if benchmark_symbol in set(frame["symbol"])
        else pd.DataFrame(columns=frame.columns)
    )
    minimum = max(momentum_lookback + 1, trend_window, volatility_window + 1)
    snapshots: list[EtfFactorSnapshot] = []
    for symbol, group in frame.groupby("symbol", sort=True):
        if symbol == benchmark_symbol:
            continue
        ordered = group.drop_duplicates("trade_date", keep="last").reset_index(drop=True)
        if len(ordered) < minimum or momentum_lookback <= momentum_skip:
            continue
        close = ordered["close"].astype(float)
        volume = ordered["volume"].astype(float)
        as_of_date = ordered["trade_date"].max().date()
        momentum = (
            float(close.iloc[-(momentum_skip + 1)] / close.iloc[-(momentum_lookback + 1)] - 1)
            if len(close) > momentum_lookback
            else None
        )
        trend_prices = np.log(close.tail(trend_window).to_numpy())
        x = np.arange(trend_window, dtype=float)
        slope, intercept = np.polyfit(x, trend_prices, 1)
        fitted = intercept + slope * x
        total = float(((trend_prices - trend_prices.mean()) ** 2).sum())
        residual = float(((trend_prices - fitted) ** 2).sum())
        trend_r2 = 0.0 if total <= 1e-15 else max(0.0, 1 - residual / total)
        returns = close.pct_change().tail(volatility_window)
        volatility = float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 2 else None
        rolling_max = close.tail(momentum_lookback).cummax()
        drawdowns = close.tail(momentum_lookback) / rolling_max - 1
        max_drawdown = float(drawdowns.min())
        risk_adjusted = (
            float(momentum / volatility)
            if momentum is not None and volatility is not None and volatility > 1e-9
            else None
        )
        policy = benchmark_policy.get(symbol)
        relative_strength: float | None = None
        correlation: float | None = None
        rs_benchmark: str | None = None
        if (
            policy
            and policy != "BENCHMARK_UNAVAILABLE"
            and policy != "BENCHMARK_UNAVAILABLE_SELF"
            and benchmark_symbol in set(frame["symbol"])
            and policy == benchmark_symbol
        ):
            benchmark_bars = benchmark_frame.drop_duplicates("trade_date", keep="last")
            aligned = pd.concat(
                [
                    ordered.set_index("trade_date")["close"],
                    benchmark_bars.set_index("trade_date")["close"],
                ],
                axis=1,
                join="inner",
            ).dropna()
            if len(aligned) > momentum_lookback:
                relative_strength = float(
                    aligned.iloc[-1, 0] / aligned.iloc[-(momentum_skip + 1), 0]
                    - aligned.iloc[-1, 1] / aligned.iloc[-(momentum_skip + 1), 1]
                )
            bench_returns = benchmark_bars["close"].pct_change().tail(volatility_window)
            own_returns = close.pct_change().tail(volatility_window)
            common = pd.concat([own_returns, bench_returns], axis=1, join="inner").dropna()
            if len(common) > 20:
                correlation = float(common.iloc[:, 0].corr(common.iloc[:, 1]))
            rs_benchmark = policy
        dollar_volume = (close * volume).tail(20)
        average_dollar_volume = float(dollar_volume.mean()) if len(dollar_volume) else None
        volume_20 = volume.tail(20).mean()
        volume_63 = volume.tail(63).mean()
        volume_ratio = (
            float(volume_20 / volume_63) if volume_63 and volume_63 > 0 else None
        )
        snapshots.append(
            EtfFactorSnapshot(
                symbol=symbol,
                as_of_date=as_of_date,
                momentum_252_21=momentum,
                trend_slope_126=float(np.expm1(slope * 252)),
                trend_consistency_126=trend_r2,
                volatility_63=volatility,
                max_drawdown_252=max_drawdown,
                risk_adjusted_momentum=risk_adjusted,
                relative_strength_252=relative_strength,
                relative_strength_benchmark=rs_benchmark,
                correlation_63_benchmark=correlation,
                average_dollar_volume_20=average_dollar_volume,
                volume_ratio_20_63=volume_ratio,
                price_observations=len(ordered),
            )
        )
    return tuple(snapshots)


def core_sleeve_eligible(
    snapshot: EtfFactorSnapshot,
    *,
    minimum_trend_consistency: float = 0.3,
    maximum_drawdown: float = 0.25,
) -> tuple[bool, tuple[str, ...]]:
    """LOW_TURNOVER core eligibility: long-term healthy trend only."""

    reasons: list[str] = []
    if snapshot.price_observations < 252:
        reasons.append("INSUFFICIENT_OBSERVATIONS")
    if snapshot.trend_slope_126 is None or snapshot.trend_slope_126 <= 0:
        reasons.append("TREND_NOT_POSITIVE")
    if (
        snapshot.trend_consistency_126 is None
        or snapshot.trend_consistency_126 < minimum_trend_consistency
    ):
        reasons.append("TREND_CONSISTENCY_BELOW_THRESHOLD")
    if snapshot.momentum_252_21 is None or snapshot.momentum_252_21 <= 0:
        reasons.append("MOMENTUM_NOT_POSITIVE")
    if (
        snapshot.max_drawdown_252 is None
        or snapshot.max_drawdown_252 <= -maximum_drawdown
    ):
        reasons.append("DRAWDOWN_EXCEEDS_CORE_LIMIT")
    return (not reasons, tuple(reasons))


def tactical_sleeve_eligible(
    snapshot: EtfFactorSnapshot,
) -> tuple[bool, tuple[str, ...]]:
    """Tactical eligibility: enough history and measurable risk-adjusted momentum."""

    reasons: list[str] = []
    if snapshot.price_observations < 126:
        reasons.append("INSUFFICIENT_OBSERVATIONS")
    if snapshot.risk_adjusted_momentum is None:
        reasons.append("RISK_ADJUSTED_MOMENTUM_UNAVAILABLE")
    if snapshot.average_dollar_volume_20 is None or snapshot.average_dollar_volume_20 <= 0:
        reasons.append("LIQUIDITY_UNAVAILABLE")
    return (not reasons, tuple(reasons))
