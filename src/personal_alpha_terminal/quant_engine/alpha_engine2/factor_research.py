"""ROUND 8: extended factor research and redundancy diagnostics.

Factor research is exploratory and never grants production status by itself.
Every factor must report an economic rationale, PIT correctness, IC, stability,
turnover and cost-adjusted value.  Redundancy diagnostics (correlation, rank
correlation, marginal IC, incremental portfolio contribution) prevent five
different names for the same momentum signal from entering a composite.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class FactorResearchResult:
    name: str
    economic_rationale: str
    pit_requirement: str
    direction: str
    rank_ic: float | None
    ic_ir: float | None
    positive_ic_ratio: float | None
    turnover: float | None
    cost_adjusted_value: float | None
    stability: float | None
    candidate: bool

    def document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FactorRedundancyReport:
    correlation: dict[str, dict[str, float]]
    rank_correlation: dict[str, dict[str, float]]
    marginal_ic: dict[str, float]
    incremental_contribution: dict[str, float]
    redundant_pairs: tuple[tuple[str, str, float], ...]

    def document(self) -> dict[str, Any]:
        return asdict(self)


FACTOR_CATALOG: tuple[dict[str, str], ...] = (
    {
        "name": "momentum_12_1",
        "rationale": "medium-term price continuation from prior winners",
        "pit": "raw close available_at <= decision cutoff; no future rows",
        "direction": "higher_is_better",
    },
    {
        "name": "trend_slope",
        "rationale": "sustained positive price trend over the lookback window",
        "pit": "raw close available_at <= decision cutoff; no future rows",
        "direction": "higher_is_better",
    },
    {
        "name": "low_volatility",
        "rationale": "defensive low-risk anomaly; lower volatility earns a premium",
        "pit": "raw close available_at <= decision cutoff; no future rows",
        "direction": "lower_is_better",
    },
    {
        "name": "short_term_reversal",
        "rationale": "short-horizon mean reversion after over-reaction",
        "pit": "raw close available_at <= decision cutoff; no future rows",
        "direction": "lower_is_better",
    },
    {
        "name": "residual_momentum",
        "rationale": "momentum orthogonal to market and factor exposures",
        "pit": "requires regression over PIT-available cross-section",
        "direction": "higher_is_better",
    },
    {
        "name": "volatility_regime",
        "rationale": "state-dependent exposure adjustment, never a bull/bear switch",
        "pit": "regime computed from data available at decision cutoff",
        "direction": "risk_budget_only",
    },
    {
        "name": "liquidity",
        "rationale": "illiquidity premium with tradability constraint",
        "pit": "raw dollar volume available_at <= decision cutoff",
        "direction": "lower_is_better",
    },
    {
        "name": "quality",
        "rationale": "PIT filing-vintage quality composite (profitability/robustness)",
        "pit": "filing publication/available_at and revisions required",
        "direction": "higher_is_better",
    },
    {
        "name": "profitability",
        "rationale": "profitable firms outperform after PIT fundamentals",
        "pit": "PIT fundamental vintages required",
        "direction": "higher_is_better",
    },
    {
        "name": "investment",
        "rationale": "asset-growth anomaly; conservative investment earns premium",
        "pit": "PIT fundamental vintages required",
        "direction": "lower_is_better",
    },
    {
        "name": "value",
        "rationale": "cheapness relative to PIT fundamentals",
        "pit": "PIT fundamental vintages required",
        "direction": "lower_is_better",
    },
    {
        "name": "market_breadth",
        "rationale": "cross-sectional participation as an exposure governor",
        "pit": "computed from the PIT cross-section at decision cutoff",
        "direction": "exposure_only",
    },
)


def factor_catalog() -> tuple[dict[str, str], ...]:
    """Return the research factor catalog (never production-eligible by itself)."""
    return FACTOR_CATALOG


def research_factor(
    labeled_panel: pd.DataFrame,
    *,
    name: str,
    signal_column: str,
    direction: str,
    horizon: int,
    cost_rate: float = 0.001,
) -> FactorResearchResult:
    """Evaluate one factor's IC, stability, turnover and cost-adjusted value.

    The labeled panel must already be PIT-safe (no future rows, prices
    available at the decision cutoff).  Stability is the fraction of rebalance
    periods with same-sign IC; cost-adjusted value subtracts the turnover cost
    from the raw top-bottom spread.
    """
    from personal_alpha_terminal.quant_engine.round4_research import evaluate_factor

    evaluation = evaluate_factor(
        labeled_panel,
        signal_column=signal_column,
        forward_return_column="forward_return",
        horizon=horizon,
    )
    panel = labeled_panel.copy()
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"], errors="raise").dt.date
    ic_by_period: dict[object, float] = {}
    for period, group in panel.groupby("as_of_date", sort=True):
        values = pd.to_numeric(group[signal_column], errors="coerce")
        forward = pd.to_numeric(group["forward_return"], errors="coerce")
        valid = pd.DataFrame({"x": values, "y": forward}).dropna()
        if len(valid) >= 5:
            ic_by_period[period] = float(valid["x"].rank().corr(valid["y"].rank()))
    stability = (
        float(sum(1 for value in ic_by_period.values() if value > 0) / len(ic_by_period))
        if ic_by_period
        else None
    )
    top_bottom = evaluation.top_bottom_spread
    cost_adjusted = None
    if top_bottom is not None and evaluation.turnover is not None:
        cost_adjusted = float(top_bottom - cost_rate * evaluation.turnover)
    return FactorResearchResult(
        name=name,
        economic_rationale=next(
            (item["rationale"] for item in FACTOR_CATALOG if item["name"] == name),
            "candidate factor",
        ),
        pit_requirement=next(
            (item["pit"] for item in FACTOR_CATALOG if item["name"] == name),
            "PIT requirement must be declared",
        ),
        direction=direction,
        rank_ic=evaluation.mean_ic,
        ic_ir=evaluation.icir,
        positive_ic_ratio=evaluation.positive_ic_ratio,
        turnover=evaluation.turnover,
        cost_adjusted_value=cost_adjusted,
        stability=stability,
        candidate=bool(
            evaluation.mean_ic is not None
            and evaluation.icir is not None
            and evaluation.icir > 0
            and (stability or 0.0) >= 0.5
        ),
    )


def factor_redundancy(
    labeled_panel: pd.DataFrame,
    *,
    signal_columns: tuple[str, ...],
    threshold: float = 0.85,
) -> FactorRedundancyReport:
    """Correlation / rank-correlation / marginal-IC / incremental-contribution.

    A pair with correlation and rank correlation both above ``threshold`` is
    flagged redundant.  Marginal IC is the rank IC of each factor alone;
    incremental contribution is the rank IC of the factor orthogonalized to the
    rest of the cross-section (partial-out by OLS residuals).
    """
    matrix: dict[str, dict[str, float]] = {name: {} for name in signal_columns}
    rank_matrix: dict[str, dict[str, float]] = {name: {} for name in signal_columns}
    marginal_ic: dict[str, float] = {}
    for name in signal_columns:
        values = pd.to_numeric(labeled_panel[name], errors="coerce")
        forward = pd.to_numeric(labeled_panel["forward_return"], errors="coerce")
        valid = pd.DataFrame({"x": values, "y": forward}).dropna()
        marginal_ic[name] = (
            float(valid["x"].rank().corr(valid["y"].rank()))
            if len(valid) >= 5
            else 0.0
        )
        for other in signal_columns:
            pair = pd.DataFrame(
                {
                    "a": pd.to_numeric(labeled_panel[name], errors="coerce"),
                    "b": pd.to_numeric(labeled_panel[other], errors="coerce"),
                }
            ).dropna()
            matrix[name][other] = float(pair["a"].corr(pair["b"])) if len(pair) else 0.0
            rank_matrix[name][other] = (
                float(pair["a"].rank().corr(pair["b"].rank())) if len(pair) else 0.0
            )
    incremental: dict[str, float] = {}
    for name in signal_columns:
        others = tuple(item for item in signal_columns if item != name)
        if not others:
            incremental[name] = marginal_ic[name]
            continue
        frame = labeled_panel.copy()
        x = pd.to_numeric(frame[name], errors="coerce")
        other_frame = frame[list(others)].apply(pd.to_numeric, errors="coerce")
        combined = pd.concat([x.rename("x"), other_frame, frame["forward_return"]], axis=1)
        combined = combined.replace([np.inf, -np.inf], np.nan).dropna()
        if len(combined) < 5:
            incremental[name] = 0.0
            continue
        design = combined[list(others)].to_numpy(dtype=float)
        residual = combined["x"].to_numpy(dtype=float) - design @ np.linalg.lstsq(
            design, combined["x"].to_numpy(dtype=float), rcond=None
        )[0]
        y = combined["forward_return"].to_numpy(dtype=float)
        incremental[name] = (
            float(np.corrcoef(_rank(residual), _rank(y))[0, 1])
            if len(residual) >= 5
            else 0.0
        )
    redundant_pairs: list[tuple[str, str, float]] = []
    names = sorted(signal_columns)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            corr = abs(matrix[left][right])
            rank = abs(rank_matrix[left][right])
            if corr >= threshold and rank >= threshold:
                redundant_pairs.append((left, right, float(max(corr, rank))))
    redundant_pairs.sort(key=lambda item: -item[2])
    return FactorRedundancyReport(
        correlation=matrix,
        rank_correlation=rank_matrix,
        marginal_ic=marginal_ic,
        incremental_contribution=incremental,
        redundant_pairs=tuple(redundant_pairs),
    )


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(values))
    return order.astype(float)
