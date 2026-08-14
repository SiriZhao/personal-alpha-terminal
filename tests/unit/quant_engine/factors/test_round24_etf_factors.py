"""ROUND24 ETF factor engine tests (C5, C6; PIT safety)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.factors.etf_factors import (
    compute_etf_factors,
    core_sleeve_eligible,
    tactical_sleeve_eligible,
)

CUTOFF = datetime(2026, 8, 13, 20, 30, tzinfo=UTC)


def _price_frame(symbols: tuple[str, ...], sessions: int = 400, *, seed: int = 7) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    rows: list[dict[str, object]] = []
    start = date(2024, 8, 1)
    for symbol in symbols:
        drift = 0.0004 if symbol in {"VOO", "QQQ"} else -0.0002
        prices = 100 * np.exp(np.cumsum(rng.normal(drift, 0.012, sessions)))
        for index, price in enumerate(prices):
            session_date = start + timedelta(days=index * 2)
            if session_date > date(2026, 8, 13):
                break
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": session_date,
                    "close": float(price),
                    "volume": float(rng.randint(1_000_000, 8_000_000)),
                }
            )
    return pd.DataFrame(rows)


def test_etf_factors_computed_pit_safe() -> None:
    frame = _price_frame(("VOO", "QQQ", "SPY", "XLK"))
    factors = compute_etf_factors(
        frame,
        information_cutoff=CUTOFF,
        benchmark_symbol="SPY",
        benchmark_policy={
            "VOO": "BENCHMARK_UNAVAILABLE_SELF",
            "QQQ": "BENCHMARK_UNAVAILABLE_SELF",
            "XLK": "SPY",
        },
    )
    by_symbol = {item.symbol: item for item in factors}
    assert "VOO" in by_symbol
    assert by_symbol["VOO"].momentum_252_21 is not None
    assert by_symbol["VOO"].volatility_63 is not None
    assert by_symbol["VOO"].relative_strength_benchmark is None
    assert by_symbol["XLK"].relative_strength_benchmark == "SPY"


def test_future_rows_are_dropped() -> None:
    frame = _price_frame(("VOO",))
    future = pd.DataFrame(
        [
            {
                "symbol": "VOO",
                "trade_date": date(2026, 8, 15),
                "close": 999.0,
                "volume": 1_000_000.0,
            }
        ]
    )
    contaminated = pd.concat([frame, future], ignore_index=True)
    factors = compute_etf_factors(
        contaminated,
        information_cutoff=CUTOFF,
        benchmark_symbol="SPY",
        benchmark_policy={"VOO": "BENCHMARK_UNAVAILABLE_SELF"},
    )
    assert len(factors) == 1


def test_core_eligibility_requires_positive_trend_and_momentum() -> None:
    """Deterministic up/down trends make the eligibility check stable."""
    rows: list[dict[str, object]] = []
    start = date(2024, 8, 1)
    for index in range(400):
        session_date = start + timedelta(days=index * 2)
        if session_date > date(2026, 8, 13):
            break
        rows.append(
            {
                "symbol": "UP",
                "trade_date": session_date,
                "close": 100.0 * float(np.exp(0.0009 * index)),
                "volume": 2_000_000.0,
            }
        )
        rows.append(
            {
                "symbol": "DOWN",
                "trade_date": session_date,
                "close": 100.0 * float(np.exp(-0.0009 * index)),
                "volume": 2_000_000.0,
            }
        )
    frame = pd.DataFrame(rows)
    factors = compute_etf_factors(
        frame,
        information_cutoff=CUTOFF,
        benchmark_symbol="SPY",
        benchmark_policy={
            "UP": "BENCHMARK_UNAVAILABLE_SELF",
            "DOWN": "BENCHMARK_UNAVAILABLE_SELF",
        },
    )
    by_symbol = {item.symbol: item for item in factors}
    up_ok, _ = core_sleeve_eligible(by_symbol["UP"])
    down_ok, down_reasons = core_sleeve_eligible(by_symbol["DOWN"])
    assert up_ok
    assert not down_ok
    assert any(
        reason in {"TREND_NOT_POSITIVE", "MOMENTUM_NOT_POSITIVE"}
        for reason in down_reasons
    )


def test_tactical_eligibility_needs_risk_adjusted_momentum() -> None:
    frame = _price_frame(("XLK",))
    factors = compute_etf_factors(
        frame,
        information_cutoff=CUTOFF,
        benchmark_symbol="SPY",
        benchmark_policy={"XLK": "SPY"},
    )
    ok, reasons = tactical_sleeve_eligible(factors[0])
    assert ok, reasons
