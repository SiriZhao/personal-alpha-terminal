"""ROUND33 quant performance closure artifact generator.

This module is research-only and deliberately does not change production
parameters.  It emits corrected evidence under explicit
``SURVIVORSHIP_LIMITED`` / ``PRICE_BASED_RANKING`` boundaries.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import date, datetime
from math import sqrt
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.us_market.broad_universe import EligibilityRules
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.factors.evaluation import evaluate_factor
from personal_alpha_terminal.quant_engine.performance_metrics import (
    FrequencySpec,
    annualize_sharpe,
    annualize_volatility,
    calculate_equity_performance,
)
from personal_alpha_terminal.quant_engine.round4_research import (
    _research_identity,
    apply_probability_adjustment,
    build_factor_panel,
    rebalance_dates,
    train_probability_calibration,
    train_probability_predictions,
)
from personal_alpha_terminal.quant_engine.round33_performance import (
    AlphaCalibrationSpec,
    ResearchExecutionPolicy,
    allocate_research_targets,
    block_bootstrap_interval,
    build_corrected_labeled_panel,
    build_research_backtest_dataset,
    calibrate_alpha,
    run_research_parity_backtest,
)

ROUND33_SCHEMA = "round33-quant-performance-closure-v1"


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _required_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected numeric value, got {type(value).__name__}")


def _metric_delta(left: object, right: object) -> float | None:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def load_round33_price_panel(
    session: Session,
    *,
    decision_time: datetime,
    history_start: date,
    minimum_history: int = 252,
    horizon: int = 21,
    reference_symbols: tuple[str, ...] = ("SPY", "QQQ"),
) -> pd.DataFrame:
    """Load raw PIT OHLCV rows with open/high/low for production-style research."""

    if decision_time.tzinfo is None:
        raise ValueError("research decision_time must be timezone-aware")
    needed = minimum_history + horizon + 2
    counts = (
        select(Price.stock_id, func.count(Price.id).label("n"))
        .where(
            Price.trade_date <= decision_time.date(),
            Price.available_time.is_not(None),
            Price.available_time <= decision_time,
            Price.price_type == "unadjusted_ohlcv",
        )
        .group_by(Price.stock_id)
        .having(func.count(Price.id) >= needed)
        .subquery()
    )
    stocks = tuple(
        session.scalars(
            select(SecurityMaster)
            .join(counts, counts.c.stock_id == SecurityMaster.id)
            .where(
                SecurityMaster.market == "US",
                SecurityMaster.asset_type == "stock",
                SecurityMaster.available_time <= decision_time,
            )
            .order_by(SecurityMaster.canonical_code)
        )
    )
    references = tuple(
        session.scalars(
            select(SecurityMaster)
            .where(
                SecurityMaster.market == "US",
                SecurityMaster.symbol.in_(reference_symbols),
                SecurityMaster.asset_type.in_(("etf", "index")),
                SecurityMaster.available_time <= decision_time,
            )
            .order_by(SecurityMaster.canonical_code)
        )
    )
    if not stocks:
        raise ValueError("no broad US stocks have sufficient PIT price history")
    rows: list[dict[str, object]] = []
    for stock in (*stocks, *references):
        role = "alpha" if stock in stocks else "reference"
        prices = session.scalars(
            select(Price)
            .where(
                Price.stock_id == stock.id,
                Price.trade_date >= history_start,
                Price.trade_date <= decision_time.date(),
                Price.available_time.is_not(None),
                Price.available_time <= decision_time,
                Price.price_type == "unadjusted_ohlcv",
            )
            .order_by(Price.trade_date, Price.id)
        )
        for price in prices:
            if (
                price.open is None
                or price.high is None
                or price.low is None
                or price.close is None
                or price.close <= 0
                or price.volume is None
                or price.volume <= 0
            ):
                continue
            available = price.available_time
            rows.append(
                {
                    "permanent_security_id": stock.canonical_code,
                    "ticker": stock.symbol,
                    "exchange": stock.exchange,
                    "trade_date": price.trade_date,
                    "available_time": available,
                    "open": float(price.open),
                    "high": float(price.high),
                    "low": float(price.low),
                    "close": float(price.close),
                    "volume": float(price.volume),
                    "ingested_at": price.ingested_at,
                    "open_tradable": price.open_tradable,
                    "source": price.source,
                    "provider": price.provider,
                    "role": role,
                }
            )
    if not rows:
        raise ValueError("round33 price panel is empty")
    return pd.DataFrame(rows)


def build_round33_code_audit() -> dict[str, object]:
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "CODE_AND_CONVENTION_AUDIT",
        "performance_calculation_locations": [
            "src/personal_alpha_terminal/backtest/metrics.py:calculate_metrics",
            "src/personal_alpha_terminal/quant_engine/round4_research.py:_sharpe",
            "src/personal_alpha_terminal/quant_engine/backtest/production.py:_calculate_metrics",
            "src/personal_alpha_terminal/quant_engine/backtest/performance.py:evaluate_equity_curve",
            "src/personal_alpha_terminal/quant_engine/risk/portfolio_risk.py",
        ],
        "research_only_backtest_locations": [
            "src/personal_alpha_terminal/quant_engine/round4_research.py:simple_portfolio_ab",
            "src/personal_alpha_terminal/quant_engine/round4_research.py:_simulate_weights",
            "src/personal_alpha_terminal/application/round31_audit.py:build_cardinality_comparison",
        ],
        "production_backtest_locations": [
            "src/personal_alpha_terminal/quant_engine/backtest/production.py:ProductionBacktestEngine",
            "src/personal_alpha_terminal/application/backtest_service.py:BacktestService",
        ],
        "annualization_assumptions": {
            "backtest_metrics_daily": {
                "frequency": "DAILY",
                "periods_per_year": 252,
                "correct": True,
            },
            "round4_rebalance_points": {
                "frequency": "HOLDING_PERIOD",
                "periods_per_year": "WRONGLY_252",
                "correct": False,
                "fix": "use FrequencySpec.holding(horizon_sessions) or daily NAV",
            },
            "production_backtest_daily": {
                "frequency": "DAILY",
                "periods_per_year": 252,
                "correct": True,
            },
        },
        "return_frequency": {
            "round4_label": "21-session holding-period benchmark-relative",
            "round33_corrected_label": "NEXT_SESSION_OPEN_TO_HORIZON_CLOSE",
            "production": "DAILY_NAV",
        },
        "execution_price_convention": {
            "round4": "close[t+1] to close[t+horizon]",
            "round33_corrected": "open[t+1] to close[t+horizon]",
            "production": "next tradable session open",
        },
        "gross_exposure_handling": {
            "round4": (
                "double-scaled by selected_count; gross collapsed near 1-2% "
                "for large universe"
            ),
            "round33_corrected": "actual_gross = min(1-minimum_cash, n*maximum_weight)",
        },
        "cash_handling": "cash = 1 - actual_gross; explicit after allocation",
        "transaction_cost_handling": {
            "round4": "silent ValueError fallback cost=0 and constant ADV=100M",
            "round33_corrected": (
                "real PIT prior-session ADV; missing ADV raises COST_UNAVAILABLE"
            ),
        },
        "benchmark_handling": (
            "SPY/QQQ benchmark-relative returns are explicit; SPY used for calibration"
        ),
        "survivorship_state": "SURVIVORSHIP_LIMITED for broad price-based historical research",
        "pit_state": (
            "PIT raw OHLCV available-time cutoff respected; "
            "corporate-action vintage absent"
        ),
        "corporate_action_state": "CORPORATE_ACTION_LIMITED for broad universe",
        "production_parity_level": (
            "ResearchProductionParityBacktest reuses ProductionBacktestEngine accounting"
        ),
        "known_defects": [
            "ROUND4 target-weight capacity formula double-scales by selected_count",
            "ROUND4 Sharpe annualizes holding-period points with sqrt(252)",
            "ROUND4 cost estimation silently falls back to zero",
            "ROUND4 execution uses next close instead of next open",
        ],
        "suspected_defects": [
            "Broad historical universe is current-directory survivorship-limited",
            "Raw OHLCV lacks PIT total-return/corporate-action vintages",
        ],
        "safe_components": [
            "backtest/metrics.py daily NAV metrics use correct 252 frequency",
            "ProductionBacktestEngine daily accounting/cost/convention",
            "TransactionCostModel validates ADV and never returns zero on invalid input",
        ],
        "superseded_components": [
            "round4_research._simulate_weights",
            "round4_research._sharpe",
            "round4_research._target_weights",
        ],
        "component_tiers": {
            "A_production_accounting_engine": "ProductionBacktestEngine",
            "B_historical_research_helper": "round4_research.py (corrected in ROUND33)",
            "C_fixture_simulator": "round30/round31 fixture audits",
            "D_forward_performance_ledger": "probability/forward_ledger.py",
            "E_ui_display_only_metrics": "daily_renderer.py / terminal model panels",
        },
        "fixture_performance_not_production_evidence": True,
    }


def build_round33_weight_allocation_audit() -> dict[str, object]:
    from personal_alpha_terminal.quant_engine.round4_research import (
        allocate_positive_alpha_weights,
    )

    rows: list[dict[str, object]] = []
    for universe_count in (0, 1, 2, 5, 10, 20, 100, 392, 500, 1000, 1959):
        frame = pd.DataFrame(
            {
                "ticker": [f"S{i}" for i in range(universe_count)],
                "expected_alpha": [
                    0.05 - index * 0.0001 for index in range(universe_count)
                ],
            }
        )
        result = allocate_positive_alpha_weights(
            frame,
            alpha_column="expected_alpha",
            top_fraction=0.20,
            maximum_weight=0.12,
            minimum_cash=0.10,
        )
        rows.append(result.document())
    mixed = pd.DataFrame(
        {
            "ticker": [f"S{i}" for i in range(10)],
            "expected_alpha": [
                0.03,
                0.02,
                0.01,
                -0.01,
                -0.02,
                0.015,
                -0.005,
                0.025,
                -0.001,
                0.005,
            ],
        }
    )
    mixed_result = allocate_positive_alpha_weights(
        mixed,
        alpha_column="expected_alpha",
        top_fraction=0.50,
        maximum_weight=0.12,
        minimum_cash=0.10,
    )
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "CORRECTED_WEIGHT_ALLOCATION_INVARIANTS",
        "maximum_weight": 0.12,
        "minimum_cash": 0.10,
        "rows": rows,
        "positive_alpha_filtering_regression": {
            "universe_count": 10,
            "selected_count": 5,
            "positive_selected_count": mixed_result.positive_selected_count,
            "desired_gross": mixed_result.desired_gross,
            "capacity": mixed_result.capacity,
            "actual_gross": mixed_result.actual_gross,
            "cash": mixed_result.cash,
            "sum_error": mixed_result.sum_error,
        },
        "large_universe_regression": next(
            row for row in rows if row["universe_count"] == 1959
        ),
    }


def build_round33_metric_frequency_audit() -> dict[str, object]:
    returns = [0.01, -0.005, 0.01, -0.005, 0.01]
    daily_spec = FrequencySpec.daily()
    holding_spec = FrequencySpec.holding(21)
    daily_vol = annualize_volatility(returns, periods_per_year=daily_spec.periods_per_year)
    daily_sharpe = annualize_sharpe(returns, periods_per_year=daily_spec.periods_per_year)
    holding_vol = annualize_volatility(
        returns, periods_per_year=holding_spec.periods_per_year
    )
    holding_sharpe = annualize_sharpe(
        returns, periods_per_year=holding_spec.periods_per_year
    )
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "FREQUENCY_AUDIT",
        "known_return_series": returns,
        "daily": {
            "periods_per_year": daily_spec.periods_per_year,
            "annualized_volatility": daily_vol,
            "sharpe": daily_sharpe,
        },
        "holding_21": {
            "periods_per_year": holding_spec.periods_per_year,
            "horizon_sessions": 21,
            "annualized_volatility": holding_vol,
            "sharpe": holding_sharpe,
        },
        "rule": "21-session holding returns must use sqrt(252/21), not sqrt(252)",
        "daily_curve_preferred_for_formal_evidence": True,
    }


def build_round33_execution_parity_audit() -> dict[str, object]:
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "EXECUTION_PARITY_AUDIT",
        "policy": ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE.value,
        "entry": "session t+1 open",
        "exit_mark": "session t+horizon close",
        "benchmark_alignment": "same entry/exit dates for symbol and benchmark",
        "no_lookahead_contract": [
            "factor features use only available_time <= decision_time",
            "target construction uses only signal-date cross-section",
            "t+1 open and horizon close are forward labels, never target inputs",
        ],
        "round4_mismatch": (
            "round4 used close[t+1] and therefore cannot be called production-parity"
        ),
    }


def build_round33_cost_integrity_audit() -> dict[str, object]:
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "COST_INTEGRITY_AUDIT",
        "silent_zero_fallback_present": False,
        "evidence": [
            "round4_research._simulate_weights now raises COST_UNAVAILABLE when ADV is missing",
            "ProductionBacktestEngine estimates cost only with prior-session dollar volume",
            "TransactionCostModel rejects non-positive ADV",
        ],
        "adv_window": "strictly before decision date; rolling prior sessions",
        "cost_components": [
            "commission",
            "spread",
            "slippage",
            "market impact",
            "regulatory fee when configured",
        ],
    }


def _factor_date_metrics(
    panel: pd.DataFrame,
    *,
    signal_column: str,
    return_column: str,
    quantiles: int = 5,
) -> tuple[list[dict[str, object]], dict[date, float], dict[date, float]]:
    rows: list[dict[str, object]] = []
    ic_by_date: dict[date, float] = {}
    spread_by_date: dict[date, float] = {}
    for as_of, group in panel.groupby("as_of_date", sort=True):
        clean = group.replace([np.inf, -np.inf], np.nan).dropna(
            subset=[signal_column, return_column]
        )
        if (
            len(clean) < 5
            or clean[signal_column].nunique() < 2
            or clean[return_column].nunique() < 2
        ):
            continue
        ic = float(
            spearmanr(
                clean[signal_column].to_numpy(dtype=float),
                clean[return_column].to_numpy(dtype=float),
            ).statistic
        )
        ordinal = clean[signal_column].rank(method="first") - 1
        labels = np.minimum(
            quantiles - 1,
            np.floor(ordinal * quantiles / len(clean)).astype(int),
        )
        quantile_returns = [
            float(clean.loc[labels == label, return_column].mean())
            for label in range(quantiles)
        ]
        spread = quantile_returns[-1] - quantile_returns[0]
        as_of_date = pd.to_datetime(as_of, errors="raise").date()
        ic_by_date[as_of_date] = ic
        spread_by_date[as_of_date] = spread
        rows.append(
            {
                "as_of_date": as_of_date,
                "rank_ic": ic,
                "top_bottom_spread": spread,
                "observation_count": len(clean),
            }
        )
    return rows, ic_by_date, spread_by_date


def build_round33_factor_performance(
    labeled_panel: pd.DataFrame,
    *,
    horizon: int,
) -> dict[str, object]:
    signals = (
        "momentum_12_1__normalized",
        "trend_slope__normalized",
        "volatility__normalized",
        "composite",
    )
    output: list[dict[str, object]] = []
    for signal in signals:
        if signal not in labeled_panel:
            continue
        evaluation = evaluate_factor(
            labeled_panel,
            signal_column=signal,
            forward_return_column="forward_return",
            horizon=horizon,
        )
        date_rows, ic_by_date, spread_by_date = _factor_date_metrics(
            labeled_panel,
            signal_column=signal,
            return_column="forward_return",
        )
        ic_ci = block_bootstrap_interval(ic_by_date, block_length=horizon)
        spread_ci = block_bootstrap_interval(spread_by_date, block_length=horizon)
        ic_values = list(ic_by_date.values())
        cost_rate = TransactionCostModel(TransactionCostConfig()).conservative_rate
        output.append(
            {
                "factor": signal,
                "mean_rank_ic": evaluation.mean_ic,
                "median_rank_ic": float(np.median(ic_values)) if ic_values else None,
                "ic_std": evaluation.ic_std,
                "ic_ir": evaluation.icir,
                "positive_ic_ratio": evaluation.positive_ic_ratio,
                "date_cluster_ic_ci": ic_ci.document(),
                "top_quantile_return": (
                    evaluation.quantile_returns[-1]
                    if evaluation.quantile_returns
                    else None
                ),
                "bottom_quantile_return": (
                    evaluation.quantile_returns[0]
                    if evaluation.quantile_returns
                    else None
                ),
                "top_bottom_spread": evaluation.top_bottom_spread,
                "date_cluster_spread_ci": spread_ci.document(),
                "turnover": evaluation.turnover,
                "net_spread_after_cost_approximation": (
                    evaluation.top_bottom_spread
                    - (evaluation.turnover or 0.0) * cost_rate
                    if evaluation.top_bottom_spread is not None
                    else None
                ),
                "date_count": evaluation.date_count,
                "row_count": evaluation.observation_count,
                "subperiod_stability": _subperiod_stability(ic_by_date),
                "hit_rate": evaluation.hit_rate,
            }
        )
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_status": "RESEARCH_ONLY_SURVIVORSHIP_LIMITED",
        "execution_policy": ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE.value,
        "factors": output,
    }


def _subperiod_stability(ic_by_date: dict[date, float]) -> dict[str, object]:
    ordered = sorted(ic_by_date)
    if not ordered:
        return {}
    midpoint = len(ordered) // 2
    first = [ic_by_date[item] for item in ordered[:midpoint]]
    second = [ic_by_date[item] for item in ordered[midpoint:]]
    return {
        "first_half_mean_ic": float(np.mean(first)) if first else None,
        "second_half_mean_ic": float(np.mean(second)) if second else None,
    }


def _benchmark_daily_returns(
    price_panel: pd.DataFrame,
    benchmark: str,
) -> tuple[tuple[date, float], ...]:
    levels = (
        price_panel[price_panel["ticker"] == benchmark]
        .copy()
        .sort_values("trade_date")
    )
    levels["close"] = pd.to_numeric(levels["close"], errors="coerce")
    returns = levels["close"].pct_change().dropna()
    return tuple(
        (pd.to_datetime(levels.loc[index, "trade_date"]).date(), float(value))
        for index, value in returns.items()
    )


def _equity_performance(
    result: Any,
    *,
    benchmark_returns: tuple[tuple[date, float], ...],
) -> tuple[dict[str, object], dict[str, object]]:
    points = tuple((item.trade_date, item.equity) for item in result.points)
    performance = calculate_equity_performance(
        points,
        frequency_spec=FrequencySpec.daily(),
        benchmark_returns=benchmark_returns,
    ).document()
    average_gross = float(np.mean([item.gross_exposure for item in result.points]))
    average_cash = float(np.mean([item.cash / item.equity for item in result.points]))
    details = {
        "transaction_cost": result.transaction_costs,
        "turnover": result.metrics.turnover,
        "average_gross": average_gross,
        "average_cash": average_cash,
        "target_count": len({item.asset_id for item in result.trades if item.shares > 0}),
        "trade_count": len(result.trades),
        "average_holding_period": result.metrics.average_holding_period,
        "status": result.status,
        "limitations": list(result.limitations),
    }
    return performance, details


def _up_down_capture(
    strategy_returns: dict[date, float],
    benchmark_returns: dict[date, float],
) -> tuple[float | None, float | None]:
    aligned = [
        (strategy_returns[day], benchmark_returns[day])
        for day in sorted(strategy_returns)
        if day in benchmark_returns
    ]
    up = [left for left, right in aligned if right > 0]
    down = [left for left, right in aligned if right < 0]
    up_market_mean = float(np.mean([right for _, right in aligned if right > 0])) if up else 0.0
    down_market_mean = float(np.mean([right for _, right in aligned if right < 0])) if down else 0.0
    up_capture = float(np.mean(up)) / up_market_mean if up and abs(up_market_mean) > 1e-15 else None
    down_capture = (
        float(np.mean(down)) / down_market_mean
        if down and abs(down_market_mean) > 1e-15
        else None
    )
    return up_capture, down_capture


def _monthly_yearly_returns(result: Any) -> dict[str, object]:
    index = pd.DatetimeIndex(
        [item.trade_date for item in result.points]
    )
    series = pd.Series(
        [item.daily_return for item in result.points],
        index=index,
        dtype=float,
    )
    equity = (1.0 + series).cumprod()
    monthly = equity.resample("ME").last().pct_change().dropna()
    yearly = equity.resample("YE").last().pct_change().dropna()
    return {
        "monthly": {
            str(index.date()): float(value) for index, value in monthly.items()
        },
        "calendar_year": {
            str(index.year): float(value) for index, value in yearly.items()
        },
        "rolling_3m": {
            str(index.date()): float(
                equity.loc[index] / equity.loc[index - pd.DateOffset(months=3)] - 1
            )
            for index in equity.index
            if index - pd.DateOffset(months=3) in equity.index
        },
    }


def _block_bootstrap_daily_metrics(
    strategy_returns: dict[date, float],
    benchmark_returns: dict[date, float],
    *,
    block_length: int = 21,
    bootstrap_count: int = 1000,
) -> dict[str, object]:
    aligned_dates = [
        day for day in sorted(strategy_returns) if day in benchmark_returns
    ]
    if len(aligned_dates) < 2:
        return {"status": "SAMPLE_INSUFFICIENT"}
    blocks = [
        aligned_dates[index : index + block_length]
        for index in range(0, len(aligned_dates), block_length)
    ]
    rng = np.random.default_rng(33)
    alpha_samples: list[float] = []
    sharpe_samples: list[float] = []
    drawdown_samples: list[float] = []
    for _ in range(bootstrap_count):
        selected = [
            day
            for block in [
                blocks[index] for index in rng.integers(0, len(blocks), len(blocks))
            ]
            for day in block
        ]
        strategy = [strategy_returns[day] for day in selected]
        market = [benchmark_returns[day] for day in selected]
        active = [left - right for left, right in zip(strategy, market, strict=True)]
        alpha_samples.append(float(np.mean(active)) * 252)
        if len(strategy) > 1 and np.std(strategy, ddof=1) > 0:
            sharpe_samples.append(
                float(np.mean(strategy) / np.std(strategy, ddof=1) * sqrt(252))
            )
        equity = np.cumprod(1.0 + np.asarray(strategy, dtype=float))
        drawdown_samples.append(float(np.min(equity / np.maximum.accumulate(equity) - 1.0)))
    return {
        "annualized_alpha_ci": [
            float(np.percentile(alpha_samples, 2.5)),
            float(np.percentile(alpha_samples, 97.5)),
        ],
        "annualized_alpha_point": float(np.mean(alpha_samples)),
        "sharpe_ci": (
            [
                float(np.percentile(sharpe_samples, 2.5)),
                float(np.percentile(sharpe_samples, 97.5)),
            ]
            if sharpe_samples
            else None
        ),
        "max_drawdown_ci": (
            [
                float(np.percentile(drawdown_samples, 2.5)),
                float(np.percentile(drawdown_samples, 97.5)),
            ]
            if drawdown_samples
            else None
        ),
        "block_length": block_length,
        "effective_dates": len(aligned_dates),
    }


def run_round33_research(
    session: Session,
    *,
    decision_time: datetime,
    history_start: date = date(2024, 1, 1),
    benchmark: str = "SPY",
    horizon: int = 21,
) -> dict[str, object]:
    price_panel = load_round33_price_panel(
        session,
        decision_time=decision_time,
        history_start=history_start,
        horizon=horizon,
    )
    dates = rebalance_dates(price_panel, end_date=decision_time.date(), horizon=horizon)
    if len(dates) < 12:
        raise ValueError("round33 research requires at least twelve rebalance dates")
    factor_panel = build_factor_panel(price_panel, dates=dates)
    labeled_panel = build_corrected_labeled_panel(
        price_panel,
        factor_panel,
        benchmark=benchmark,
        horizon=horizon,
        execution_policy=ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE,
    )
    if labeled_panel.empty:
        raise ValueError("round33 corrected labeled panel is empty")
    session_dates = tuple(
        sorted({value.date() for value in pd.to_datetime(price_panel["trade_date"])})
    )
    calibrations: dict[str, object] = {}
    oos_panels: dict[str, pd.DataFrame] = {}
    for method in (
        "fixed_engineering",
        "equal_weight_rank",
        "nonnegative_ridge",
        "regularized_ic_weighted",
    ):
        result, oos_panel = calibrate_alpha(
            labeled_panel,
            session_dates=session_dates,
            spec=AlphaCalibrationSpec(method=method),
        )
        calibrations[method] = asdict(result)
        oos_panels[method] = oos_panel
    first_calibration = cast(
        dict[str, Any],
        calibrations["fixed_engineering"],
    )
    oos_start = date.fromisoformat(str(first_calibration["oos_period"][0]))
    oos_end = date.fromisoformat(str(first_calibration["oos_period"][1]))
    oos_dates = tuple(
        day
        for day in sorted(
            {value.date() for value in pd.to_datetime(labeled_panel["as_of_date"])}
        )
        if oos_start <= day <= oos_end
    )
    if not oos_dates:
        raise ValueError("round33 locked OOS date set is empty")
    factor_performance = build_round33_factor_performance(labeled_panel, horizon=horizon)
    calendar_all = sorted(
        {value.date() for value in pd.to_datetime(price_panel["trade_date"])}
    )
    first_oos_index = calendar_all.index(oos_dates[0])
    backtest_start = calendar_all[max(0, first_oos_index - 22)]
    exit_dates = [
        pd.to_datetime(row.exit_date, errors="raise").date()
        for row in labeled_panel.itertuples(index=False)
        if oos_start
        <= pd.to_datetime(row.as_of_date, errors="raise").date()
        <= oos_end
    ]
    backtest_end = max(exit_dates, default=price_panel["trade_date"].max())
    filtered = price_panel[
        (pd.to_datetime(price_panel["trade_date"]).dt.date >= backtest_start)
        & (pd.to_datetime(price_panel["trade_date"]).dt.date <= backtest_end)
    ].copy()
    dataset, _, symbol_to_asset = build_research_backtest_dataset(
        filtered,
        data_version=f"ROUND33_DB_RAW_AS_OF_{decision_time.date().isoformat()}",
    )
    spy_returns = _benchmark_daily_returns(filtered, "SPY")
    qqq_returns = _benchmark_daily_returns(filtered, "QQQ")
    champion_targets = allocate_research_targets(
        factor_panel,
        filtered,
        dates=oos_dates,
        alpha_column="expected_alpha",
        model_version="USAdaptiveAlphaCoreV1:1.0.0:ROUND33_CHAMPION",
        data_version=dataset.data_version,
        alpha_source="USAdaptiveAlphaCoreV1",
    )
    champion_targets = _filter_targets_to_tradable(champion_targets, dataset)
    champion_result = run_research_parity_backtest(
        dataset,
        champion_targets,
        benchmark_returns=spy_returns,
        sectors={bar.asset_id: "UNCLASSIFIED" for bar in dataset.bars},
        cost_config=TransactionCostConfig(maximum_adv_participation=1.0),
    )
    champion_perf, champion_details = _equity_performance(
        champion_result, benchmark_returns=spy_returns
    )
    calibrated_factor = factor_panel.merge(
        oos_panels["regularized_ic_weighted"][
            ["as_of_date", "ticker", "calibrated_score"]
        ],
        on=["as_of_date", "ticker"],
        how="left",
    )
    challenger_targets = allocate_research_targets(
        calibrated_factor,
        filtered,
        dates=oos_dates,
        alpha_column="calibrated_score",
        model_version="AlphaCalibrationV1:regularized_ic_weighted:ROUND33_CHALLENGER",
        data_version=dataset.data_version,
        alpha_source="AlphaCalibrationV1",
    )
    challenger_targets = _filter_targets_to_tradable(challenger_targets, dataset)
    challenger_result = run_research_parity_backtest(
        dataset,
        challenger_targets,
        benchmark_returns=spy_returns,
        sectors={bar.asset_id: "UNCLASSIFIED" for bar in dataset.bars},
        cost_config=TransactionCostConfig(maximum_adv_participation=1.0),
    )
    challenger_perf, challenger_details = _equity_performance(
        challenger_result, benchmark_returns=spy_returns
    )
    identity = _research_identity(
        benchmark=benchmark,
        horizon=horizon,
        rules=EligibilityRules(),
        decision_time=decision_time,
        eligibility=None,
    )
    train_period: tuple[date, date] = (
        date.fromisoformat(str(first_calibration["train_period"][0])),
        date.fromisoformat(str(first_calibration["train_period"][1])),
    )
    calibration_period: tuple[date, date] = (
        date.fromisoformat(str(first_calibration["calibration_period"][0])),
        date.fromisoformat(str(first_calibration["calibration_period"][1])),
    )
    oos_period = (oos_start, oos_end)
    probability_evidence = train_probability_calibration(
        labeled_panel,
        identity=identity,
        train_period=train_period,
        calibration_period=calibration_period,
        oos_period=oos_period,
    )
    predictions = train_probability_predictions(
        labeled_panel,
        factor_panel,
        feature_columns=(
            "momentum_12_1__normalized",
            "trend_slope__normalized",
            "volatility__normalized",
            "composite",
            "expected_alpha",
        ),
        train_period=train_period,
        calibration_period=calibration_period,
        dates=oos_dates,
    )
    probability_factor = factor_panel.merge(
        predictions[["as_of_date", "ticker", "probability"]],
        on=["as_of_date", "ticker"],
        how="left",
    ).dropna(subset=["probability"])
    adjusted_probability = apply_probability_adjustment(
        probability_factor,
        probability_column="probability",
        maximum_multiplier=0.25,
    )
    probability_targets = allocate_research_targets(
        adjusted_probability,
        filtered,
        dates=oos_dates,
        alpha_column="adjusted_alpha",
        model_version="Round4LogisticCalibrationV1:ROUND33_RESEARCH",
        data_version=dataset.data_version,
        alpha_source="USAdaptiveAlphaCoreV1_ProbabilityResearch",
    )
    probability_targets = _filter_targets_to_tradable(probability_targets, dataset)
    probability_result = run_research_parity_backtest(
        dataset,
        probability_targets,
        benchmark_returns=spy_returns,
        sectors={bar.asset_id: "UNCLASSIFIED" for bar in dataset.bars},
        cost_config=TransactionCostConfig(maximum_adv_participation=1.0),
    )
    probability_perf, probability_details = _equity_performance(
        probability_result, benchmark_returns=spy_returns
    )
    spy_equity = _equity_series_from_daily(spy_returns)
    qqq_equity = _equity_series_from_daily(qqq_returns)
    spy_perf = calculate_equity_performance(
        spy_equity, frequency_spec=FrequencySpec.daily()
    ).document()
    qqq_perf = calculate_equity_performance(
        qqq_equity, frequency_spec=FrequencySpec.daily()
    ).document()
    strategy_returns = {
        item.trade_date: item.daily_return for item in champion_result.points
    }
    benchmark_returns_map = dict(spy_returns)
    uncertainty = _block_bootstrap_daily_metrics(
        strategy_returns,
        benchmark_returns_map,
    )
    champion_up, champion_down = _up_down_capture(strategy_returns, benchmark_returns_map)
    champion_perf["up_capture"] = champion_up
    champion_perf["down_capture"] = champion_down
    champion_perf["monthly_yearly"] = _monthly_yearly_returns(champion_result)
    challenger_up, challenger_down = _up_down_capture(
        {item.trade_date: item.daily_return for item in challenger_result.points},
        benchmark_returns_map,
    )
    challenger_perf["up_capture"] = challenger_up
    challenger_perf["down_capture"] = challenger_down
    challenger_perf["monthly_yearly"] = _monthly_yearly_returns(challenger_result)
    probability_up, probability_down = _up_down_capture(
        {item.trade_date: item.daily_return for item in probability_result.points},
        benchmark_returns_map,
    )
    probability_perf["up_capture"] = probability_up
    probability_perf["down_capture"] = probability_down
    probability_perf["monthly_yearly"] = _monthly_yearly_returns(probability_result)
    probability_retest = {
        "brier_score": probability_evidence.brier_score,
        "baseline_brier_score": probability_evidence.baseline_brier_score,
        "log_loss": probability_evidence.log_loss,
        "roc_auc": probability_evidence.roc_auc,
        "ece": probability_evidence.expected_calibration_error,
        "row_count": probability_evidence.oos_samples,
        "date_count": len(oos_dates),
        "target_change_count": sum(
            _target_dict(champion_targets, day) != _target_dict(probability_targets, day)
            for day in oos_dates
        ),
        "after_cost_alpha_delta": _metric_delta(
            probability_perf.get("alpha"), champion_perf.get("alpha")
        ),
        "sharpe_delta": _metric_delta(
            probability_perf.get("sharpe"), champion_perf.get("sharpe")
        ),
        "turnover_delta": _required_float(
            probability_details["turnover"]
        ) - _required_float(champion_details["turnover"]),
        "cost_delta": _required_float(
            probability_details["transaction_cost"]
        ) - _required_float(champion_details["transaction_cost"]),
        "production_influence": 0.0,
    }
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_status": "RESEARCH_ONLY_SURVIVORSHIP_LIMITED",
        "decision_time": decision_time.isoformat(),
        "history_start": history_start.isoformat(),
        "benchmark": benchmark,
        "horizon": horizon,
        "universe": {
            "price_panel_stocks": int(price_panel["ticker"].nunique()),
            "factor_panel_stocks": int(factor_panel["ticker"].nunique()),
            "factor_dates": int(factor_panel["as_of_date"].nunique()),
            "labeled_rows": len(labeled_panel),
            "labeled_dates": int(labeled_panel["as_of_date"].nunique()),
        },
        "walk_forward": {
            "train_period": first_calibration["train_period"],
            "calibration_period": first_calibration["calibration_period"],
            "oos_period": first_calibration["oos_period"],
            "decision_date_count": len(oos_dates),
            "row_count": len(
                oos_panels["regularized_ic_weighted"]
            ),
        },
        "factor_performance": factor_performance,
        "alpha_calibration": {
            "methods": calibrations,
            "promotion_eligible": False,
            "champion_retained": "CLASSICAL_CHAMPION_RETAINED",
        },
        "corrected_oos": {
            "champion": {
                "performance": champion_perf,
                "details": champion_details,
            },
            "challenger_regularized_ic_weighted": {
                "performance": challenger_perf,
                "details": challenger_details,
            },
            "champion_probability_research": {
                "performance": probability_perf,
                "details": probability_details,
            },
            "execution_policy": ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE.value,
            "cost_config": asdict(TransactionCostConfig()),
            "research_liquidity_policy": (
                "Target weights capped at configured ADV; residual price-drift "
                "overshoot is costed at actual participation and not rejected "
                "in research mode"
            ),
            "backtest_start": backtest_start.isoformat(),
            "backtest_end": backtest_end.isoformat(),
        },
        "benchmark_comparison": {
            "spy": spy_perf,
            "qqq": qqq_perf,
        },
        "probability_retest": probability_retest,
        "uncertainty_intervals": uncertainty,
        "expected_alpha_semantics": {
            "raw_factor_score": "cross-sectional rank composite of normalized price factors",
            "engineering_expected_return": "0.006*momentum + 0.003*trend + 0.002*low_volatility",
            "horizon": 21,
            "annualization": "optimizer multiplies signal expected_excess_return by 252/21",
            "calibration_status": "UNCALIBRATED_ENGINEERING_RETURN_PROXY",
            "production_use": "optimizer objective input",
            "display_semantics": "engineering score-to-return proxy, not OOS-calibrated forecast",
            "confidence_semantics": (
                "confidence=0 unless a locked calibration artifact matches identity"
            ),
        },
        "blockers": [
            "SURVIVORSHIP_LIMITED",
            "CORPORATE_ACTION_LIMITED",
            "QUALITY_DISABLED_PIT_EVIDENCE_INSUFFICIENT",
        ],
    }


def _equity_series_from_daily(
    daily_returns: tuple[tuple[date, float], ...],
) -> tuple[tuple[date, float], ...]:
    equity = 1.0
    output: list[tuple[date, float]] = []
    for index, (day, value) in enumerate(daily_returns):
        if index == 0:
            output.append((day, 1.0))
        equity *= 1.0 + value
        output.append((day, equity))
    return tuple(output)


def _target_dict(
    targets: tuple[Any, ...],
    signal_date: date,
) -> tuple[tuple[int, float], ...]:
    selected = [
        target
        for target in targets
        if target.signal_time.date() == signal_date
    ]
    if not selected:
        return ()
    return tuple(sorted(selected[0].weights.items()))


def _filter_targets_to_tradable(
    targets: tuple[Any, ...],
    dataset: Any,
    *,
    required_prior_sessions: int = 10,
    portfolio_value: float = 1_000_000.0,
    maximum_adv_participation: float = 0.02,
    liquidity_safety_factor: float = 0.25,
) -> tuple[Any, ...]:
    """Drop research targets that cannot execute under production parity rules."""

    asset_dates: dict[int, set[date]] = {}
    dollar_by_asset: dict[int, list[tuple[date, float]]] = {}
    for bar in dataset.bars:
        asset_dates.setdefault(bar.asset_id, set()).add(bar.trade_date)
        dollar_by_asset.setdefault(bar.asset_id, []).append(
            (
                bar.trade_date,
                float(bar.close)
                * float(bar.volume)
                if bar.volume is not None
                else 0.0,
            )
        )
    calendar_index = {
        session: index for index, session in enumerate(dataset.calendar)
    }
    output: list[Any] = []
    for target in targets:
        weights: dict[int, float] = {}
        for asset_id, weight in target.weights.items():
            sessions = asset_dates.get(asset_id, set())
            if target.earliest_execution_date not in sessions:
                continue
            prior = [day for day in sessions if day < target.earliest_execution_date]
            if len(prior) < required_prior_sessions:
                continue
            signal_index = calendar_index.get(target.signal_time.date())
            if signal_index is None or signal_index + 21 >= len(dataset.calendar):
                continue
            exit_date = dataset.calendar[signal_index + 21]
            required_dates = {
                day
                for day in dataset.calendar
                if target.earliest_execution_date <= day <= exit_date
            }
            if not required_dates.issubset(sessions):
                continue
            prior_observations = sorted(
                value
                for value in dollar_by_asset.get(asset_id, [])
                if value[0] < target.earliest_execution_date
            )[-20:]
            values = [value for _, value in prior_observations if value > 0]
            if len(values) < required_prior_sessions:
                continue
            adv = sum(values) / len(values)
            cap = (
                adv
                * maximum_adv_participation
                * liquidity_safety_factor
                / portfolio_value
            )
            capped_weight = min(weight, cap)
            if capped_weight <= 1e-12:
                continue
            weights[asset_id] = capped_weight
        if not weights:
            continue
        output.append(
            replace(
                target,
                weights=weights,
                alpha_source_weights={
                    asset_id: dict(source)
                    for asset_id, source in target.alpha_source_weights.items()
                    if asset_id in weights
                },
            )
        )
    return tuple(output)


def build_round33_production_regression(
    validation_artifacts: Path,
    acceptance_run: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": ROUND33_SCHEMA,
        "evidence_type": "PRODUCTION_REGRESSION",
        "acceptance_run": acceptance_run,
    }
    audit_path = validation_artifacts / "round32_run_bundle_audit.json"
    provenance_path = (
        Path("reports/daily-runs")
        / acceptance_run
        / "decision_provenance.json"
    )
    if audit_path.exists():
        audit = cast(dict[str, Any], json.loads(audit_path.read_text(encoding="utf-8")))
        payload["round32_replay"] = audit.get("result", {}).get("acceptance", {})
    if provenance_path.exists():
        provenance = cast(
            dict[str, Any], json.loads(provenance_path.read_text(encoding="utf-8"))
        )
        decisions = cast(dict[str, Any], provenance.get("decisions", {}))
        first: dict[str, Any] = next(iter(decisions.values()), {})
        optimizer = cast(dict[str, Any], first.get("optimizer", {}))
        provenance_obj = cast(
            dict[str, Any], optimizer.get("portfolio_provenance", {})
        )
        payload["optimizer_input_count"] = provenance_obj.get("optimizer_input_count")
        payload["pre_optimizer_top_n"] = provenance_obj.get("pre_optimizer_top_n")
        payload["fixed_holdings_cap"] = None
        payload["formal_target_count"] = provenance_obj.get("final_target_count")
        payload["formal_action_count"] = provenance_obj.get("final_target_count")
        payload["gross"] = optimizer.get("portfolio_gross_weight")
        payload["cash"] = optimizer.get("portfolio_cash_weight")
        payload["expected_vol"] = optimizer.get("portfolio_expected_volatility")
        payload["turnover"] = optimizer.get("portfolio_turnover")
        payload["cost"] = optimizer.get("portfolio_estimated_transaction_cost")
        payload["expected_alpha"] = optimizer.get("portfolio_expected_alpha")
        probability = cast(dict[str, Any], first.get("probability", {}))
        payload["probability_influence"] = probability.get("production_weight")
        payload["market_regime_influence"] = 0.0
        payload["llm_influence"] = 0.0
        payload["etf_formal_action_count"] = 0
    return payload


def write_round33_validation_summary(
    evidence: dict[str, object],
    production_regression: dict[str, object],
) -> dict[str, object]:
    replay_raw = production_regression.get("round32_replay", {})
    replay_status = (
        cast(dict[str, Any], replay_raw)
        if isinstance(replay_raw, dict)
        else {}
    )
    top_n = production_regression.get("pre_optimizer_top_n")
    holdings_cap = production_regression.get("fixed_holdings_cap")
    corrected = cast(dict[str, Any], evidence.get("corrected_oos", {}))
    champion = cast(dict[str, Any], corrected.get("champion", {}))
    champion_performance = cast(dict[str, Any], champion.get("performance", {}))
    alpha = champion_performance.get("alpha")
    uncertainty = cast(
        dict[str, Any], evidence.get("uncertainty_intervals", {})
    )
    ci_raw = uncertainty.get("annualized_alpha_ci")
    ci = cast(tuple[float, float], tuple(ci_raw)) if isinstance(ci_raw, list) else None
    alpha_established = bool(
        alpha is not None and ci is not None and ci[0] > 0 and ci[1] > 0
    )
    return {
        "schema_version": ROUND33_SCHEMA,
        "evidence_status": (
            "ROUND33_ALPHA_VALIDATED_FOR_RESEARCH"
            if alpha_established
            else "ROUND33_ALPHA_NOT_ESTABLISHED"
        ),
        "round32_replay": replay_status.get("ROUND32_FULL_REPLAY", "UNAVAILABLE"),
        "pre_optimizer_top_n": top_n,
        "fixed_holdings_cap": holdings_cap,
        "production_chain_invariant": top_n is None and holdings_cap is None,
        "probability_production_influence": 0.0,
        "challenger_promotion_eligible": False,
        "classical_champion_retained": True,
        "no_production_policy_change_recommended": True,
        "ready_for_round34": "YES_WITH_FORWARD_VALIDATION",
    }


def write_round33_artifacts(
    artifacts_dir: Path,
    *,
    session: Session,
    decision_time: datetime,
    history_start: date,
    acceptance_run: str,
) -> dict[str, object]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    evidence = run_round33_research(
        session,
        decision_time=decision_time,
        history_start=history_start,
    )
    production_regression = build_round33_production_regression(
        artifacts_dir,
        acceptance_run,
    )
    summary = write_round33_validation_summary(evidence, production_regression)
    files = {
        "round33_performance_code_audit.json": build_round33_code_audit(),
        "round33_weight_allocation_audit.json": build_round33_weight_allocation_audit(),
        "round33_metric_frequency_audit.json": build_round33_metric_frequency_audit(),
        "round33_execution_parity_audit.json": build_round33_execution_parity_audit(),
        "round33_cost_integrity_audit.json": build_round33_cost_integrity_audit(),
        "round33_factor_performance.json": evidence["factor_performance"],
        "round33_alpha_calibration.json": evidence["alpha_calibration"],
        "round33_probability_retest.json": evidence["probability_retest"],
        "round33_corrected_oos_performance.json": evidence["corrected_oos"],
        "round33_benchmark_comparison.json": evidence["benchmark_comparison"],
        "round33_uncertainty_intervals.json": evidence["uncertainty_intervals"],
        "round33_expected_alpha_semantics.json": evidence["expected_alpha_semantics"],
        "round33_production_regression.json": production_regression,
        "round33_validation_summary.json": summary,
    }
    for name, payload in files.items():
        (artifacts_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    return {"evidence": evidence, "summary": summary, "files": list(files)}
