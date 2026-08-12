"""ROUND 4 research evidence: broad cross-section, probability calibration, A/B.

This module is deliberately research-only.  It reads the same real SQLite price
and security-master rows used by daily production, but it does not promote the
current-directory price-based universe to a survivorship-safe historical
certification.  Every artifact records ``SURVIVORSHIP_LIMITED`` and
``PRICE_BASED_RANKING`` unless upstream certified data proves otherwise.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.data.us_market.broad_universe import (
    BroadUniverseEligibility,
    EligibilityRules,
)
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig, TransactionCostModel
from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.factors.features import compute_price_features
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1Config,
)


@dataclass(frozen=True, slots=True)
class ResearchIdentity:
    strategy_id: str
    strategy_version: str
    model_id: str
    feature_schema_hash: str
    factor_identity: str
    universe_identity: str
    benchmark: str
    holding_horizon: int
    transaction_cost_assumption: str
    data_version: str
    config_hash: str

    @property
    def research_hash(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    lower_bound: float
    upper_bound: float
    predicted: float
    actual: float
    count: int


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationEvidence:
    identity: ResearchIdentity
    training_period: tuple[date, date]
    calibration_period: tuple[date, date]
    oos_period: tuple[date, date]
    training_samples: int
    calibration_samples: int
    oos_samples: int
    base_rate: float
    brier_score: float
    baseline_brier_score: float
    log_loss: float
    expected_calibration_error: float
    roc_auc: float
    reliability_buckets: tuple[ReliabilityBucket, ...]
    created_at: datetime
    artifact_hash: str

    def document(self) -> dict[str, object]:
        payload = {
            "identity": asdict(self.identity),
            "training_period": [item.isoformat() for item in self.training_period],
            "calibration_period": [item.isoformat() for item in self.calibration_period],
            "oos_period": [item.isoformat() for item in self.oos_period],
            "training_samples": self.training_samples,
            "calibration_samples": self.calibration_samples,
            "oos_samples": self.oos_samples,
            "base_rate": self.base_rate,
            "brier_score": self.brier_score,
            "baseline_brier_score": self.baseline_brier_score,
            "log_loss": self.log_loss,
            "expected_calibration_error": self.expected_calibration_error,
            "roc_auc": self.roc_auc,
            "reliability_buckets": [asdict(item) for item in self.reliability_buckets],
            "created_at": self.created_at.isoformat(),
            "artifact_hash": self.artifact_hash,
        }
        return cast(
            dict[str, object],
            json.loads(json.dumps(payload, sort_keys=True)),
        )


@dataclass(frozen=True, slots=True)
class FactorDiagnostics:
    factor: str
    mean: float | None
    std: float | None
    p01: float | None
    p50: float | None
    p99: float | None
    coverage: float
    missing_ratio: float
    rank_ic: float | None
    pearson_ic: float | None
    positive_ic_ratio: float | None
    ic_ir: float | None
    top_bottom_spread: float | None
    turnover: float | None
    constant: bool


@dataclass(frozen=True, slots=True)
class PortfolioAB:
    classical_net_return: float
    probability_net_return: float
    classical_sharpe: float | None
    probability_sharpe: float | None
    classical_drawdown: float | None
    probability_drawdown: float | None
    probability_change_count: int
    probability_target_change_count: int
    probability_max_multiplier: float
    probability_min_multiplier: float
    turnover_classical: float
    turnover_probability: float
    total_cost_classical: float
    total_cost_probability: float


@dataclass(frozen=True, slots=True)
class Round4ResearchReport:
    run_id: str
    created_at: datetime
    universe: dict[str, int]
    eligibility_hash: str
    factor_diagnostics: tuple[FactorDiagnostics, ...]
    factor_correlations: dict[str, object]
    calibration: ProbabilityCalibrationEvidence | None
    probability_snapshot: dict[str, object] | None
    portfolio_ab: PortfolioAB | None
    walk_forward: dict[str, object]
    benchmark: dict[str, float | None]
    survivors: str
    blockers: tuple[str, ...]
    report_hash: str

    def document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "universe": self.universe,
            "eligibility_hash": self.eligibility_hash,
            "factor_diagnostics": [asdict(item) for item in self.factor_diagnostics],
            "factor_correlations": self.factor_correlations,
            "calibration": (
                self.calibration.document() if self.calibration is not None else None
            ),
            "probability_snapshot": self.probability_snapshot,
            "portfolio_ab": asdict(self.portfolio_ab) if self.portfolio_ab else None,
            "walk_forward": self.walk_forward,
            "benchmark": self.benchmark,
            "survivors": self.survivors,
            "blockers": list(self.blockers),
            "report_hash": self.report_hash,
        }


def load_price_panel(
    session: Session,
    *,
    decision_time: datetime,
    history_start: date,
    minimum_history: int = 252,
    horizon: int = 21,
    reference_symbols: tuple[str, ...] = ("SPY", "QQQ"),
) -> pd.DataFrame:
    """Load PIT raw OHLCV rows for stocks with enough pre-decision history."""

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
    if not stocks:
        raise ValueError("no broad US stocks have sufficient PIT price history")
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
    rows: list[dict[str, object]] = []
    for stock in (*stocks, *references):
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
        role = "alpha" if stock in stocks else "reference"
        for price in prices:
            if price.volume is None or price.close <= 0:
                continue
            available = cast(datetime, price.available_time)
            rows.append(
                {
                    "permanent_security_id": stock.canonical_code,
                    "ticker": stock.symbol,
                    "exchange": stock.exchange,
                    "trade_date": price.trade_date,
                    "available_time": available,
                    "close": float(price.close),
                    "volume": float(price.volume),
                    "role": role,
                }
            )
    return pd.DataFrame(rows)


def rebalance_dates(
    price_panel: pd.DataFrame,
    *,
    end_date: date,
    horizon: int = 21,
) -> tuple[date, ...]:
    dates = sorted(
        {
            value.date()
            for value in pd.to_datetime(price_panel["trade_date"], errors="raise")
            if value.date() <= end_date
        }
    )
    return tuple(dates[index] for index in range(horizon, len(dates), horizon))


def build_factor_panel(
    price_panel: pd.DataFrame,
    *,
    dates: tuple[date, ...],
    config: USAdaptiveAlphaCoreV1Config | None = None,
    rules: EligibilityRules | None = None,
) -> pd.DataFrame:
    configured = config or USAdaptiveAlphaCoreV1Config()
    configured_rules = rules or EligibilityRules()
    specs = (
        FactorSpec(
            "momentum_12_1",
            "high",
            minimum_observations=5,
            sector_neutral=True,
            size_neutral=True,
        ),
        FactorSpec(
            "trend_slope",
            "high",
            minimum_observations=5,
            sector_neutral=True,
            size_neutral=True,
        ),
        FactorSpec(
            "volatility",
            "low",
            minimum_observations=5,
            sector_neutral=True,
            size_neutral=True,
        ),
    )
    alpha_panel = (
        price_panel[price_panel["role"] == "alpha"]
        if "role" in price_panel
        else price_panel
    )
    frames: list[pd.DataFrame] = []
    for day in dates:
        cutoff = datetime.combine(day, time(20, 30), tzinfo=UTC)
        features = compute_price_features(
            alpha_panel,
            information_cutoff=cutoff,
            momentum_lookback=configured.momentum_lookback,
            momentum_skip=configured.momentum_skip,
            trend_window=configured.trend_window,
            volatility_window=configured.volatility_window,
        )
        if features.empty:
            continue
        features["sector"] = "UNKNOWN"
        features["market_cap"] = np.nan
        features["available_at"] = pd.to_datetime(
            features["available_at"], utc=True, errors="raise"
        )
        processed = process_cross_section(
            features,
            specs,
            as_of=cutoff,
            minimum_required_factors=3,
            allow_degraded_neutralization=True,
        )
        frame = processed.frame.copy()
        frame["as_of_date"] = day
        frame["composite"] = (
            frame["momentum_12_1__normalized"]
            + frame["trend_slope__normalized"]
            + frame["volatility__normalized"]
        ) / 3.0
        frame["expected_alpha"] = (
            frame["momentum_12_1__normalized"] * configured.momentum_coefficient
            + frame["trend_slope__normalized"] * configured.trend_coefficient
            + frame["volatility__normalized"] * configured.low_volatility_coefficient
        )
        frame["eligible"] = frame["factor_coverage"] >= 1.0
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    panel["rank"] = (
        panel.groupby("as_of_date")["expected_alpha"].rank(
            method="first", ascending=False
        )
    )
    panel["rules_fingerprint"] = configured_rules.fingerprint
    return panel


def build_labeled_panel(
    price_panel: pd.DataFrame,
    factor_panel: pd.DataFrame,
    *,
    benchmark: str,
    horizon: int = 21,
    threshold: float = 0.0,
) -> pd.DataFrame:
    levels = price_panel.pivot_table(
        index="trade_date",
        columns="ticker",
        values="close",
        aggfunc="last",
    ).sort_index()
    levels = levels.replace([np.inf, -np.inf], np.nan)
    if benchmark not in levels:
        raise ValueError(f"benchmark {benchmark} is missing from the price panel")
    benchmark_future = levels[benchmark].shift(-horizon) / levels[benchmark].shift(-1) - 1
    symbol_future = levels.shift(-horizon) / levels.shift(-1) - 1
    relative_future = symbol_future.sub(benchmark_future, axis=0)
    future = relative_future.reset_index().melt(
        id_vars="trade_date",
        var_name="ticker",
        value_name="forward_return",
    )
    future["as_of_date"] = pd.to_datetime(future["trade_date"], errors="raise").dt.date
    out = factor_panel.merge(
        future,
        left_on=["as_of_date", "ticker"],
        right_on=["as_of_date", "ticker"],
        how="inner",
    )
    out["forward_return"] = pd.to_numeric(out["forward_return"], errors="coerce")
    out = out.dropna(subset=["forward_return"]).copy()
    out["outcome"] = (out["forward_return"] > threshold).astype(int)
    out = out.dropna(subset=["expected_alpha", "forward_return"]).copy()
    out["horizon"] = horizon
    return out


def temporal_splits(
    dates: tuple[date, ...],
    *,
    train_ratio: float = 0.50,
    calibration_ratio: float = 0.25,
) -> tuple[tuple[date, date], tuple[date, date], tuple[date, date]]:
    if not dates or train_ratio <= 0 or calibration_ratio <= 0:
        raise ValueError("temporal split requires valid positive ratios")
    if train_ratio + calibration_ratio >= 1.0:
        raise ValueError("temporal split must leave an OOS period")
    n = len(dates)
    train_end = max(0, min(n - 2, int(n * train_ratio)))
    calibration_end = max(train_end + 1, min(n - 1, int(n * (train_ratio + calibration_ratio))))
    return (
        (dates[0], dates[train_end]),
        (dates[train_end + 1], dates[calibration_end]),
        (dates[calibration_end + 1], dates[-1]),
    )


def train_probability_calibration(
    labeled_panel: pd.DataFrame,
    *,
    identity: ResearchIdentity,
    train_period: tuple[date, date],
    calibration_period: tuple[date, date],
    oos_period: tuple[date, date],
    created_at: datetime | None = None,
) -> ProbabilityCalibrationEvidence:
    feature_columns = (
        "momentum_12_1__normalized",
        "trend_slope__normalized",
        "volatility__normalized",
        "composite",
        "expected_alpha",
    )
    missing = set(feature_columns) - set(labeled_panel.columns)
    if missing:
        raise ValueError(f"probability panel misses features: {sorted(missing)}")
    observed = created_at or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("calibration created_at must be timezone-aware")
    panel = labeled_panel.copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel = panel.dropna(subset=[*feature_columns, "outcome"]).copy()
    train = panel[
        (panel["as_of_date"] >= train_period[0])
        & (panel["as_of_date"] <= train_period[1])
    ]
    calibration = panel[
        (panel["as_of_date"] >= calibration_period[0])
        & (panel["as_of_date"] <= calibration_period[1])
    ]
    oos = panel[
        (panel["as_of_date"] >= oos_period[0]) & (panel["as_of_date"] <= oos_period[1])
    ]
    if len(train) < 60 or len(calibration) < 30 or len(oos) < 30:
        raise ValueError(
            "probability calibration sample is insufficient for a legitimate temporal split"
        )
    if len(set(train["outcome"])) < 2 or len(set(oos["outcome"])) < 2:
        raise ValueError("probability calibration requires positive and negative labels")
    x_train = train[list(feature_columns)].to_numpy(dtype=float)
    y_train = train["outcome"].to_numpy(dtype=int)
    x_cal = calibration[list(feature_columns)].to_numpy(dtype=float)
    y_cal = calibration["outcome"].to_numpy(dtype=int)
    x_oos = oos[list(feature_columns)].to_numpy(dtype=float)
    y_oos = oos["outcome"].to_numpy(dtype=int)
    estimator = LogisticRegression(
        C=1.0,
        max_iter=1000,
        solver="liblinear",
        random_state=0,
    )
    estimator.fit(x_train, y_train)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(estimator.predict_proba(x_cal)[:, 1], y_cal)
    probabilities = calibrator.predict(estimator.predict_proba(x_oos)[:, 1])
    base_rate = float(y_oos.mean())
    brier = float(brier_score_loss(y_oos, probabilities))
    baseline_brier = float(brier_score_loss(y_oos, np.full(len(y_oos), base_rate)))
    loss = float(log_loss(y_oos, probabilities))
    auc = float(roc_auc_score(y_oos, probabilities))
    buckets, ece = _reliability_buckets(probabilities, y_oos)
    artifact_payload = {
        "identity": asdict(identity),
        "training_period": [item.isoformat() for item in train_period],
        "calibration_period": [item.isoformat() for item in calibration_period],
        "oos_period": [item.isoformat() for item in oos_period],
        "training_samples": len(train),
        "calibration_samples": len(calibration),
        "oos_samples": len(oos),
        "base_rate": base_rate,
        "brier_score": brier,
        "baseline_brier_score": baseline_brier,
        "log_loss": loss,
        "expected_calibration_error": ece,
        "roc_auc": auc,
        "reliability_buckets": [asdict(item) for item in buckets],
        "created_at": observed.isoformat(),
    }
    artifact_hash = fingerprint(artifact_payload)
    return ProbabilityCalibrationEvidence(
        identity=identity,
        training_period=train_period,
        calibration_period=calibration_period,
        oos_period=oos_period,
        training_samples=len(train),
        calibration_samples=len(calibration),
        oos_samples=len(oos),
        base_rate=base_rate,
        brier_score=brier,
        baseline_brier_score=baseline_brier,
        log_loss=loss,
        expected_calibration_error=ece,
        roc_auc=auc,
        reliability_buckets=tuple(buckets),
        created_at=observed,
        artifact_hash=artifact_hash,
    )


def train_probability_predictions(
    labeled_panel: pd.DataFrame,
    factor_panel: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    train_period: tuple[date, date],
    calibration_period: tuple[date, date],
    dates: tuple[date, ...],
) -> pd.DataFrame:
    panel = labeled_panel.copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    panel = panel.replace([np.inf, -np.inf], np.nan)
    train = panel[
        (panel["as_of_date"] >= train_period[0])
        & (panel["as_of_date"] <= train_period[1])
    ]
    calibration = panel[
        (panel["as_of_date"] >= calibration_period[0])
        & (panel["as_of_date"] <= calibration_period[1])
    ]
    estimator = LogisticRegression(
        C=1.0,
        max_iter=1000,
        solver="liblinear",
        random_state=0,
    )
    estimator.fit(
        train[list(feature_columns)].to_numpy(dtype=float),
        train["outcome"].to_numpy(dtype=int),
    )
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(
        estimator.predict_proba(calibration[list(feature_columns)].to_numpy(dtype=float))[:, 1],
        calibration["outcome"].to_numpy(dtype=int),
    )
    return probability_predictions(
        factor_panel,
        dates=dates,
        feature_columns=feature_columns,
        estimator=estimator,
        calibrator=calibrator,
    )


def apply_probability_adjustment(
    frame: pd.DataFrame,
    *,
    probability_column: str,
    base_alpha_column: str = "expected_alpha",
    maximum_multiplier: float = 0.25,
) -> pd.DataFrame:
    if probability_column not in frame:
        raise ValueError("probability column is missing")
    probabilities = pd.to_numeric(frame[probability_column], errors="coerce")
    if probabilities.between(0.0, 1.0).sum() != probabilities.notna().sum():
        raise ValueError("probability values must be in [0, 1]")
    multiplier = 1.0 + maximum_multiplier * (2.0 * probabilities - 1.0)
    multiplier = multiplier.clip(1.0 - maximum_multiplier, 1.0 + maximum_multiplier)
    frame = frame.copy()
    frame["probability_multiplier"] = multiplier
    frame["adjusted_alpha"] = (
        pd.to_numeric(frame[base_alpha_column], errors="coerce") * multiplier
    )
    return frame


def probability_predictions(
    factor_panel: pd.DataFrame,
    *,
    dates: tuple[date, ...],
    feature_columns: tuple[str, ...],
    estimator: Any,
    calibrator: Any | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in dates:
        day_rows = factor_panel[
            pd.to_datetime(factor_panel["as_of_date"], errors="raise").dt.date == day
        ]
        if day_rows.empty:
            continue
        matrix = day_rows[list(feature_columns)].replace([np.inf, -np.inf], np.nan).dropna()
        if matrix.empty:
            continue
        raw_probabilities = estimator.predict_proba(matrix.to_numpy(dtype=float))[:, 1]
        probabilities = (
            calibrator.predict(raw_probabilities)
            if calibrator is not None
            else raw_probabilities
        )
        subset = day_rows.loc[matrix.index].copy()
        subset["probability"] = probabilities
        rows.append(subset)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def factor_diagnostics(
    labeled_panel: pd.DataFrame,
    *,
    horizon: int = 21,
) -> tuple[FactorDiagnostics, ...]:
    signals = (
        "momentum_12_1__normalized",
        "trend_slope__normalized",
        "volatility__normalized",
        "composite",
    )
    output: list[FactorDiagnostics] = []
    for signal in signals:
        values = pd.to_numeric(labeled_panel[signal], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        valid = values.dropna()
        evaluation = evaluate_factor(
            labeled_panel,
            signal_column=signal,
            forward_return_column="forward_return",
            horizon=horizon,
        )
        output.append(
            FactorDiagnostics(
                factor=signal,
                mean=float(valid.mean()) if len(valid) else None,
                std=float(valid.std(ddof=1)) if len(valid) > 1 else None,
                p01=float(valid.quantile(0.01)) if len(valid) else None,
                p50=float(valid.median()) if len(valid) else None,
                p99=float(valid.quantile(0.99)) if len(valid) else None,
                coverage=float(valid.notna().mean()) if len(values) else 0.0,
                missing_ratio=float(values.isna().mean()) if len(values) else 1.0,
                rank_ic=evaluation.mean_ic,
                pearson_ic=evaluation.pearson_ic,
                positive_ic_ratio=evaluation.positive_ic_ratio,
                ic_ir=evaluation.icir,
                top_bottom_spread=evaluation.top_bottom_spread,
                turnover=evaluation.turnover,
                constant=bool(len(valid) and valid.nunique() <= 1),
            )
        )
    return tuple(output)


def simple_portfolio_ab(
    labeled_panel: pd.DataFrame,
    *,
    dates: tuple[date, ...],
    benchmark: str,
    cost_config: TransactionCostConfig | None = None,
    top_fraction: float = 0.20,
    maximum_weight: float = 0.12,
    minimum_cash: float = 0.10,
    maximum_multiplier: float = 0.25,
) -> PortfolioAB:
    configured_cost = cost_config or TransactionCostConfig()
    cost_model = TransactionCostModel(configured_cost)
    panel = labeled_panel.copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    panel = panel[panel["as_of_date"].isin(dates)]
    if "probability" not in panel:
        panel["probability"] = 0.50
    adjusted = apply_probability_adjustment(
        panel,
        probability_column="probability",
        maximum_multiplier=maximum_multiplier,
    )
    classical_targets = _target_weights(
        adjusted,
        alpha_column="expected_alpha",
        dates=dates,
        top_fraction=top_fraction,
        maximum_weight=maximum_weight,
        minimum_cash=minimum_cash,
    )
    probability_targets = _target_weights(
        adjusted,
        alpha_column="adjusted_alpha",
        dates=dates,
        top_fraction=top_fraction,
        maximum_weight=maximum_weight,
        minimum_cash=minimum_cash,
    )
    classical_points, classical_cost, classical_turnover = _simulate_weights(
        panel,
        adjusted,
        alpha_column="expected_alpha",
        dates=dates,
        top_fraction=top_fraction,
        maximum_weight=maximum_weight,
        minimum_cash=minimum_cash,
        cost_model=cost_model,
    )
    probability_points, probability_cost, probability_turnover = _simulate_weights(
        panel,
        adjusted,
        alpha_column="adjusted_alpha",
        dates=dates,
        top_fraction=top_fraction,
        maximum_weight=maximum_weight,
        minimum_cash=minimum_cash,
        cost_model=cost_model,
    )
    return PortfolioAB(
        classical_net_return=_cumulative_return(classical_points),
        probability_net_return=_cumulative_return(probability_points),
        classical_sharpe=_sharpe(classical_points),
        probability_sharpe=_sharpe(probability_points),
        classical_drawdown=_max_drawdown(classical_points),
        probability_drawdown=_max_drawdown(probability_points),
        probability_change_count=int(
            (adjusted["adjusted_alpha"] != adjusted["expected_alpha"]).sum()
        ),
        probability_target_change_count=sum(
            classical_targets.get(day) != probability_targets.get(day) for day in dates
        ),
        probability_max_multiplier=float(adjusted["probability_multiplier"].max()),
        probability_min_multiplier=float(adjusted["probability_multiplier"].min()),
        turnover_classical=classical_turnover,
        turnover_probability=probability_turnover,
        total_cost_classical=classical_cost,
        total_cost_probability=probability_cost,
    )


def evaluate_factor(
    panel: pd.DataFrame,
    *,
    signal_column: str,
    forward_return_column: str,
    horizon: int,
    quantiles: int = 5,
    minimum_cross_section: int = 5,
) -> Any:
    """Small wrapper around the existing evaluator contract for diagnostics."""

    from personal_alpha_terminal.quant_engine.factors.evaluation import (
        evaluate_factor as upstream,
    )

    return upstream(
        panel,
        signal_column=signal_column,
        forward_return_column=forward_return_column,
        horizon=horizon,
        quantiles=quantiles,
        minimum_cross_section=minimum_cross_section,
    )


def write_round4_report(
    report: Round4ResearchReport,
    root: Path,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{report.run_id}.json"
    rendered = json.dumps(report.document(), ensure_ascii=False, indent=2, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"round4 research report is immutable: {path}")
    path.write_text(rendered, encoding="utf-8")
    latest = root / "latest.json"
    latest.write_text(rendered, encoding="utf-8")
    return path


def run_round4_research(
    session: Session,
    *,
    decision_time: datetime,
    history_start: date = date(2020, 1, 1),
    benchmark: str = "SPY",
    horizon: int = 21,
    rules: EligibilityRules | None = None,
    eligibility: BroadUniverseEligibility | None = None,
) -> Round4ResearchReport:
    configured_rules = rules or EligibilityRules()
    price_panel = load_price_panel(
        session,
        decision_time=decision_time,
        history_start=history_start,
        horizon=horizon,
        reference_symbols=(benchmark, "QQQ"),
    )
    dates = rebalance_dates(price_panel, end_date=decision_time.date(), horizon=horizon)
    if len(dates) < 6:
        raise ValueError("round4 research requires at least six rebalance dates")
    factor_panel = build_factor_panel(
        price_panel,
        dates=dates,
        rules=configured_rules,
    )
    if factor_panel.empty:
        raise ValueError("round4 factor panel is empty")
    labeled_panel = build_labeled_panel(
        price_panel,
        factor_panel,
        benchmark=benchmark,
        horizon=horizon,
    )
    diagnostics = factor_diagnostics(labeled_panel, horizon=horizon)
    factor_correlations = _factor_correlation_matrix(labeled_panel)
    train, calibration, oos = temporal_splits(dates)
    identity = _research_identity(
        benchmark=benchmark,
        horizon=horizon,
        rules=configured_rules,
        decision_time=decision_time,
        eligibility=eligibility,
    )
    calibration_evidence: ProbabilityCalibrationEvidence | None = None
    probability_snapshot: dict[str, object] | None = None
    portfolio_ab: PortfolioAB | None = None
    try:
        calibration_evidence = train_probability_calibration(
            labeled_panel,
            identity=identity,
            train_period=train,
            calibration_period=calibration,
            oos_period=oos,
        )
    except (ArithmeticError, RuntimeError, TypeError, ValueError) as error:
        calibration_evidence = None
        portfolio_error = str(error)
    else:
        portfolio_error = ""
        try:
            current_predictions = train_probability_predictions(
                labeled_panel,
                factor_panel,
                feature_columns=(
                    "momentum_12_1__normalized",
                    "trend_slope__normalized",
                    "volatility__normalized",
                    "composite",
                    "expected_alpha",
                ),
                train_period=train,
                calibration_period=calibration,
                dates=(dates[-1],),
            )
            probability_snapshot = _probability_snapshot(
                factor_panel,
                current_predictions,
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
                train_period=train,
                calibration_period=calibration,
                dates=oos,
            )
            labeled_with_probability = labeled_panel.merge(
                predictions[["as_of_date", "ticker", "probability"]],
                on=["as_of_date", "ticker"],
                how="left",
            )
            portfolio_ab = simple_portfolio_ab(
                labeled_with_probability,
                dates=oos,
                benchmark=benchmark,
            )
        except (ArithmeticError, FloatingPointError, TypeError, ValueError) as error:
            portfolio_ab = None
            portfolio_error = str(error)
    walk_forward = {
        "train_start": train[0].isoformat(),
        "train_end": train[1].isoformat(),
        "calibration_start": calibration[0].isoformat(),
        "calibration_end": calibration[1].isoformat(),
        "oos_start": oos[0].isoformat(),
        "oos_end": oos[1].isoformat(),
        "rebalance_dates": len(dates),
        "factor_rows": len(labeled_panel),
    }
    benchmark_stats = _benchmark_stats(price_panel, benchmark)
    blockers: list[str] = [
        "SURVIVORSHIP_LIMITED: current-directory price rows are not a "
        "certified historical universe",
        "PRICE_BASED_RANKING: no PIT corporate-action ledger for the broad universe",
    ]
    if calibration_evidence is None:
        blockers.append(
            f"PROBABILITY_CALIBRATION_UNAVAILABLE: {portfolio_error or 'temporal sample too small'}"
        )
    if portfolio_ab is None:
        blockers.append("PROBABILITY_INCREMENTAL_VALUE_UNAVAILABLE")
    universe_counts = _universe_counts(price_panel, factor_panel)
    report_payload = {
        "run_id": f"round4-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(UTC).isoformat(),
        "universe": universe_counts,
        "eligibility_hash": (
            eligibility.snapshot_hash if eligibility is not None else "UNAVAILABLE"
        ),
        "factor_diagnostics": [asdict(item) for item in diagnostics],
        "factor_correlations": factor_correlations,
        "calibration": calibration_evidence.document() if calibration_evidence else None,
        "probability_snapshot": probability_snapshot,
        "portfolio_ab": asdict(portfolio_ab) if portfolio_ab else None,
        "walk_forward": walk_forward,
        "benchmark": benchmark_stats,
        "survivors": "SURVIVORSHIP_LIMITED",
        "blockers": blockers,
    }
    report_hash = fingerprint(report_payload)
    return Round4ResearchReport(
        run_id=str(report_payload["run_id"]),
        created_at=datetime.now(UTC),
        universe=universe_counts,
        eligibility_hash=str(report_payload["eligibility_hash"]),
        factor_diagnostics=diagnostics,
        factor_correlations=factor_correlations,
        calibration=calibration_evidence,
        probability_snapshot=probability_snapshot,
        portfolio_ab=portfolio_ab,
        walk_forward=walk_forward,
        benchmark=benchmark_stats,
        survivors="SURVIVORSHIP_LIMITED",
        blockers=tuple(blockers),
        report_hash=report_hash,
    )


def _reliability_buckets(
    probabilities: np.ndarray,
    outcomes: np.ndarray,
    *,
    bucket_count: int = 10,
) -> tuple[list[ReliabilityBucket], float]:
    buckets: list[ReliabilityBucket] = []
    ece = 0.0
    edges = np.linspace(0.0, 1.0, bucket_count + 1)
    for index in range(bucket_count):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        selected = (probabilities >= lower) & (
            probabilities <= upper if index == bucket_count - 1 else probabilities < upper
        )
        count = int(selected.sum())
        if count == 0:
            continue
        predicted = float(probabilities[selected].mean())
        actual = float(outcomes[selected].mean())
        ece += count / len(probabilities) * abs(predicted - actual)
        buckets.append(ReliabilityBucket(lower, upper, predicted, actual, count))
    return buckets, ece


def _research_identity(
    *,
    benchmark: str,
    horizon: int,
    rules: EligibilityRules,
    decision_time: datetime,
    eligibility: BroadUniverseEligibility | None,
) -> ResearchIdentity:
    feature_schema = (
        "momentum_12_1__normalized",
        "trend_slope__normalized",
        "volatility__normalized",
        "composite",
        "expected_alpha",
    )
    return ResearchIdentity(
        strategy_id="USAdaptiveAlphaCoreV1",
        strategy_version="1.0.0",
        model_id="Round4LogisticCalibrationV1",
        feature_schema_hash=sha256(
            json.dumps(feature_schema, sort_keys=True).encode()
        ).hexdigest(),
        factor_identity=USAdaptiveAlphaCoreV1Config().parameter_fingerprint,
        universe_identity=(
            "PRICE_BASED_RANKING:CURRENT_DIRECTORY"
            if eligibility is None
            else f"PRICE_BASED_RANKING:{eligibility.snapshot_hash}"
        ),
        benchmark=benchmark,
        holding_horizon=horizon,
        transaction_cost_assumption="commission+spread+slippage+impact bps",
        data_version=(
            eligibility.snapshot_hash
            if eligibility is not None
            else f"DB_RAW_AS_OF_{decision_time.date().isoformat()}"
        ),
        config_hash=rules.fingerprint,
    )


def _universe_counts(
    price_panel: pd.DataFrame,
    factor_panel: pd.DataFrame,
) -> dict[str, int]:
    dates = sorted(
        {value.date() for value in pd.to_datetime(price_panel["trade_date"], errors="raise")}
    )
    return {
        "price_panel_stocks": int(price_panel["ticker"].nunique()),
        "factor_panel_stocks": int(factor_panel["ticker"].nunique()) if len(factor_panel) else 0,
        "factor_dates": int(factor_panel["as_of_date"].nunique()) if len(factor_panel) else 0,
        "price_dates": len(dates),
    }


def _factor_correlation_matrix(
    panel: pd.DataFrame,
) -> dict[str, object]:
    columns = (
        "momentum_12_1__normalized",
        "trend_slope__normalized",
        "volatility__normalized",
        "composite",
    )
    values = panel[list(columns)].replace([np.inf, -np.inf], np.nan)
    pearson = values.corr()
    spearman = values.rank().corr()
    return {
        "pearson": pearson.to_dict(),
        "spearman": spearman.to_dict(),
        "coverage": {
            name: float(values[name].notna().mean()) if name in values else 0.0
            for name in columns
        },
    }


def _probability_snapshot(
    factor_panel: pd.DataFrame,
    predictions: pd.DataFrame,
) -> dict[str, object]:
    if predictions.empty:
        return {"status": "UNAVAILABLE"}
    latest_date = sorted(
        {value.date() for value in pd.to_datetime(predictions["as_of_date"])}
    )[-1]
    latest = predictions[pd.to_datetime(predictions["as_of_date"]).dt.date == latest_date]
    if latest.empty:
        return {"status": "UNAVAILABLE"}
    frame = factor_panel[
        pd.to_datetime(factor_panel["as_of_date"]).dt.date == latest_date
    ].merge(
        latest[["ticker", "probability"]],
        on="ticker",
        how="inner",
    )
    if frame.empty:
        return {"status": "UNAVAILABLE"}
    adjusted = apply_probability_adjustment(
        frame,
        probability_column="probability",
    )
    rows = adjusted.sort_values("adjusted_alpha", ascending=False).head(20)
    return {
        "as_of": latest_date.isoformat(),
        "rows": [
            {
                "symbol": str(row.ticker),
                "base_alpha": float(row.expected_alpha),
                "probability": float(row.probability),
                "multiplier": float(row.probability_multiplier),
                "adjusted_alpha": float(row.adjusted_alpha),
            }
            for row in rows.itertuples(index=False)
        ],
        "status": "CALIBRATED_RESEARCH",
    }


def _benchmark_stats(labeled_panel: pd.DataFrame, benchmark: str) -> dict[str, float | None]:
    if "ticker" not in labeled_panel or benchmark not in set(labeled_panel["ticker"]):
        return {"period_return": None, "volatility": None, "drawdown": None}
    levels = labeled_panel.loc[
        labeled_panel["ticker"] == benchmark, ["trade_date", "close"]
    ].copy()
    levels["trade_date"] = pd.to_datetime(levels["trade_date"], errors="raise")
    levels = levels.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    values = levels["close"].astype(float).pct_change().dropna()
    if values.empty:
        return {"period_return": None, "volatility": None, "drawdown": None}
    wealth = np.cumprod(1.0 + values.to_numpy(dtype=float))
    return {
        "period_return": float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0),
        "volatility": float(values.std(ddof=1) * sqrt(252)) if len(values) > 1 else None,
        "drawdown": float(np.min(wealth / np.maximum.accumulate(wealth) - 1.0)),
    }


def _return_matrix(
    labeled_panel: pd.DataFrame,
    benchmark: str,
) -> pd.DataFrame:
    panel = labeled_panel.copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    levels_by_date: dict[date, dict[str, float]] = {}
    for record in panel.itertuples(index=False):
        day = record.as_of_date
        ticker = record.ticker
        close = float(getattr(record, f"future_{ticker}", np.nan))
        if isfinite(close):
            levels_by_date.setdefault(day, {})[ticker] = close
    # Not enough information in the labeled frame to reconstruct true daily
    # returns; the A/B uses rebalance-period returns from future columns instead.
    rows: list[dict[str, object]] = []
    for day in sorted(levels_by_date):
        row: dict[str, object] = {"as_of_date": day}
        row.update(levels_by_date[day])
        rows.append(row)
    return pd.DataFrame(rows)


def _simulate_weights(
    panel: pd.DataFrame,
    adjusted: pd.DataFrame,
    *,
    alpha_column: str,
    dates: tuple[date, ...],
    top_fraction: float,
    maximum_weight: float,
    minimum_cash: float,
    cost_model: TransactionCostModel,
) -> tuple[list[float], float, float]:
    if panel.empty:
        return ([1.0], 0.0, 0.0)
    points: list[float] = [1.0]
    total_cost = 0.0
    total_turnover = 0.0
    current: dict[str, float] = {}
    for day in dates:
        target = _target_weights(
            adjusted,
            alpha_column=alpha_column,
            dates=(day,),
            top_fraction=top_fraction,
            maximum_weight=maximum_weight,
            minimum_cash=minimum_cash,
        ).get(day, {})
        period_return = 0.0
        for symbol, weight in target.items():
            rows = adjusted[
                (pd.to_datetime(adjusted["as_of_date"]).dt.date == day)
                & (adjusted["ticker"] == symbol)
            ]
            if not rows.empty:
                period_return += weight * float(rows["forward_return"].iloc[0])
        turnover = sum(
            abs(target.get(symbol, 0.0) - current.get(symbol, 0.0))
            for symbol in set(target) | set(current)
        )
        trade_value = turnover * 1_000_000.0
        try:
            cost = cost_model.estimate(
                trade_value=trade_value,
                average_daily_dollar_volume=100_000_000.0,
            ).total_cost
        except ValueError:
            cost = 0.0
        cost_fraction = cost / 1_000_000.0
        total_cost += cost_fraction * 1_000_000.0
        total_turnover += turnover
        current = target
        points.append(points[-1] * (1.0 + period_return) * (1.0 - cost_fraction))
    return points, total_cost, total_turnover


def _target_weights(
    adjusted: pd.DataFrame,
    *,
    alpha_column: str,
    dates: tuple[date, ...],
    top_fraction: float,
    maximum_weight: float,
    minimum_cash: float,
) -> dict[date, dict[str, float]]:
    output: dict[date, dict[str, float]] = {}
    for day in dates:
        day_rows = adjusted[pd.to_datetime(adjusted["as_of_date"]).dt.date == day]
        if day_rows.empty:
            continue
        ranked = day_rows.sort_values(alpha_column, ascending=False)
        selected_count = max(1, int(round(len(ranked) * top_fraction)))
        selected = ranked.head(selected_count)
        target_value = 1.0 - minimum_cash
        cap_total = selected_count * maximum_weight
        scale = min(1.0, target_value / cap_total) if cap_total > 0 else 0.0
        output[day] = {
            symbol: min(maximum_weight, target_value * scale / selected_count)
            for symbol in selected["ticker"]
            if float(selected.loc[selected["ticker"] == symbol, alpha_column].iloc[0]) > 0
        }
    return output


def _cumulative_return(points: list[float]) -> float:
    return float(points[-1] / points[0] - 1.0) if points else 0.0


def _sharpe(points: list[float]) -> float | None:
    if len(points) < 3:
        return None
    returns = np.diff(points) / np.asarray(points[:-1])
    std = float(np.std(returns, ddof=1))
    return float(np.mean(returns) / std * sqrt(252)) if std > 0 else None


def _max_drawdown(points: list[float]) -> float | None:
    if not points:
        return None
    wealth = np.asarray(points, dtype=float)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1.0))
