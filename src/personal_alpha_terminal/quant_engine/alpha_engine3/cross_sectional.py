"""PIT-safe cross-sectional expected-return research for ROUND62.

This module is a challenger layer. It cannot alter the production Champion
without a certified research manifest and a separately frozen locked-OOS run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite, sqrt
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor  # type: ignore[import-untyped]
from sklearn.ensemble import GradientBoostingRegressor  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import ElasticNet, HuberRegressor, Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from personal_alpha_terminal.quant_engine.alpha_engine2.promotion import (
    PromotionVerdict,
    StrategyMetrics,
    evaluate_promotion,
)
from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import ResearchDatasetManifestV2

DEFAULT_PRICE_FEATURES = (
    "momentum_21",
    "momentum_63",
    "momentum_126",
    "momentum_252_21",
    "trend_slope_63",
    "trend_strength_63",
    "breakout_63",
    "reversal_5",
    "reversal_21",
    "distance_ma_20",
    "distance_ma_60",
    "realized_volatility_21",
    "downside_volatility_21",
    "idiosyncratic_volatility_63",
    "beta_63",
    "drawdown_252",
    "relative_strength_63",
    "sector_relative_strength_63",
    "adv_20",
    "turnover_proxy_20",
    "gap_behavior_20",
    "volatility_of_volatility_63",
    "size_score",
    "volatility_bucket",
    "cluster_code",
    "market_momentum_63",
    "market_volatility_21",
)

FUNDAMENTAL_FEATURES = (
    "profitability",
    "margin",
    "roe",
    "roic",
    "leverage",
    "cash_generation",
    "earnings_quality",
    "growth",
    "valuation",
    "revisions",
)


class AlphaModelKind(StrEnum):
    CURRENT_HEURISTIC = "CURRENT_HEURISTIC_CHAMPION"
    RIDGE = "RIDGE"
    ELASTIC_NET = "ELASTIC_NET"
    HUBER = "HUBER"
    IC_WEIGHTED = "IC_WEIGHTED_ENSEMBLE"
    GRADIENT_BOOSTING = "GRADIENT_BOOSTING"


class AlphaEngine3Verdict(StrEnum):
    PROMOTE_CHALLENGER = "PROMOTE_CHALLENGER"
    KEEP_EXISTING_CHAMPION = "KEEP_EXISTING_CHAMPION"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"


@dataclass(frozen=True, slots=True)
class AlphaEngine3Config:
    horizons: tuple[int, ...] = (5, 21, 63)
    minimum_history: int = 64
    minimum_train_dates: int = 12
    test_dates_per_fold: int = 4
    embargo_dates: int = 1
    minimum_training_rows: int = 120
    minimum_test_rows: int = 20
    transaction_cost_bps: float = 7.0
    slippage_bps: float = 3.0
    bootstrap_samples: int = 400
    random_seed: int = 20260818

    def __post_init__(self) -> None:
        if (
            not self.horizons
            or any(item <= 0 for item in self.horizons)
            or self.minimum_history < 20
            or self.minimum_train_dates < 3
            or self.test_dates_per_fold <= 0
            or self.embargo_dates < 0
            or self.minimum_training_rows <= 0
            or self.minimum_test_rows <= 0
            or self.transaction_cost_bps < 0
            or self.slippage_bps < 0
            or self.bootstrap_samples < 100
        ):
            raise ValueError("alpha engine 3 configuration is invalid")


@dataclass(frozen=True, slots=True)
class FeaturePanel:
    frame: pd.DataFrame
    enabled_features: tuple[str, ...]
    disabled_features: tuple[str, ...]
    fundamentals_pit_safe: bool


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    train_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    train_rows: int
    test_rows: int
    purged_rows: int


@dataclass(frozen=True, slots=True)
class CrossSectionalPrediction:
    model: AlphaModelKind
    horizon_sessions: int
    as_of_date: date
    permanent_security_id: str
    ranking_score: float
    expected_excess_return: float
    realized_excess_return: float


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower_quantile: float
    upper_quantile: float
    predicted_mean: float
    realized_mean: float
    count: int


@dataclass(frozen=True, slots=True)
class FeatureAblation:
    feature: str
    baseline_rank_ic: float | None
    ablated_rank_ic: float | None
    rank_ic_delta: float | None
    baseline_net_alpha: float | None
    ablated_net_alpha: float | None
    net_alpha_delta: float | None


@dataclass(frozen=True, slots=True)
class ModelEvidence:
    model: AlphaModelKind
    horizon_sessions: int
    supported: bool
    failure_reason: str | None
    prediction_count: int
    fold_count: int
    average_positive_candidates: float | None
    maximum_positive_candidates: int | None
    rank_ic: float | None
    pearson_ic: float | None
    annualized_net_excess_return: float | None
    annualized_volatility: float | None
    sharpe: float | None
    information_ratio: float | None
    maximum_drawdown: float | None
    annualized_turnover: float | None
    total_cost_bps: float | None
    stability: float | None
    forward_consistency: float | None
    bootstrap_net_alpha_interval: tuple[float, float] | None
    calibration: tuple[CalibrationBucket, ...]
    attribution: dict[str, float]
    regime_breakdown: dict[str, float]
    sector_breakdown: dict[str, float]

    def document(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AlphaEngine3Evaluation:
    verdict: AlphaEngine3Verdict
    champion: AlphaModelKind
    selected_challenger: AlphaModelKind | None
    horizons: tuple[int, ...]
    feature_columns: tuple[str, ...]
    folds: tuple[WalkForwardFold, ...]
    evidence: tuple[ModelEvidence, ...]
    blockers: tuple[str, ...]
    locked_oos: bool
    deterministic_seed: int

    def document(self) -> dict[str, object]:
        return asdict(self)


def build_price_feature_panel(
    prices: pd.DataFrame,
    *,
    decision_cutoffs: tuple[datetime, ...],
    benchmark_symbol: str,
    config: AlphaEngine3Config | None = None,
    fundamentals: pd.DataFrame | None = None,
    fundamentals_pit_safe: bool = False,
) -> FeaturePanel:
    """Build price/liquidity/context features from rows visible at each cutoff."""

    configured = config or AlphaEngine3Config()
    required = {
        "permanent_security_id",
        "ticker",
        "trade_date",
        "available_time",
        "close",
    }
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"alpha engine 3 price panel misses columns: {sorted(missing)}")
    if any(item.tzinfo is None or item.utcoffset() is None for item in decision_cutoffs):
        raise ValueError("all alpha engine 3 decision cutoffs must be timezone-aware")

    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "volume" in frame:
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    rows: list[dict[str, object]] = []
    disabled: set[str] = set()

    for decision_cutoff in sorted(decision_cutoffs):
        cutoff = pd.Timestamp(decision_cutoff).tz_convert("UTC")
        visible = frame.loc[
            (frame["trade_date"].dt.date <= decision_cutoff.date())
            & (frame["available_time"] <= cutoff)
            & (frame["close"] > 0)
        ].copy()
        benchmark = visible.loc[visible["ticker"] == benchmark_symbol]
        benchmark_returns = _ordered_returns(benchmark)
        market_momentum = _period_return(benchmark_returns, 63)
        market_volatility = _annualized_volatility(benchmark_returns, 21)
        preliminary: list[dict[str, object]] = []
        for security_id, group in visible.groupby("permanent_security_id", sort=True):
            ordered = group.sort_values(["trade_date", "available_time"]).drop_duplicates(
                "trade_date", keep="last"
            )
            ticker = str(ordered["ticker"].iloc[-1])
            if ticker == benchmark_symbol or len(ordered) < configured.minimum_history:
                continue
            close = ordered["close"].astype(float).to_numpy()
            returns = pd.Series(close).pct_change().dropna().to_numpy(dtype=float)
            if not len(returns):
                continue
            beta, idiosyncratic = _beta_and_idiosyncratic(returns, benchmark_returns, 63)
            metadata = ordered.iloc[-1]
            sector = str(metadata.get("sector", "UNKNOWN"))
            cluster = str(metadata.get("cluster", "UNKNOWN"))
            market_cap = _finite_or_nan(metadata.get("market_cap"))
            volume = (
                ordered["volume"].astype(float).to_numpy()
                if "volume" in ordered
                else np.asarray([], dtype=float)
            )
            if not len(volume):
                disabled.update({"adv_20", "turnover_proxy_20"})
            preliminary.append(
                {
                    "permanent_security_id": str(security_id),
                    "ticker": ticker,
                    "as_of_date": decision_cutoff.date(),
                    "decision_cutoff": cutoff.to_pydatetime(),
                    "feature_available_at": ordered["available_time"].max().to_pydatetime(),
                    "sector": sector,
                    "industry": str(metadata.get("industry", "UNKNOWN")),
                    "cluster": cluster,
                    "momentum_21": _price_return(close, 21),
                    "momentum_63": _price_return(close, 63),
                    "momentum_126": _price_return(close, 126),
                    "momentum_252_21": _skip_return(close, 252, 21),
                    "trend_slope_63": _trend_slope(close, 63)[0],
                    "trend_strength_63": _trend_slope(close, 63)[1],
                    "breakout_63": _breakout(close, 63),
                    "reversal_5": -_price_return(close, 5),
                    "reversal_21": -_price_return(close, 21),
                    "distance_ma_20": _distance_to_mean(close, 20),
                    "distance_ma_60": _distance_to_mean(close, 60),
                    "realized_volatility_21": _annualized_volatility(returns, 21),
                    "downside_volatility_21": _downside_volatility(returns, 21),
                    "idiosyncratic_volatility_63": idiosyncratic,
                    "beta_63": beta,
                    "drawdown_252": _drawdown(close, 252),
                    "relative_strength_63": _price_return(close, 63) - market_momentum,
                    "sector_relative_strength_63": np.nan,
                    "adv_20": _adv(close, volume, 20),
                    "turnover_proxy_20": _turnover_proxy(volume, market_cap, 20),
                    "gap_behavior_20": _gap_behavior(returns, 20),
                    "volatility_of_volatility_63": _volatility_of_volatility(returns, 63),
                    "size_score": np.log(max(market_cap, 1.0)) if isfinite(market_cap) else np.nan,
                    "volatility_bucket": np.nan,
                    "cluster_code": np.nan,
                    "market_momentum_63": market_momentum,
                    "market_volatility_21": market_volatility,
                }
            )
        if not preliminary:
            continue
        cross_section = pd.DataFrame(preliminary)
        cross_section["sector_relative_strength_63"] = cross_section["momentum_63"] - (
            cross_section.groupby("sector")["momentum_63"].transform("mean")
        )
        cross_section["volatility_bucket"] = cross_section[
            "realized_volatility_21"
        ].rank(method="average", pct=True)
        cluster_codes = {
            name: float(index)
            for index, name in enumerate(sorted(set(cross_section["cluster"])))
        }
        cross_section["cluster_code"] = cross_section["cluster"].map(cluster_codes)
        rows.extend(cross_section.to_dict(orient="records"))

    output = pd.DataFrame(rows)
    if output.empty:
        return FeaturePanel(output, (), tuple(sorted(disabled)), fundamentals_pit_safe)
    if fundamentals is not None and fundamentals_pit_safe:
        output = _merge_pit_fundamentals(output, fundamentals)
    else:
        disabled.update(f"fundamental:{name}" for name in FUNDAMENTAL_FEATURES)

    enabled: list[str] = []
    for feature in (*DEFAULT_PRICE_FEATURES, *FUNDAMENTAL_FEATURES):
        if feature not in output:
            disabled.add(feature)
            continue
        values = pd.to_numeric(output[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if values.notna().mean() < 0.50 or values.nunique(dropna=True) <= 1:
            disabled.add(feature)
            continue
        output[feature] = values
        enabled.append(feature)
    return FeaturePanel(
        output.sort_values(["as_of_date", "permanent_security_id"]).reset_index(drop=True),
        tuple(enabled),
        tuple(sorted(disabled)),
        fundamentals_pit_safe,
    )


def build_forward_labels(
    prices: pd.DataFrame,
    feature_panel: FeaturePanel,
    *,
    benchmark_symbol: str,
    horizons: tuple[int, ...] = (5, 21, 63),
) -> pd.DataFrame:
    """Attach next-session benchmark-relative labels without changing features."""

    if feature_panel.frame.empty:
        return pd.DataFrame()
    if any(item <= 0 for item in horizons):
        raise ValueError("forward label horizons must be positive")
    required = {"ticker", "trade_date", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"forward labels miss price columns: {sorted(missing)}")
    levels = prices.copy()
    levels["trade_date"] = pd.to_datetime(levels["trade_date"], errors="raise").dt.date
    levels["close"] = pd.to_numeric(levels["close"], errors="coerce")
    pivot = levels.pivot_table(
        index="trade_date", columns="ticker", values="close", aggfunc="last"
    ).sort_index()
    if benchmark_symbol not in pivot:
        raise ValueError(f"benchmark {benchmark_symbol} is missing from forward label prices")
    sessions = tuple(pivot.index)
    positions = {session: index for index, session in enumerate(sessions)}
    labeled: list[dict[str, object]] = []
    for record in feature_panel.frame.to_dict(orient="records"):
        as_of = pd.Timestamp(record["as_of_date"]).date()
        position = positions.get(as_of)
        ticker = str(record["ticker"])
        if position is None or ticker not in pivot:
            continue
        for horizon in horizons:
            entry_index = position + 1
            exit_index = position + horizon
            if exit_index >= len(sessions):
                continue
            entry_date = sessions[entry_index]
            exit_date = sessions[exit_index]
            security_entry = _finite_or_nan(pivot.at[entry_date, ticker])
            security_exit = _finite_or_nan(pivot.at[exit_date, ticker])
            benchmark_entry = _finite_or_nan(pivot.at[entry_date, benchmark_symbol])
            benchmark_exit = _finite_or_nan(pivot.at[exit_date, benchmark_symbol])
            if not all(
                isfinite(item) and item > 0
                for item in (security_entry, security_exit, benchmark_entry, benchmark_exit)
            ):
                continue
            item = dict(record)
            item.update(
                {
                    "horizon_sessions": horizon,
                    "label_entry_date": entry_date,
                    "label_end_date": exit_date,
                    "forward_excess_return": (
                        security_exit / security_entry - benchmark_exit / benchmark_entry
                    ),
                }
            )
            labeled.append(item)
    return pd.DataFrame(labeled).sort_values(
        ["horizon_sessions", "as_of_date", "permanent_security_id"]
    ).reset_index(drop=True)


def build_walk_forward_folds(
    labeled_panel: pd.DataFrame,
    *,
    horizon_sessions: int,
    config: AlphaEngine3Config | None = None,
) -> tuple[WalkForwardFold, ...]:
    """Build expanding walk-forward folds with label-overlap purge and embargo."""

    configured = config or AlphaEngine3Config()
    panel = labeled_panel.loc[
        labeled_panel["horizon_sessions"] == horizon_sessions
    ].copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    panel["label_end_date"] = pd.to_datetime(
        panel["label_end_date"], errors="raise"
    ).dt.date
    dates = tuple(sorted(set(panel["as_of_date"])))
    folds: list[WalkForwardFold] = []
    for start in range(
        configured.minimum_train_dates,
        len(dates),
        configured.test_dates_per_fold,
    ):
        test_dates = dates[start : start + configured.test_dates_per_fold]
        if not test_dates:
            continue
        embargo_index = max(0, start - configured.embargo_dates)
        embargo_cutoff = dates[embargo_index]
        candidate_dates = dates[:start]
        candidate = panel.loc[panel["as_of_date"].isin(candidate_dates)]
        purged = candidate.loc[candidate["label_end_date"] < embargo_cutoff]
        test = panel.loc[panel["as_of_date"].isin(test_dates)]
        train_dates = tuple(sorted(set(purged["as_of_date"])))
        purged_rows = len(candidate) - len(purged)
        if (
            len(purged) < configured.minimum_training_rows
            or len(test) < configured.minimum_test_rows
            or len(train_dates) < 3
        ):
            continue
        folds.append(
            WalkForwardFold(
                fold_id=f"H{horizon_sessions}-F{len(folds) + 1:02d}",
                train_dates=train_dates,
                test_dates=tuple(test_dates),
                train_rows=len(purged),
                test_rows=len(test),
                purged_rows=purged_rows,
            )
        )
    return tuple(folds)


def evaluate_alpha_engine3(
    labeled_panel: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    manifest: ResearchDatasetManifestV2 | None,
    config: AlphaEngine3Config | None = None,
    locked_oos: bool = False,
) -> AlphaEngine3Evaluation:
    """Evaluate Champion and challengers; promotion remains fail-closed."""

    configured = config or AlphaEngine3Config()
    panel = _validated_labeled_panel(labeled_panel, feature_columns)
    all_evidence: list[ModelEvidence] = []
    all_folds: list[WalkForwardFold] = []
    for horizon in configured.horizons:
        folds = build_walk_forward_folds(
            panel,
            horizon_sessions=horizon,
            config=configured,
        )
        all_folds.extend(folds)
        horizon_panel = panel.loc[panel["horizon_sessions"] == horizon].copy()
        for model in AlphaModelKind:
            all_evidence.append(
                _evaluate_model(
                    horizon_panel,
                    folds=folds,
                    feature_columns=feature_columns,
                    model=model,
                    config=configured,
                )
            )

    blockers = _promotion_blockers(manifest, locked_oos=locked_oos)
    aggregate = _aggregate_by_model(all_evidence)
    champion = aggregate.get(AlphaModelKind.CURRENT_HEURISTIC)
    challengers = [
        item
        for model, item in aggregate.items()
        if model is not AlphaModelKind.CURRENT_HEURISTIC and item.supported
    ]
    selected = max(
        challengers,
        key=lambda item: (
            item.rank_ic if item.rank_ic is not None else float("-inf"),
            item.annualized_net_excess_return
            if item.annualized_net_excess_return is not None
            else float("-inf"),
            item.model.value,
        ),
        default=None,
    )
    verdict = AlphaEngine3Verdict.BLOCKED_DATA_QUALITY if blockers else (
        AlphaEngine3Verdict.KEEP_EXISTING_CHAMPION
    )
    if not blockers and champion is not None and selected is not None:
        promotion = evaluate_promotion(
            challenger_id=f"alpha-engine3:{selected.model.value}",
            champion=_promotion_metrics(champion),
            challenger=_promotion_metrics(selected),
        )
        verdict = (
            AlphaEngine3Verdict.PROMOTE_CHALLENGER
            if promotion.verdict is PromotionVerdict.CHALLENGER_PROMOTED
            else AlphaEngine3Verdict.KEEP_EXISTING_CHAMPION
        )
    return AlphaEngine3Evaluation(
        verdict=verdict,
        champion=AlphaModelKind.CURRENT_HEURISTIC,
        selected_challenger=selected.model if selected is not None else None,
        horizons=configured.horizons,
        feature_columns=feature_columns,
        folds=tuple(all_folds),
        evidence=tuple(all_evidence),
        blockers=tuple(blockers),
        locked_oos=locked_oos,
        deterministic_seed=configured.random_seed,
    )


def evaluate_feature_ablation(
    labeled_panel: pd.DataFrame,
    *,
    model: AlphaModelKind,
    horizon_sessions: int,
    feature_columns: tuple[str, ...],
    config: AlphaEngine3Config | None = None,
) -> tuple[FeatureAblation, ...]:
    """Run deterministic leave-one-feature-out diagnostics on one horizon."""

    if len(feature_columns) < 2:
        raise ValueError("feature ablation requires at least two features")
    configured = config or AlphaEngine3Config()
    panel = _validated_labeled_panel(labeled_panel, feature_columns)
    horizon_panel = panel.loc[panel["horizon_sessions"] == horizon_sessions].copy()
    folds = build_walk_forward_folds(
        horizon_panel,
        horizon_sessions=horizon_sessions,
        config=configured,
    )
    baseline = _evaluate_model(
        horizon_panel,
        folds=folds,
        feature_columns=feature_columns,
        model=model,
        config=configured,
    )
    results: list[FeatureAblation] = []
    for feature in feature_columns:
        retained = tuple(item for item in feature_columns if item != feature)
        ablated = _evaluate_model(
            horizon_panel,
            folds=folds,
            feature_columns=retained,
            model=model,
            config=configured,
        )
        results.append(
            FeatureAblation(
                feature=feature,
                baseline_rank_ic=baseline.rank_ic,
                ablated_rank_ic=ablated.rank_ic,
                rank_ic_delta=_difference_optional(baseline.rank_ic, ablated.rank_ic),
                baseline_net_alpha=baseline.annualized_net_excess_return,
                ablated_net_alpha=ablated.annualized_net_excess_return,
                net_alpha_delta=_difference_optional(
                    baseline.annualized_net_excess_return,
                    ablated.annualized_net_excess_return,
                ),
            )
        )
    return tuple(results)


def _evaluate_model(
    panel: pd.DataFrame,
    *,
    folds: tuple[WalkForwardFold, ...],
    feature_columns: tuple[str, ...],
    model: AlphaModelKind,
    config: AlphaEngine3Config,
) -> ModelEvidence:
    if not folds:
        horizon = int(panel["horizon_sessions"].iloc[0]) if len(panel) else 0
        return _unsupported(model, horizon, "INSUFFICIENT_PURGED_WALK_FORWARD_FOLDS")
    predictions: list[pd.DataFrame] = []
    attribution: dict[str, list[float]] = {name: [] for name in feature_columns}
    try:
        for fold in folds:
            train = panel.loc[panel["as_of_date"].isin(fold.train_dates)].copy()
            test = panel.loc[panel["as_of_date"].isin(fold.test_dates)].copy()
            x_train = train.loc[:, feature_columns].to_numpy(dtype=float)
            y_train = train["forward_excess_return"].to_numpy(dtype=float)
            x_test = test.loc[:, feature_columns].to_numpy(dtype=float)
            if model is AlphaModelKind.CURRENT_HEURISTIC:
                predicted = test["champion_expected_excess_return"].to_numpy(dtype=float)
                fold_attribution = _current_heuristic_attribution(train, feature_columns)
            elif model is AlphaModelKind.IC_WEIGHTED:
                predicted, fold_attribution = _ic_weighted_predict(
                    x_train,
                    y_train,
                    x_test,
                    feature_columns,
                )
            else:
                estimator = _regression_model(model, config.random_seed)
                estimator.fit(x_train, y_train)
                predicted = np.asarray(estimator.predict(x_test), dtype=float)
                fold_attribution = _model_attribution(
                    estimator,
                    x_test,
                    predicted,
                    feature_columns,
                )
            scored = test[
                [
                    "as_of_date",
                    "permanent_security_id",
                    "forward_excess_return",
                    "sector",
                    "regime",
                ]
            ].copy()
            scored["expected_excess_return"] = predicted
            scored["ranking_score"] = scored.groupby("as_of_date")[
                "expected_excess_return"
            ].rank(method="average", pct=True)
            predictions.append(scored)
            for feature, value in fold_attribution.items():
                attribution[feature].append(value)
    except (ValueError, FloatingPointError, OverflowError) as exc:
        return _unsupported(model, int(panel["horizon_sessions"].iloc[0]), str(exc))

    combined = pd.concat(predictions, ignore_index=True)
    horizon = int(panel["horizon_sessions"].iloc[0])
    date_ic = _cross_sectional_correlations(combined, rank=True)
    date_pearson = _cross_sectional_correlations(combined, rank=False)
    returns, turnover, total_cost = _all_positive_portfolio_returns(
        combined,
        cost_rate=(config.transaction_cost_bps + config.slippage_bps) / 10_000,
    )
    annualization = 252 / horizon
    annualized_return = float(returns.mean() * annualization) if len(returns) else 0.0
    annualized_vol = (
        float(returns.std(ddof=1) * sqrt(annualization)) if len(returns) > 1 else 0.0
    )
    sharpe = annualized_return / annualized_vol if annualized_vol > 1e-12 else None
    bootstrap = _cluster_bootstrap_interval(
        returns,
        annualization=annualization,
        samples=config.bootstrap_samples,
        seed=config.random_seed + sum(ord(char) for char in model.value) + horizon,
    )
    positive_counts = combined.groupby("as_of_date")["expected_excess_return"].apply(
        lambda values: int((values > 0).sum())
    )
    return ModelEvidence(
        model=model,
        horizon_sessions=horizon,
        supported=True,
        failure_reason=None,
        prediction_count=len(combined),
        fold_count=len(folds),
        average_positive_candidates=float(positive_counts.mean()),
        maximum_positive_candidates=int(positive_counts.max()),
        rank_ic=float(date_ic.mean()) if len(date_ic) else None,
        pearson_ic=float(date_pearson.mean()) if len(date_pearson) else None,
        annualized_net_excess_return=annualized_return,
        annualized_volatility=annualized_vol,
        sharpe=sharpe,
        information_ratio=sharpe,
        maximum_drawdown=_maximum_drawdown(returns.to_numpy(dtype=float)),
        annualized_turnover=float(turnover.mean() * annualization) if len(turnover) else 0.0,
        total_cost_bps=total_cost * 10_000,
        stability=float((date_ic > 0).mean()) if len(date_ic) else 0.0,
        forward_consistency=float((returns > 0).mean()) if len(returns) else 0.0,
        bootstrap_net_alpha_interval=bootstrap,
        calibration=_calibration_buckets(combined),
        attribution={
            name: float(np.mean(values)) if values else 0.0
            for name, values in attribution.items()
        },
        regime_breakdown=_group_return_breakdown(combined, "regime"),
        sector_breakdown=_group_return_breakdown(combined, "sector"),
    )


def _regression_model(model: AlphaModelKind, seed: int) -> Any:
    if model is AlphaModelKind.RIDGE:
        regressor: Any = Ridge(alpha=1.0)
    elif model is AlphaModelKind.ELASTIC_NET:
        regressor = ElasticNet(alpha=0.001, l1_ratio=0.50, max_iter=10_000, selection="cyclic")
    elif model is AlphaModelKind.HUBER:
        regressor = HuberRegressor(epsilon=1.35, alpha=0.0001, max_iter=1_000)
    elif model is AlphaModelKind.GRADIENT_BOOSTING:
        regressor = GradientBoostingRegressor(
            learning_rate=0.05,
            n_estimators=120,
            max_depth=3,
            loss="huber",
            random_state=seed,
        )
    else:
        raise ValueError(f"unsupported alpha engine 3 regression model: {model.value}")
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("regressor", regressor),
        ]
    )
    return TransformedTargetRegressor(regressor=pipeline, transformer=StandardScaler())


def _ic_weighted_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    feature_columns: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, float]]:
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    train = scaler.fit_transform(imputer.fit_transform(x_train))
    test = scaler.transform(imputer.transform(x_test))
    weights = np.asarray(
        [_spearman(train[:, index], y_train) for index in range(train.shape[1])],
        dtype=float,
    )
    denominator = float(np.abs(weights).sum())
    weights = weights / denominator if denominator > 1e-12 else np.zeros_like(weights)
    raw_train = train @ weights
    raw_test = test @ weights
    design = np.column_stack([np.ones(len(raw_train)), raw_train])
    intercept, slope = np.linalg.lstsq(design, y_train, rcond=None)[0]
    predicted = intercept + slope * raw_test
    return predicted, {
        name: float(value) for name, value in zip(feature_columns, weights, strict=True)
    }


def _model_attribution(
    estimator: Any,
    x_test: np.ndarray,
    predicted: np.ndarray,
    feature_columns: tuple[str, ...],
) -> dict[str, float]:
    pipeline = estimator.regressor_
    regressor = pipeline.named_steps["regressor"]
    coefficients = getattr(regressor, "coef_", None)
    if coefficients is not None:
        values = np.asarray(coefficients, dtype=float).reshape(-1)
        scale = float(np.abs(values).sum())
        if scale > 1e-12:
            values = values / scale
        return {
            name: float(value) for name, value in zip(feature_columns, values, strict=True)
        }
    imputed = pipeline.named_steps["imputer"].transform(x_test)
    scaled = pipeline.named_steps["scaler"].transform(imputed)
    sensitivities = np.asarray(
        [_spearman(scaled[:, index], predicted) for index in range(scaled.shape[1])],
        dtype=float,
    )
    scale = float(np.abs(sensitivities).sum())
    if scale > 1e-12:
        sensitivities = sensitivities / scale
    return {
        name: float(value)
        for name, value in zip(feature_columns, sensitivities, strict=True)
    }


def _current_heuristic_attribution(
    train: pd.DataFrame,
    feature_columns: tuple[str, ...],
) -> dict[str, float]:
    return {
        name: _spearman(
            pd.to_numeric(train[name], errors="coerce").fillna(0.0).to_numpy(dtype=float),
            train["champion_expected_excess_return"].to_numpy(dtype=float),
        )
        for name in feature_columns
    }


def _validated_labeled_panel(
    panel: pd.DataFrame,
    feature_columns: tuple[str, ...],
) -> pd.DataFrame:
    required = {
        "permanent_security_id",
        "as_of_date",
        "decision_cutoff",
        "feature_available_at",
        "label_end_date",
        "horizon_sessions",
        "forward_excess_return",
        "champion_expected_excess_return",
    } | set(feature_columns)
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"alpha engine 3 labeled panel misses columns: {sorted(missing)}")
    frame = panel.copy()
    frame["as_of_date"] = pd.to_datetime(frame["as_of_date"], errors="raise").dt.date
    frame["label_end_date"] = pd.to_datetime(frame["label_end_date"], errors="raise").dt.date
    frame["decision_cutoff"] = pd.to_datetime(frame["decision_cutoff"], utc=True, errors="raise")
    frame["feature_available_at"] = pd.to_datetime(
        frame["feature_available_at"], utc=True, errors="raise"
    )
    if bool((frame["feature_available_at"] > frame["decision_cutoff"]).any()):
        raise ValueError("alpha engine 3 feature timestamp follows decision cutoff")
    if bool((frame["label_end_date"] <= frame["as_of_date"]).any()):
        raise ValueError("alpha engine 3 label end must follow the decision date")
    for column in (*feature_columns, "forward_excess_return", "champion_expected_excess_return"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(
        subset=["forward_excess_return", "champion_expected_excess_return"]
    ).copy()
    if "sector" not in frame:
        frame["sector"] = "UNKNOWN"
    if "regime" not in frame:
        frame["regime"] = "UNKNOWN"
    return frame.sort_values(
        ["horizon_sessions", "as_of_date", "permanent_security_id"]
    ).reset_index(drop=True)


def _promotion_blockers(
    manifest: ResearchDatasetManifestV2 | None,
    *,
    locked_oos: bool,
) -> list[str]:
    blockers: list[str] = []
    if manifest is None:
        blockers.append("CERTIFIED_RESEARCH_MANIFEST_REQUIRED")
    else:
        if manifest.certification_state is not ResearchDatasetState.CERTIFIED:
            blockers.extend(manifest.blockers or ("RESEARCH_DATA_NOT_CERTIFIED",))
        if not manifest.production_eligible:
            blockers.append("RESEARCH_DATA_NOT_PRODUCTION_ELIGIBLE")
        if not manifest.total_return_certified:
            blockers.append("PIT_TOTAL_RETURN_HISTORY_INCOMPLETE")
    if not locked_oos:
        blockers.append("LOCKED_OOS_NOT_FROZEN")
    return sorted(set(blockers))


def _aggregate_by_model(evidence: list[ModelEvidence]) -> dict[AlphaModelKind, ModelEvidence]:
    aggregate: dict[AlphaModelKind, ModelEvidence] = {}
    for model in AlphaModelKind:
        rows = [item for item in evidence if item.model is model and item.supported]
        if not rows:
            continue
        aggregate[model] = ModelEvidence(
            model=model,
            horizon_sessions=0,
            supported=True,
            failure_reason=None,
            prediction_count=sum(item.prediction_count for item in rows),
            fold_count=sum(item.fold_count for item in rows),
            average_positive_candidates=_mean_optional(
                item.average_positive_candidates for item in rows
            ),
            maximum_positive_candidates=max(
                (item.maximum_positive_candidates or 0 for item in rows), default=0
            ),
            rank_ic=_mean_optional(item.rank_ic for item in rows),
            pearson_ic=_mean_optional(item.pearson_ic for item in rows),
            annualized_net_excess_return=_mean_optional(
                item.annualized_net_excess_return for item in rows
            ),
            annualized_volatility=_mean_optional(item.annualized_volatility for item in rows),
            sharpe=_mean_optional(item.sharpe for item in rows),
            information_ratio=_mean_optional(item.information_ratio for item in rows),
            maximum_drawdown=max(
                (item.maximum_drawdown or 0.0 for item in rows), default=0.0
            ),
            annualized_turnover=_mean_optional(item.annualized_turnover for item in rows),
            total_cost_bps=sum(item.total_cost_bps or 0.0 for item in rows),
            stability=_mean_optional(item.stability for item in rows),
            forward_consistency=_mean_optional(item.forward_consistency for item in rows),
            bootstrap_net_alpha_interval=None,
            calibration=(),
            attribution={},
            regime_breakdown={},
            sector_breakdown={},
        )
    return aggregate


def _promotion_metrics(evidence: ModelEvidence) -> StrategyMetrics:
    return StrategyMetrics(
        oos_net_alpha=evidence.annualized_net_excess_return or 0.0,
        oos_sharpe=evidence.sharpe or 0.0,
        oos_ir=evidence.information_ratio or 0.0,
        max_drawdown=evidence.maximum_drawdown or 1.0,
        annual_turnover=evidence.annualized_turnover or 0.0,
        cost_bps=evidence.total_cost_bps or 0.0,
        stability=evidence.stability or 0.0,
        forward_consistency=evidence.forward_consistency or 0.0,
        robustness=min(evidence.stability or 0.0, evidence.forward_consistency or 0.0),
    )


def _unsupported(model: AlphaModelKind, horizon: int, reason: str) -> ModelEvidence:
    return ModelEvidence(
        model=model,
        horizon_sessions=horizon,
        supported=False,
        failure_reason=reason,
        prediction_count=0,
        fold_count=0,
        average_positive_candidates=None,
        maximum_positive_candidates=None,
        rank_ic=None,
        pearson_ic=None,
        annualized_net_excess_return=None,
        annualized_volatility=None,
        sharpe=None,
        information_ratio=None,
        maximum_drawdown=None,
        annualized_turnover=None,
        total_cost_bps=None,
        stability=None,
        forward_consistency=None,
        bootstrap_net_alpha_interval=None,
        calibration=(),
        attribution={},
        regime_breakdown={},
        sector_breakdown={},
    )


def _all_positive_portfolio_returns(
    predictions: pd.DataFrame,
    *,
    cost_rate: float,
) -> tuple[pd.Series, pd.Series, float]:
    previous: dict[str, float] = {}
    returns: list[float] = []
    turnover_values: list[float] = []
    total_cost = 0.0
    dates: list[date] = []
    for as_of, group in predictions.groupby("as_of_date", sort=True):
        positive = group.loc[group["expected_excess_return"] > 0].copy()
        if positive.empty:
            weights: dict[str, float] = {}
            realized = 0.0
        else:
            scores = positive["expected_excess_return"].to_numpy(dtype=float)
            denominator = float(scores.sum())
            weights = {
                str(security_id): float(score / denominator)
                for security_id, score in zip(
                    positive["permanent_security_id"], scores, strict=True
                )
            }
            realized = sum(
                weights[str(row.permanent_security_id)] * float(row.forward_excess_return)
                for row in positive.itertuples(index=False)
            )
        turnover = sum(
            abs(weights.get(symbol, 0.0) - previous.get(symbol, 0.0))
            for symbol in set(weights) | set(previous)
        )
        cost = turnover * cost_rate
        returns.append(realized - cost)
        turnover_values.append(turnover)
        total_cost += cost
        previous = weights
        dates.append(pd.Timestamp(as_of).date())
    return (
        pd.Series(returns, index=dates, dtype=float),
        pd.Series(turnover_values, index=dates, dtype=float),
        total_cost,
    )


def _cross_sectional_correlations(frame: pd.DataFrame, *, rank: bool) -> pd.Series:
    values: dict[date, float] = {}
    for as_of, group in frame.groupby("as_of_date", sort=True):
        if len(group) < 5:
            continue
        predicted = group["expected_excess_return"]
        realized = group["forward_excess_return"]
        value = predicted.rank().corr(realized.rank()) if rank else predicted.corr(realized)
        if value is not None and isfinite(float(value)):
            values[pd.Timestamp(as_of).date()] = float(value)
    return pd.Series(values, dtype=float)


def _calibration_buckets(frame: pd.DataFrame) -> tuple[CalibrationBucket, ...]:
    if len(frame) < 10:
        return ()
    ranked = frame["expected_excess_return"].rank(method="first", pct=True)
    buckets: list[CalibrationBucket] = []
    for lower in np.linspace(0.0, 0.8, 5):
        upper = lower + 0.2
        mask = (ranked > lower) & (ranked <= upper)
        group = frame.loc[mask]
        if group.empty:
            continue
        buckets.append(
            CalibrationBucket(
                lower_quantile=float(lower),
                upper_quantile=float(upper),
                predicted_mean=float(group["expected_excess_return"].mean()),
                realized_mean=float(group["forward_excess_return"].mean()),
                count=len(group),
            )
        )
    return tuple(buckets)


def _group_return_breakdown(frame: pd.DataFrame, column: str) -> dict[str, float]:
    return {
        str(name): float(group["forward_excess_return"].mean())
        for name, group in frame.groupby(column, sort=True)
    }


def _cluster_bootstrap_interval(
    returns: pd.Series,
    *,
    annualization: float,
    samples: int,
    seed: int,
) -> tuple[float, float] | None:
    values = returns.to_numpy(dtype=float)
    if not len(values):
        return None
    rng = np.random.default_rng(seed)
    estimates = np.asarray(
        [
            float(rng.choice(values, size=len(values), replace=True).mean() * annualization)
            for _ in range(samples)
        ],
        dtype=float,
    )
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def _maximum_drawdown(returns: np.ndarray) -> float:
    if not len(returns):
        return 0.0
    wealth = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(wealth)
    return float(np.max(1 - wealth / peak))


def _merge_pit_fundamentals(features: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    required = {"permanent_security_id", "available_at"} | set(FUNDAMENTAL_FEATURES)
    missing = required - set(fundamentals.columns)
    if missing:
        raise ValueError(f"PIT fundamentals miss columns: {sorted(missing)}")
    source = fundamentals.copy()
    source["available_at"] = pd.to_datetime(source["available_at"], utc=True, errors="raise")
    merged: list[dict[str, object]] = []
    for row in features.to_dict(orient="records"):
        cutoff = pd.Timestamp(row["decision_cutoff"])
        security_id = str(row["permanent_security_id"])
        available = source.loc[
            (source["permanent_security_id"] == security_id)
            & (source["available_at"] <= cutoff)
        ].sort_values("available_at")
        item = dict(row)
        if not available.empty:
            latest = available.iloc[-1]
            for feature in FUNDAMENTAL_FEATURES:
                item[feature] = _finite_or_nan(latest[feature])
        merged.append(item)
    return pd.DataFrame(merged)


def _ordered_returns(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.asarray([], dtype=float)
    ordered = frame.sort_values(["trade_date", "available_time"]).drop_duplicates(
        "trade_date", keep="last"
    )
    return np.asarray(
        ordered["close"].astype(float).pct_change().dropna().to_numpy(dtype=float),
        dtype=float,
    )


def _price_return(close: np.ndarray, lookback: int) -> float:
    return float(close[-1] / close[-(lookback + 1)] - 1) if len(close) > lookback else np.nan


def _skip_return(close: np.ndarray, lookback: int, skip: int) -> float:
    if len(close) <= lookback or lookback <= skip:
        return np.nan
    return float(close[-(skip + 1)] / close[-(lookback + 1)] - 1)


def _period_return(returns: np.ndarray, lookback: int) -> float:
    values = returns[-lookback:]
    return float(np.prod(1 + values) - 1) if len(values) else 0.0


def _trend_slope(close: np.ndarray, lookback: int) -> tuple[float, float]:
    if len(close) < lookback:
        return np.nan, np.nan
    values = np.log(close[-lookback:])
    x = np.arange(lookback, dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    fitted = intercept + slope * x
    total = float(((values - values.mean()) ** 2).sum())
    residual = float(((values - fitted) ** 2).sum())
    strength = 0.0 if total <= 1e-15 else max(0.0, 1 - residual / total)
    return float(np.expm1(slope * 252)), strength


def _breakout(close: np.ndarray, lookback: int) -> float:
    if len(close) < lookback:
        return np.nan
    maximum = float(np.max(close[-lookback:]))
    return float(close[-1] / maximum - 1) if maximum > 0 else np.nan


def _distance_to_mean(close: np.ndarray, lookback: int) -> float:
    if len(close) < lookback:
        return np.nan
    average = float(np.mean(close[-lookback:]))
    return float(close[-1] / average - 1) if average > 0 else np.nan


def _annualized_volatility(returns: np.ndarray, lookback: int) -> float:
    values = returns[-lookback:]
    return float(np.std(values, ddof=1) * sqrt(252)) if len(values) > 1 else 0.0


def _downside_volatility(returns: np.ndarray, lookback: int) -> float:
    values = returns[-lookback:]
    downside = values[values < 0]
    return float(np.std(downside, ddof=1) * sqrt(252)) if len(downside) > 1 else 0.0


def _beta_and_idiosyncratic(
    returns: np.ndarray,
    benchmark: np.ndarray,
    lookback: int,
) -> tuple[float, float]:
    length = min(len(returns), len(benchmark), lookback)
    if length < 10:
        return np.nan, np.nan
    asset = returns[-length:]
    market = benchmark[-length:]
    variance = float(np.var(market, ddof=1))
    beta = float(np.cov(asset, market, ddof=1)[0, 1] / variance) if variance > 1e-15 else 0.0
    residual = asset - beta * market
    return beta, float(np.std(residual, ddof=1) * sqrt(252))


def _drawdown(close: np.ndarray, lookback: int) -> float:
    values = close[-lookback:]
    maximum = float(np.max(values))
    return float(values[-1] / maximum - 1) if maximum > 0 else np.nan


def _adv(close: np.ndarray, volume: np.ndarray, lookback: int) -> float:
    length = min(len(close), len(volume), lookback)
    return float(np.mean(close[-length:] * volume[-length:])) if length else np.nan


def _turnover_proxy(volume: np.ndarray, market_cap: float, lookback: int) -> float:
    if not len(volume) or not isfinite(market_cap) or market_cap <= 0:
        return np.nan
    return float(np.mean(volume[-lookback:]) / market_cap)


def _gap_behavior(returns: np.ndarray, lookback: int) -> float:
    values = returns[-lookback:]
    return float(np.mean(np.abs(values))) if len(values) else np.nan


def _volatility_of_volatility(returns: np.ndarray, lookback: int) -> float:
    values = pd.Series(returns[-lookback:]).rolling(5).std(ddof=1).dropna()
    return float(values.std(ddof=1) * sqrt(252)) if len(values) > 1 else 0.0


def _finite_or_nan(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if isfinite(number) else np.nan


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    valid = np.isfinite(left) & np.isfinite(right)
    if int(valid.sum()) < 3:
        return 0.0
    left_rank = pd.Series(left[valid]).rank(method="average").to_numpy(dtype=float)
    right_rank = pd.Series(right[valid]).rank(method="average").to_numpy(dtype=float)
    value = float(np.corrcoef(left_rank, right_rank)[0, 1])
    return value if isfinite(value) else 0.0


def _mean_optional(values: Any) -> float | None:
    observed = [float(item) for item in values if item is not None and isfinite(float(item))]
    return float(np.mean(observed)) if observed else None


def _difference_optional(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None
