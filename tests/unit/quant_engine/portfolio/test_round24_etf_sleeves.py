"""ROUND24 ETF sleeves portfolio tests (C8-C10, K)."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.factors.etf_factors import (
    EtfFactorSnapshot,
)
from personal_alpha_terminal.quant_engine.portfolio.etf_sleeves import (
    EtfSleeveConfig,
    build_etf_targets,
    compose_multi_sleeve,
)

DECISION = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _factor(
    symbol: str,
    *,
    momentum: float,
    trend: float,
    vol: float,
    drawdown: float,
    consistency: float = 0.8,
    adv: float = 1e9,
) -> EtfFactorSnapshot:
    from datetime import date

    return EtfFactorSnapshot(
        symbol=symbol,
        as_of_date=date(2026, 8, 13),
        momentum_252_21=momentum,
        trend_slope_126=trend,
        trend_consistency_126=consistency,
        volatility_63=vol,
        max_drawdown_252=drawdown,
        risk_adjusted_momentum=momentum / vol if vol > 0 else None,
        relative_strength_252=None,
        relative_strength_benchmark=None,
        correlation_63_benchmark=None,
        average_dollar_volume_20=adv,
        volume_ratio_20_63=1.0,
        price_observations=400,
    )


def test_core_targets_respect_budget_and_position_cap() -> None:
    factors = (
        _factor("VOO", momentum=0.15, trend=0.10, vol=0.15, drawdown=-0.05),
        _factor("QQQ", momentum=0.18, trend=0.12, vol=0.18, drawdown=-0.08),
        _factor("VTI", momentum=0.12, trend=0.09, vol=0.14, drawdown=-0.06),
    )
    config = EtfSleeveConfig(core_budget=0.25, max_single_etf_weight=0.10)
    targets = build_etf_targets(
        factors,
        sleeve="ETF_CORE",
        current_weights={},
        portfolio_value=100_000.0,
        decision_time=DECISION,
        config=config,
    )
    positive = [item for item in targets if item.target_weight > 0]
    assert positive
    total = sum(item.target_weight for item in positive)
    assert total <= config.core_budget + 1e-9
    assert all(
        item.target_weight <= config.max_single_etf_weight + 1e-9 for item in positive
    )
    assert all(item.sleeve == "ETF_CORE" for item in positive)


def test_core_low_turnover_band_keeps_existing_weight() -> None:
    factors = (_factor("VOO", momentum=0.15, trend=0.10, vol=0.15, drawdown=-0.05),)
    config = EtfSleeveConfig(no_trade_band=0.0025)
    current = {"VOO": 0.0995}
    targets = build_etf_targets(
        factors,
        sleeve="ETF_CORE",
        current_weights=current,
        portfolio_value=100_000.0,
        decision_time=DECISION,
        config=config,
    )
    voo = next(item for item in targets if item.symbol == "VOO")
    assert abs(voo.target_weight - 0.0995) < 1e-9
    assert abs(voo.delta_weight) < 1e-9


def test_tactical_targets_rank_by_risk_adjusted_momentum() -> None:
    factors = (
        _factor("XLK", momentum=0.20, trend=0.10, vol=0.25, drawdown=-0.10),
        _factor("XLF", momentum=0.10, trend=0.08, vol=0.20, drawdown=-0.06),
        _factor("XLV", momentum=-0.05, trend=-0.02, vol=0.15, drawdown=-0.12),
    )
    targets = build_etf_targets(
        factors,
        sleeve="ETF_TACTICAL",
        current_weights={},
        portfolio_value=100_000.0,
        decision_time=DECISION,
        config=EtfSleeveConfig(tactical_budget=0.10, maximum_tactical_positions=2),
    )
    positive = [item for item in targets if item.target_weight > 0]
    assert {item.symbol for item in positive} == {"XLK", "XLF"}
    by_symbol = {item.symbol: item for item in positive}
    assert by_symbol["XLK"].expected_value > by_symbol["XLF"].expected_value
    xlv = next(item for item in targets if item.symbol == "XLV")
    assert xlv.target_weight == 0.0
    assert "excluded by rank" in xlv.rationale


def test_composition_reports_overlap_and_unavailable_lookthrough() -> None:
    rng = np.random.RandomState(3)
    dates = pd.date_range("2024-08-01", periods=400, freq="B")
    etf_returns = pd.Series(rng.normal(0, 0.01, 400), index=dates)
    stock_returns = etf_returns * 0.95 + pd.Series(
        rng.normal(0, 0.002, 400), index=dates
    )
    composition = compose_multi_sleeve(
        equity_weights={"STOCK_A": 0.08},
        etf_weights={"VOO": 0.07},
        returns={"VOO": etf_returns, "STOCK_A": stock_returns},
        portfolio_value=100_000.0,
        sector_proxy={"VOO": "US_BROAD_MARKET"},
    )
    assert composition.overlap.look_through == "UNAVAILABLE"
    assert composition.overlap.max_etf_stock_correlation["VOO"] >= 0.7
    assert composition.overlap.status == "OVERLAP_WARNING"
    assert composition.sector_exposure_status == "SECTOR_EXPOSURE_NOT_VALIDATED"


def test_composition_scales_back_when_budgets_exceeded() -> None:
    composition = compose_multi_sleeve(
        equity_weights={"A": 0.10},
        etf_weights={"VOO": 0.30, "QQQ": 0.30},
        returns={},
        portfolio_value=100_000.0,
        sector_proxy={"VOO": "US_BROAD_MARKET", "QQQ": "US_BROAD_MARKET_GROWTH"},
    )
    assert composition.scaled_back is True
    assert composition.combined_gross <= 1.0 - 0.05 + 1e-9
    assert composition.cash_weight >= 0.05 - 1e-9


def test_etf_not_passed_through_company_quality_factor() -> None:
    """The ETF sleeve factor scope is price-only; no company fundamentals exist."""
    config = EtfSleeveConfig()
    factors = (_factor("VOO", momentum=0.15, trend=0.10, vol=0.15, drawdown=-0.05),)
    targets = build_etf_targets(
        factors,
        sleeve="ETF_CORE",
        current_weights={},
        portfolio_value=100_000.0,
        decision_time=DECISION,
        config=config,
    )
    assert all(item.model_status == "RESEARCH_CANDIDATE" for item in targets)
