"""ROUND24 Market Regime Engine V1 (D5) — RESEARCH_ONLY.

PIT-safe regime classification from already-reliable inputs:
SPY trend, QQQ trend, breadth, cross-sectional dispersion, realized
volatility, correlation and drawdown.  Output is one of
RISK_ON / NEUTRAL / RISK_OFF / STRESS.

The engine is RESEARCH_ONLY: it never feeds the production risk budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

MODEL_VERSION = "market-regime-v1"
MODEL_STATUS = "RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class RegimeInputs:
    spy_return_63: float | None
    qqq_return_63: float | None
    spy_above_ma200: bool | None
    qqq_above_ma200: bool | None
    breadth_pct_above_ma50: float | None
    cross_sectional_dispersion_21: float | None
    realized_volatility_21: float | None
    average_pairwise_correlation_21: float | None
    universe_adv_ratio_63: float | None
    spy_drawdown_252: float | None

    def document(self) -> dict[str, object]:
        return {
            "spy_return_63": self.spy_return_63,
            "qqq_return_63": self.qqq_return_63,
            "spy_above_ma200": self.spy_above_ma200,
            "qqq_above_ma200": self.qqq_above_ma200,
            "breadth_pct_above_ma50": self.breadth_pct_above_ma50,
            "cross_sectional_dispersion_21": self.cross_sectional_dispersion_21,
            "realized_volatility_21": self.realized_volatility_21,
            "average_pairwise_correlation_21": self.average_pairwise_correlation_21,
            "universe_adv_ratio_63": self.universe_adv_ratio_63,
            "spy_drawdown_252": self.spy_drawdown_252,
        }


@dataclass(frozen=True, slots=True)
class RegimeVerdict:
    regime: str
    score: float
    inputs: RegimeInputs
    as_of_date: date
    model_version: str = MODEL_VERSION
    model_status: str = MODEL_STATUS

    def document(self) -> dict[str, object]:
        return {
            "regime": self.regime,
            "score": self.score,
            "inputs": self.inputs.document(),
            "as_of_date": self.as_of_date.isoformat(),
            "model_version": self.model_version,
            "model_status": self.model_status,
        }


def classify_regime(inputs: RegimeInputs, *, as_of_date: date) -> RegimeVerdict:
    """Deterministic rule-based regime classification from PIT inputs."""

    score = 0.0
    signals: list[str] = []
    if inputs.spy_above_ma200 is True:
        score += 1.0
        signals.append("SPY>MA200")
    elif inputs.spy_above_ma200 is False:
        score -= 1.0
        signals.append("SPY<MA200")
    if inputs.spy_return_63 is not None:
        score += float(np.clip(inputs.spy_return_63 / 0.05, -1.0, 1.0))
        signals.append(f"SPY63={inputs.spy_return_63:.3f}")
    if inputs.qqq_return_63 is not None:
        score += 0.5 * float(np.clip(inputs.qqq_return_63 / 0.05, -1.0, 1.0))
    if inputs.realized_volatility_21 is not None:
        if inputs.realized_volatility_21 > 0.35:
            score -= 1.5
            signals.append("HIGH_VOL")
        elif inputs.realized_volatility_21 > 0.22:
            score -= 0.5
            signals.append("ELEVATED_VOL")
    if inputs.breadth_pct_above_ma50 is not None:
        score += float(np.clip((inputs.breadth_pct_above_ma50 - 0.5) * 2, -1.0, 1.0))
    if (
        inputs.average_pairwise_correlation_21 is not None
        and inputs.average_pairwise_correlation_21 > 0.75
    ):
        score -= 1.0
        signals.append("HIGH_CORRELATION")
    if inputs.spy_drawdown_252 is not None and inputs.spy_drawdown_252 < -0.15:
        score -= 1.0
        signals.append("DEEP_DRAWDOWN")
    if inputs.universe_adv_ratio_63 is not None and inputs.universe_adv_ratio_63 < 0.5:
        score -= 1.0
        signals.append("LIQUIDITY_COLLAPSE")
    if score >= 1.0:
        regime = "RISK_ON"
    elif score <= -1.5:
        regime = "STRESS" if score <= -2.5 else "RISK_OFF"
    else:
        regime = "NEUTRAL"
    if signals and score <= -2.5:
        regime = "STRESS"
    return RegimeVerdict(
        regime=regime,
        score=round(score, 4),
        inputs=inputs,
        as_of_date=as_of_date,
    )


def compute_regime_inputs(
    benchmark_frame: pd.DataFrame,
    universe_frame: pd.DataFrame | None,
    *,
    as_of_date: date,
) -> RegimeInputs:
    """Compute regime inputs from PIT-visible close prices.

    benchmark_frame: columns symbol(SPY/QQQ), trade_date, close.
    universe_frame: columns symbol, trade_date, close, volume for breadth.
    """

    if not {"symbol", "trade_date", "close"} <= set(benchmark_frame.columns):
        raise ValueError("benchmark_frame needs symbol, trade_date, close")
    frame = benchmark_frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame[frame["trade_date"].dt.date <= as_of_date]
    spy = frame[frame["symbol"] == "SPY"].drop_duplicates("trade_date").sort_values("trade_date")
    qqq = frame[frame["symbol"] == "QQQ"].drop_duplicates("trade_date").sort_values("trade_date")

    def _return_63(series: pd.Series) -> float | None:
        close = series["close"].astype(float)
        if len(close) <= 63:
            return None
        return float(close.iloc[-1] / close.iloc[-64] - 1)

    def _above_ma200(series: pd.Series) -> bool | None:
        close = series["close"].astype(float)
        if len(close) < 200:
            return None
        return bool(close.iloc[-1] > close.tail(200).mean())

    def _vol_21(series: pd.Series) -> float | None:
        returns = series["close"].astype(float).pct_change().tail(21)
        if len(returns) < 5:
            return None
        return float(returns.std(ddof=1) * np.sqrt(252))

    def _drawdown_252(series: pd.Series) -> float | None:
        close = series["close"].astype(float).tail(252)
        if close.empty:
            return None
        return float(close.iloc[-1] / close.max() - 1)

    breadth: float | None = None
    dispersion: float | None = None
    correlation: float | None = None
    adv_ratio: float | None = None
    if universe_frame is not None and {
        "symbol", "trade_date", "close"
    } <= set(universe_frame.columns):
        uf = universe_frame.copy()
        uf["trade_date"] = pd.to_datetime(uf["trade_date"])
        uf = uf[uf["trade_date"].dt.date <= as_of_date]
        pivoted = uf.pivot_table(
            index="trade_date", columns="symbol", values="close"
        )
        if pivoted.shape[1] >= 10:
            ma50 = pivoted.rolling(50).mean()
            if not ma50.empty:
                last = pivoted.iloc[-1]
                breadth = float((last > ma50.iloc[-1]).mean())
            returns = pivoted.pct_change().tail(21)
            if returns.shape[1] >= 5:
                dispersion = float(returns.std(axis=1).mean() * np.sqrt(252))
                sampled = returns.iloc[:, :30]
                corr = sampled.corr().to_numpy()
                mask = ~np.eye(corr.shape[0], dtype=bool)
                correlation = float(corr[mask].mean()) if mask.any() else None
        if "volume" in universe_frame.columns:
            uf["volume"] = pd.to_numeric(uf["volume"], errors="coerce").fillna(0)
            adv = uf.pivot_table(
                index="trade_date", columns="symbol", values="volume"
            ).mean(axis=1)
            if len(adv) > 63:
                adv_ratio = float(adv.tail(21).mean() / max(1e-9, adv.tail(63).mean()))

    return RegimeInputs(
        spy_return_63=_return_63(spy) if not spy.empty else None,
        qqq_return_63=_return_63(qqq) if not qqq.empty else None,
        spy_above_ma200=_above_ma200(spy) if not spy.empty else None,
        qqq_above_ma200=_above_ma200(qqq) if not qqq.empty else None,
        breadth_pct_above_ma50=breadth,
        cross_sectional_dispersion_21=dispersion,
        realized_volatility_21=_vol_21(spy) if not spy.empty else None,
        average_pairwise_correlation_21=correlation,
        universe_adv_ratio_63=adv_ratio,
        spy_drawdown_252=_drawdown_252(spy) if not spy.empty else None,
    )
