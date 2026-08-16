"""ROUND33 corrected research performance primitives.

This module is research-only.  It never changes the production optimizer or
promotes a challenger automatically.  It exists to make historical evidence
use production-style execution, explicit frequencies, real prior ADV, and
explicit survivorship/PIT boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import HuberRegressor, Ridge  # type: ignore[import-untyped]

from personal_alpha_terminal.backtest.schemas import BacktestBar, UniversePoint
from personal_alpha_terminal.core.market_time import market_close_utc
from personal_alpha_terminal.quant_engine.backtest.production import (
    BacktestTarget,
    ProductionBacktestConfig,
    ProductionBacktestDataset,
    ProductionBacktestEngine,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.round4_research import (
    allocate_positive_alpha_weights,
)

FEATURE_COLUMNS: tuple[str, ...] = (
    "momentum_12_1__normalized",
    "trend_slope__normalized",
    "volatility__normalized",
)


class ResearchExecutionPolicy(StrEnum):
    NEXT_SESSION_OPEN_TO_HORIZON_CLOSE = "NEXT_SESSION_OPEN_TO_HORIZON_CLOSE"


@dataclass(frozen=True, slots=True)
class CorrectedForwardReturn:
    symbol: str
    as_of_date: date
    entry_date: date
    exit_date: date
    absolute_return: float
    benchmark_return: float
    benchmark_relative_return: float


def build_corrected_labeled_panel(
    price_panel: pd.DataFrame,
    factor_panel: pd.DataFrame,
    *,
    benchmark: str,
    horizon: int = 21,
    execution_policy: ResearchExecutionPolicy = (
        ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE
    ),
) -> pd.DataFrame:
    """Join factor rows to next-session-open -> horizon-close returns."""

    if execution_policy is not ResearchExecutionPolicy.NEXT_SESSION_OPEN_TO_HORIZON_CLOSE:
        raise ValueError(f"unsupported research execution policy: {execution_policy}")
    required = {"trade_date", "ticker", "open", "close", "volume"}
    missing = required - set(price_panel.columns)
    if missing:
        raise ValueError(f"price panel misses columns: {sorted(missing)}")
    panel = price_panel.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise").dt.date
    calendar = tuple(sorted(set(panel["trade_date"])))
    session_index = {session: index for index, session in enumerate(calendar)}
    closes = panel.pivot_table(
        index="trade_date",
        columns="ticker",
        values="close",
        aggfunc="last",
    ).reindex(calendar).sort_index()
    opens = panel.pivot_table(
        index="trade_date",
        columns="ticker",
        values="open",
        aggfunc="last",
    ).reindex(calendar).sort_index()
    if benchmark not in closes.columns or benchmark not in opens.columns:
        raise ValueError(f"benchmark {benchmark} is missing from the price panel")
    rows: list[dict[str, object]] = []
    for record in factor_panel.itertuples(index=False):
        signal_date = pd.to_datetime(record.as_of_date, errors="raise").date()
        signal_index = session_index.get(signal_date)
        if signal_index is None:
            continue
        entry_index = signal_index + 1
        exit_index = signal_index + horizon
        if exit_index >= len(calendar) or entry_index >= len(calendar):
            continue
        symbol = str(record.ticker)
        entry_open = float(opens.iloc[entry_index][symbol])
        exit_close = float(closes.iloc[exit_index][symbol])
        benchmark_entry_open = float(opens.iloc[entry_index][benchmark])
        benchmark_exit_close = float(closes.iloc[exit_index][benchmark])
        if not all(
            isfinite(value) and value > 0
            for value in (
                entry_open,
                exit_close,
                benchmark_entry_open,
                benchmark_exit_close,
            )
        ):
            continue
        absolute = exit_close / entry_open - 1.0
        benchmark_return = benchmark_exit_close / benchmark_entry_open - 1.0
        row: dict[str, object] = {
            column: getattr(record, column)
            for column in factor_panel.columns
            if hasattr(record, column)
        }
        row.update(
            {
                "as_of_date": signal_date,
                "entry_date": calendar[entry_index],
                "exit_date": calendar[exit_index],
                "forward_return": absolute - benchmark_return,
                "absolute_forward_return": absolute,
                "benchmark_return": benchmark_return,
                "outcome": int(absolute - benchmark_return > 0),
                "horizon": horizon,
                "execution_policy": execution_policy.value,
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def allocate_research_targets(
    factor_panel: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    dates: tuple[date, ...],
    alpha_column: str = "expected_alpha",
    top_fraction: float = 0.20,
    maximum_weight: float = 0.12,
    minimum_cash: float = 0.10,
    model_version: str,
    data_version: str,
    validation_status: str = "RESEARCH_SURVIVORSHIP_LIMITED",
    oos_validation_id: str = "ROUND33_RESEARCH_SURVIVORSHIP_LIMITED",
    parameter_lock_fingerprint: str = "round33-research-lock",
    alpha_source: str = "USAdaptiveAlphaCoreV1",
    portfolio_value: float = 1_000_000.0,
    maximum_adv_participation: float = 0.02,
    liquidity_safety_factor: float = 0.25,
) -> tuple[BacktestTarget, ...]:
    """Build frozen research targets using the corrected allocation invariant."""

    calendar = tuple(sorted({value.date() for value in pd.to_datetime(price_panel["trade_date"])}))
    session_index = {session: index for index, session in enumerate(calendar)}
    symbol_to_asset = _symbol_asset_ids(tuple(price_panel["ticker"].dropna().unique()))
    dollar_panel = price_panel.copy()
    dollar_panel["trade_date"] = pd.to_datetime(
        dollar_panel["trade_date"], errors="raise"
    ).dt.date
    dollar_panel["dollar_volume"] = (
        pd.to_numeric(dollar_panel["close"], errors="coerce")
        * pd.to_numeric(dollar_panel["volume"], errors="coerce")
    )
    targets: list[BacktestTarget] = []
    for day in dates:
        day_rows = factor_panel[pd.to_datetime(factor_panel["as_of_date"]).dt.date == day]
        if day_rows.empty:
            continue
        allocation = allocate_positive_alpha_weights(
            day_rows,
            alpha_column=alpha_column,
            top_fraction=top_fraction,
            maximum_weight=maximum_weight,
            minimum_cash=minimum_cash,
        )
        if not allocation.weights:
            continue
        signal_index = session_index.get(day)
        if signal_index is None or signal_index + 1 >= len(calendar):
            continue
        execution_date = calendar[signal_index + 1]
        prior_dollar = dollar_panel[dollar_panel["trade_date"] < execution_date]
        signal_time = market_close_utc(day, "US") + timedelta(minutes=30)
        weights: dict[int, float] = {}
        for symbol, weight in allocation.weights:
            observations = prior_dollar.loc[
                prior_dollar["ticker"] == symbol, "dollar_volume"
            ].dropna().tail(20)
            if len(observations) < 10:
                continue
            adv = float(observations.mean())
            if not isfinite(adv) or adv <= 0:
                continue
            liquidity_cap = (
                adv
                * maximum_adv_participation
                * liquidity_safety_factor
                / portfolio_value
            )
            capped_weight = min(weight, liquidity_cap)
            if capped_weight <= 1e-12:
                continue
            weights[symbol_to_asset[symbol]] = capped_weight
        if not weights:
            continue
        targets.append(
            BacktestTarget(
                signal_time=signal_time,
                earliest_execution_date=calendar[signal_index + 1],
                weights=weights,
                universe_snapshot_id=1,
                data_version=data_version,
                model_version=model_version,
                validation_status=validation_status,
                alpha_source_weights={
                    asset_id: {alpha_source: 1.0} for asset_id in weights
                },
                parameter_lock_fingerprint=parameter_lock_fingerprint,
                oos_validation_id=oos_validation_id,
            )
        )
    return tuple(targets)


def build_research_backtest_dataset(
    price_panel: pd.DataFrame,
    *,
    data_version: str,
    source: str = "round33-research",
    provider: str = "round33-research",
) -> tuple[ProductionBacktestDataset, dict[int, str], dict[str, int]]:
    """Build a research-only raw-OHLC dataset for ProductionBacktestEngine."""

    required = {
        "trade_date",
        "ticker",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "available_time",
    }
    missing = required - set(price_panel.columns)
    if missing:
        raise ValueError(f"research dataset panel misses columns: {sorted(missing)}")
    panel = price_panel.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise").dt.date
    calendar = tuple(sorted(set(panel["trade_date"])))
    symbols = tuple(panel["ticker"].dropna().unique())
    symbol_to_asset = _symbol_asset_ids(symbols)
    asset_to_symbol = {value: key for key, value in symbol_to_asset.items()}
    bars: list[BacktestBar] = []
    for record in panel.itertuples(index=False):
        trade_date = record.trade_date
        if not hasattr(record, "trade_date"):
            continue
        symbol = str(record.ticker)
        asset_id = symbol_to_asset[symbol]
        event_time = market_close_utc(trade_date, "US")
        available_time = _as_aware_datetime(getattr(record, "available_time", None))
        if available_time is None or available_time < event_time:
            available_time = event_time + timedelta(minutes=1)
        ingested_time = _as_aware_datetime(getattr(record, "ingested_at", None))
        if ingested_time is None or ingested_time < available_time:
            ingested_time = available_time + timedelta(minutes=1)
        open_tradable = True
        bars.append(
            BacktestBar(
                asset_id=asset_id,
                symbol=symbol,
                market="US",
                trade_date=trade_date,
                open=float(record.open),
                high=float(record.high),
                low=float(record.low),
                close=float(record.close),
                adjusted_close=None,
                volume=int(record.volume) if record.volume is not None else None,
                source=str(getattr(record, "source", source)),
                adjustment_method="RAW_OHLCV",
                provider=str(getattr(record, "provider", provider)),
                event_time=event_time,
                available_time=available_time,
                ingested_time=ingested_time,
                open_tradable=open_tradable,
            )
        )
    universe = UniversePoint(
        snapshot_id=1,
        as_of_date=calendar[0],
        available_at=datetime.combine(calendar[0], time(20), tzinfo=UTC),
        asset_ids=frozenset(symbol_to_asset.values()),
        source="PRICE_BASED_RANKING:CURRENT_DIRECTORY_RESEARCH",
    )
    dataset = ProductionBacktestDataset(
        bars=tuple(bars),
        calendar=calendar,
        calendar_source="round33-research-inferred-calendar",
        universe_timeline=(universe,),
        corporate_actions=(),
        corporate_action_ledger_certified=False,
        universe_certified=False,
        data_version=data_version,
        market="US",
        execution_price_policy="RAW_OHLC",
        return_policy="RESEARCH_RAW_OHLC_CORPORATE_ACTION_LIMITED",
    )
    return (
        dataset,
        {asset_id: symbol for asset_id, symbol in asset_to_symbol.items()},
        symbol_to_asset,
    )


def run_research_parity_backtest(
    dataset: ProductionBacktestDataset,
    targets: tuple[BacktestTarget, ...],
    *,
    benchmark_returns: tuple[tuple[date, float], ...],
    sectors: dict[int, str] | None = None,
    config: ProductionBacktestConfig | None = None,
    cost_config: TransactionCostConfig | None = None,
) -> Any:
    """Run the production accounting engine in explicit research mode."""

    from personal_alpha_terminal.quant_engine.costs import TransactionCostModel

    engine = ProductionBacktestEngine(
        TransactionCostModel(cost_config or TransactionCostConfig()),
        research_mode=True,
    )
    effective = config or ProductionBacktestConfig(
        benchmark_returns=benchmark_returns,
        minimum_sessions=20,
        git_commit="ROUND33_RESEARCH_SURVIVORSHIP_LIMITED",
    )
    return engine.run(
        dataset,
        targets,
        effective,
        sectors=sectors or {
            asset_id: "UNCLASSIFIED"
            for asset_id in {item.asset_id for item in dataset.bars}
        },
    )


@dataclass(frozen=True, slots=True)
class AlphaCalibrationSpec:
    method: str
    ridge_alpha: float = 1.0
    shrinkage: float = 0.50
    minimum_dates: int = 6
    embargo_sessions: int = 21

    def __post_init__(self) -> None:
        if self.method not in {
            "fixed_engineering",
            "equal_weight_rank",
            "nonnegative_ridge",
            "robust_linear",
            "ic_weighted",
            "regularized_ic_weighted",
        }:
            raise ValueError(f"unsupported alpha calibration method: {self.method}")
        if self.ridge_alpha <= 0 or not 0 <= self.shrinkage <= 1:
            raise ValueError("ridge alpha and shrinkage must be valid")


@dataclass(frozen=True, slots=True)
class AlphaCalibrationResult:
    method: str
    train_period: tuple[date, date]
    calibration_period: tuple[date, date]
    oos_period: tuple[date, date]
    coefficients: dict[str, float]
    oos_row_count: int
    oos_date_count: int
    calibration_status: str
    promotion_eligible: bool


def calibrate_alpha(
    labeled_panel: pd.DataFrame,
    *,
    session_dates: tuple[date, ...],
    spec: AlphaCalibrationSpec,
) -> tuple[AlphaCalibrationResult, pd.DataFrame]:
    """Fit challenger coefficients on train+calibration and lock the OOS panel."""

    if labeled_panel.empty:
        raise ValueError("cannot calibrate alpha on an empty panel")
    dates = tuple(sorted(set(labeled_panel["as_of_date"])))
    if len(dates) < spec.minimum_dates:
        raise ValueError("alpha calibration requires more independent dates")
    train_end, calibration, oos = _purged_splits(
        dates,
        train_ratio=0.5,
        calibration_ratio=0.25,
        embargo_sessions=spec.embargo_sessions,
    )
    train = labeled_panel[
        (labeled_panel["as_of_date"] >= train_end[0])
        & (labeled_panel["as_of_date"] <= train_end[1])
    ]
    calibration_panel = labeled_panel[
        (labeled_panel["as_of_date"] >= calibration[0])
        & (labeled_panel["as_of_date"] <= calibration[1])
    ]
    fit_panel = pd.concat([train, calibration_panel], ignore_index=True)
    oos_panel = labeled_panel[
        (labeled_panel["as_of_date"] >= oos[0])
        & (labeled_panel["as_of_date"] <= oos[1])
    ].copy()
    if oos_panel.empty:
        raise ValueError("locked OOS panel is empty")
    score, coefficients = _calibrated_score(
        fit_panel,
        oos_panel,
        spec=spec,
    )
    oos_panel["calibrated_score"] = score
    result = AlphaCalibrationResult(
        method=spec.method,
        train_period=train_end,
        calibration_period=calibration,
        oos_period=oos,
        coefficients=coefficients,
        oos_row_count=len(oos_panel),
        oos_date_count=len(set(oos_panel["as_of_date"])),
        calibration_status="UNCALIBRATED_ENGINEERING_RETURN_PROXY"
        if spec.method == "fixed_engineering"
        else "LOCKED_OOS_RESEARCH_CALIBRATION",
        promotion_eligible=False,
    )
    return result, oos_panel


def _purged_splits(
    dates: tuple[date, ...],
    *,
    train_ratio: float,
    calibration_ratio: float,
    embargo_sessions: int,
) -> tuple[tuple[date, date], tuple[date, date], tuple[date, date]]:
    n = len(dates)
    if n < 4:
        raise ValueError("too few dates for purged splits")
    train_end = max(0, min(n - 3, int(n * train_ratio) - 1))
    gap = max(1, int(round(embargo_sessions / 21)))
    calibration_start = min(n - 2, train_end + gap)
    calibration_end = min(
        n - gap - 1,
        max(calibration_start, int(n * (train_ratio + calibration_ratio)) - 1),
    )
    oos_start = min(n - 1, calibration_end + gap)
    if calibration_start <= train_end or oos_start <= calibration_end:
        raise ValueError("purged temporal split leaves no valid OOS window")
    return (
        (dates[0], dates[train_end]),
        (dates[calibration_start], dates[calibration_end]),
        (dates[oos_start], dates[-1]),
    )


def _calibrated_score(
    fit_panel: pd.DataFrame,
    oos_panel: pd.DataFrame,
    *,
    spec: AlphaCalibrationSpec,
) -> tuple[np.ndarray, dict[str, float]]:
    method = spec.method
    if method == "fixed_engineering":
        return (
            pd.to_numeric(oos_panel["expected_alpha"], errors="coerce").to_numpy(dtype=float),
            {
                "momentum_coefficient": 0.006,
                "trend_coefficient": 0.003,
                "low_volatility_coefficient": 0.002,
            },
        )
    if method == "equal_weight_rank":
        features = _normalize_features(oos_panel)
        return features.mean(axis=1).to_numpy(dtype=float), {
            feature: 1.0 / len(FEATURE_COLUMNS) for feature in FEATURE_COLUMNS
        }
    if method in {"nonnegative_ridge", "robust_linear"}:
        x_fit, y_fit = _fit_matrix(fit_panel)
        x_oos, _ = _fit_matrix(oos_panel)
        if method == "nonnegative_ridge":
            model: Any = Ridge(alpha=spec.ridge_alpha, positive=True, fit_intercept=True)
        else:
            model = HuberRegressor(alpha=spec.ridge_alpha, max_iter=1000)
        model.fit(x_fit, y_fit)
        coefficients = {
            feature: float(model.coef_[index])
            for index, feature in enumerate(FEATURE_COLUMNS)
        }
        coefficients["intercept"] = float(model.intercept_)
        return model.predict(x_oos), coefficients
    ic = _ic_weights(fit_panel)
    features = _normalize_features(oos_panel)
    if method == "ic_weighted":
        weights = np.array([ic.get(feature, 0.0) for feature in FEATURE_COLUMNS], dtype=float)
    else:
        equal = np.full(len(FEATURE_COLUMNS), 1.0 / len(FEATURE_COLUMNS))
        ic_vector = np.array([ic.get(feature, 0.0) for feature in FEATURE_COLUMNS], dtype=float)
        weights = (1.0 - spec.shrinkage) * ic_vector + spec.shrinkage * equal
    if np.allclose(weights, 0.0):
        weights = np.full(len(FEATURE_COLUMNS), 1.0 / len(FEATURE_COLUMNS))
    score = features.to_numpy(dtype=float) @ weights
    coefficients = {
        feature: float(weights[index]) for index, feature in enumerate(FEATURE_COLUMNS)
    }
    return score, coefficients


def _normalize_features(panel: pd.DataFrame) -> pd.DataFrame:
    features = panel[list(FEATURE_COLUMNS)].replace([np.inf, -np.inf], np.nan)
    ranked = features.rank(pct=True)
    return ranked.fillna(0.0)


def _fit_matrix(panel: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    clean = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[*FEATURE_COLUMNS, "forward_return"]
    )
    return (
        clean[list(FEATURE_COLUMNS)].to_numpy(dtype=float),
        clean["forward_return"].to_numpy(dtype=float),
    )


def _ic_weights(panel: pd.DataFrame) -> dict[str, float]:
    output: dict[str, float] = {}
    for feature in FEATURE_COLUMNS:
        values: list[float] = []
        for _as_of, group in panel.groupby("as_of_date", sort=True):
            clean = group.replace([np.inf, -np.inf], np.nan).dropna(
                subset=[feature, "forward_return"]
            )
            if (
                len(clean) < 5
                or clean[feature].nunique() < 2
                or clean["forward_return"].nunique() < 2
            ):
                continue
            statistic = spearmanr(
                clean[feature].to_numpy(dtype=float),
                clean["forward_return"].to_numpy(dtype=float),
            ).statistic
            if isfinite(statistic):
                values.append(float(statistic))
        output[feature] = float(np.mean(values)) if values else 0.0
    return output


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    point_estimate: float
    lower_95: float
    upper_95: float
    bootstrap_count: int
    date_count: int
    block_length_used: int
    sufficient_independent_dates: bool

    def document(self) -> dict[str, object]:
        return {
            "point_estimate": self.point_estimate,
            "ci95": [self.lower_95, self.upper_95],
            "bootstrap_count": self.bootstrap_count,
            "date_count": self.date_count,
            "block_length_used": self.block_length_used,
            "sufficient_independent_dates": self.sufficient_independent_dates,
        }


def block_bootstrap_interval(
    date_values: dict[date, float],
    *,
    block_length: int = 21,
    bootstrap_count: int = 2000,
    seed: int = 33,
) -> BootstrapInterval:
    """Block bootstrap by decision date for overlapping-horizon evidence."""

    if not date_values:
        raise ValueError("block bootstrap requires date-level values")
    ordered = sorted(date_values)
    sufficient = len(ordered) >= block_length
    effective_block_length = max(1, min(block_length, len(ordered)))
    if len(ordered) < block_length:
        effective_block_length = 1
    blocks = [
        ordered[index : index + effective_block_length]
        for index in range(0, len(ordered), effective_block_length)
    ]
    if not blocks:
        raise ValueError("block bootstrap blocks are empty")
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(bootstrap_count):
        selected_blocks = [blocks[index] for index in rng.integers(0, len(blocks), len(blocks))]
        values = [date_values[item] for block in selected_blocks for item in block]
        samples.append(float(np.mean(values)) if values else 0.0)
    point = float(np.mean(list(date_values.values())))
    lower = float(np.percentile(samples, 2.5))
    upper = float(np.percentile(samples, 97.5))
    return BootstrapInterval(
        point,
        lower,
        upper,
        bootstrap_count,
        len(ordered),
        effective_block_length,
        sufficient,
    )


def _symbol_asset_ids(symbols: tuple[str, ...]) -> dict[str, int]:
    output: dict[str, int] = {}
    for symbol in symbols:
        digest = sha256(symbol.encode("utf-8")).digest()[:8]
        asset_id = int.from_bytes(digest, "big") % 1_000_000_000 + 1
        while asset_id in output.values():
            asset_id += 1
        output[symbol] = asset_id
    return output


def _as_aware_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, utc=True)
    if pd.isna(parsed):
        return None
    return cast(datetime, parsed.to_pydatetime())
