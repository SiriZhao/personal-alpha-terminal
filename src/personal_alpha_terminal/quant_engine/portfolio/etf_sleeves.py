"""ROUND24 ETF sleeves portfolio construction (C5-C10).

ETF sleeve targets are RESEARCH_CANDIDATE outputs.  Budgets are risk-control
caps (diversification budget), not return tuning.  The composer reports joint
stock/ETF risk and correlation-cluster overlap; constituent look-through is
honestly marked UNAVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from personal_alpha_terminal.instruments.sleeves import ETF_LOOK_THROUGH_STATUS
from personal_alpha_terminal.quant_engine.factors.etf_factors import (
    ETF_METRIC_SEMANTIC_CONTRACT,
    METRIC_KIND_PERCENT,
    EtfFactorSnapshot,
    core_sleeve_eligible,
    tactical_sleeve_eligible,
)


@dataclass(frozen=True, slots=True)
class EtfSleeveConfig:
    """Risk-control budget caps for the ETF sleeves."""

    core_budget: float = 0.25
    tactical_budget: float = 0.10
    max_single_etf_weight: float = 0.10
    minimum_cash_weight: float = 0.05
    maximum_adv_participation: float = 0.05
    no_trade_band: float = 0.0025
    minimum_core_positions: int = 1
    maximum_core_positions: int = 4
    maximum_tactical_positions: int = 4
    correlation_overlap_threshold: float = 0.70
    minimum_trend_consistency: float = 0.3
    maximum_core_drawdown: float = 0.25
    model_version: str = "etf-sleeves-v1"

    def fingerprint(self) -> str:
        import json
        from hashlib import sha256

        payload = {key: getattr(self, key) for key in (
            "core_budget", "tactical_budget", "max_single_etf_weight",
            "minimum_cash_weight", "maximum_adv_participation", "no_trade_band",
            "minimum_core_positions", "maximum_core_positions",
            "maximum_tactical_positions", "correlation_overlap_threshold",
            "minimum_trend_consistency", "maximum_core_drawdown",
            "model_version",
        )}
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EtfSleeveTarget:
    symbol: str
    sleeve: str
    target_weight: float
    current_weight: float
    delta_weight: float
    eligibility: tuple[str, ...]
    eligible: bool
    # ROUND25 PHASE 2: the former ``expected_value`` was the factor ratio
    # risk_adjusted_momentum = momentum(252,21) / annualized_vol(63).  It is a
    # dimensionless momentum-to-volatility ratio, NOT an expected alpha and
    # NOT a percentage.  It is now stored under its true name and unit.
    momentum_vol_ratio: float | None
    rationale: str
    model_version: str
    momentum_252_21: float | None = None
    annualized_volatility: float | None = None
    model_status: str = "RESEARCH_CANDIDATE"
    # Explicit semantic-domain and trading-permission annotations (ROUND25 P0).
    domain: str = "RESEARCH_CANDIDATE"
    trading_permission: str = "NONE"

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "sleeve": self.sleeve,
            "target_weight": self.target_weight,
            "current_weight": self.current_weight,
            "delta_weight": self.delta_weight,
            "eligibility": list(self.eligibility),
            "eligible": self.eligible,
            "momentum_vol_ratio": self.momentum_vol_ratio,
            "momentum_252_21": self.momentum_252_21,
            "annualized_volatility": self.annualized_volatility,
            "metric_semantics": {
                "momentum_252_21": ETF_METRIC_SEMANTIC_CONTRACT["momentum_252_21"],
                "momentum_vol_ratio": ETF_METRIC_SEMANTIC_CONTRACT[
                    "risk_adjusted_momentum"
                ],
                "annualized_volatility": ETF_METRIC_SEMANTIC_CONTRACT[
                    "volatility_63"
                ],
                "target_weight": {
                    "kind": METRIC_KIND_PERCENT,
                    "definition": "portfolio weight expressed as a decimal (0.07 == 7%)",
                },
            },
            "rationale": self.rationale,
            "model_version": self.model_version,
            "model_status": self.model_status,
            "domain": self.domain,
            "trading_permission": self.trading_permission,
            "not_part_of_execution_plan": True,
        }


@dataclass(frozen=True, slots=True)
class OverlapReport:
    status: str
    look_through: str
    max_etf_stock_correlation: dict[str, float]
    etf_etf_correlations: dict[str, float]
    overlapping_clusters: tuple[str, ...]
    warnings: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "look_through": self.look_through,
            "max_etf_stock_correlation": self.max_etf_stock_correlation,
            "etf_etf_correlations": self.etf_etf_correlations,
            "overlapping_clusters": list(self.overlapping_clusters),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class MultiSleeveComposition:
    equity_weights: dict[str, float]
    etf_weights: dict[str, float]
    combined_weights: dict[str, float]
    combined_gross: float
    cash_weight: float
    largest_single_name: float
    single_name_violations: tuple[str, ...]
    gross_budget_applied: float
    scaled_back: bool
    overlap: OverlapReport
    sector_proxy_exposure: dict[str, float]
    sector_exposure_status: str
    model_version: str

    def document(self) -> dict[str, object]:
        return {
            "equity_weights": self.equity_weights,
            "etf_weights": self.etf_weights,
            "combined_weights": self.combined_weights,
            "combined_gross": self.combined_gross,
            "cash_weight": self.cash_weight,
            "largest_single_name": self.largest_single_name,
            "single_name_violations": list(self.single_name_violations),
            "gross_budget_applied": self.gross_budget_applied,
            "scaled_back": self.scaled_back,
            "overlap": self.overlap.document(),
            "sector_proxy_exposure": self.sector_proxy_exposure,
            "sector_exposure_status": self.sector_exposure_status,
            "model_version": self.model_version,
        }


def build_etf_targets(
    factors: tuple[EtfFactorSnapshot, ...],
    *,
    sleeve: str,
    current_weights: dict[str, float],
    portfolio_value: float,
    decision_time: datetime,
    config: EtfSleeveConfig | None = None,
    benchmark_policy: dict[str, str] | None = None,
) -> tuple[EtfSleeveTarget, ...]:
    """Build core or tactical ETF targets under the configured risk budget."""

    configured = config or EtfSleeveConfig()
    if decision_time.tzinfo is None:
        raise ValueError("ETF sleeve decision_time must be timezone-aware")
    if portfolio_value <= 0:
        raise ValueError("ETF sleeve requires a positive portfolio value")
    budget = (
        configured.core_budget
        if sleeve == "ETF_CORE"
        else configured.tactical_budget
    )
    max_positions = (
        configured.maximum_core_positions
        if sleeve == "ETF_CORE"
        else configured.maximum_tactical_positions
    )
    eligible: list[EtfFactorSnapshot] = []
    ineligible_reasons: dict[str, tuple[str, ...]] = {}
    for snapshot in factors:
        if sleeve == "ETF_CORE":
            ok, reasons = core_sleeve_eligible(
                snapshot,
                minimum_trend_consistency=configured.minimum_trend_consistency,
                maximum_drawdown=configured.maximum_core_drawdown,
            )
        else:
            ok, reasons = tactical_sleeve_eligible(snapshot)
        if ok:
            eligible.append(snapshot)
        else:
            ineligible_reasons[snapshot.symbol] = reasons
    inverse_vol = {
        item.symbol: (  # noqa: E501
            1.0 / item.volatility_63
            if item.volatility_63 and item.volatility_63 > 0
            else 0.0
        )
        for item in eligible
    }
    ranking = sorted(
        eligible,
        key=lambda item: (
            item.risk_adjusted_momentum
            if item.risk_adjusted_momentum is not None
            else float("-inf")
        ),
        reverse=True,
    )[:max_positions]
    raw_weights: dict[str, float] = {}
    denominator = sum(inverse_vol.get(item.symbol, 0.0) for item in ranking)
    for item in ranking:
        if denominator <= 0:
            break
        raw_weights[item.symbol] = (  # noqa: E501
            budget * inverse_vol[item.symbol] / denominator
        )
    total = sum(raw_weights.values())
    if total > budget and budget > 0:
        scale = budget / total
        raw_weights = {symbol: weight * scale for symbol, weight in raw_weights.items()}
    targets: list[EtfSleeveTarget] = []
    for symbol, weight in sorted(raw_weights.items()):
        current = current_weights.get(symbol, 0.0)
        capped = min(weight, configured.max_single_etf_weight)
        if sleeve == "ETF_CORE" and abs(capped - current) <= configured.no_trade_band:
            capped = current
        delta = capped - current
        snapshot = next(item for item in factors if item.symbol == symbol)
        momentum_252_21 = (
            float(snapshot.momentum_252_21)
            if snapshot.momentum_252_21 is not None
            else None
        )
        annualized_volatility = (
            float(snapshot.volatility_63) if snapshot.volatility_63 is not None else None
        )
        momentum_vol_ratio = (
            float(snapshot.risk_adjusted_momentum)
            if snapshot.risk_adjusted_momentum is not None
            else None
        )
        targets.append(
            EtfSleeveTarget(
                symbol=symbol,
                sleeve=sleeve,
                target_weight=round(capped, 8),
                current_weight=round(current, 8),
                delta_weight=round(delta, 8),
                eligibility=(),
                eligible=True,
                momentum_vol_ratio=(
                    round(momentum_vol_ratio, 6)
                    if momentum_vol_ratio is not None
                    else None
                ),
                momentum_252_21=(
                    round(momentum_252_21, 6) if momentum_252_21 is not None else None
                ),
                annualized_volatility=(
                    round(annualized_volatility, 6)
                    if annualized_volatility is not None
                    else None
                ),
                rationale=(
                    "risk-parity within sleeve budget; low-turnover band applied"
                    if sleeve == "ETF_CORE"
                    else "risk-adjusted momentum rank within tactical budget"
                ),
                model_version=configured.model_version,
            )
        )
    selected = set(raw_weights)
    for snapshot in eligible:
        if snapshot.symbol in selected:
            continue
        momentum_vol_ratio = (
            float(snapshot.risk_adjusted_momentum)
            if snapshot.risk_adjusted_momentum is not None
            else None
        )
        momentum_252_21 = (
            float(snapshot.momentum_252_21)
            if snapshot.momentum_252_21 is not None
            else None
        )
        annualized_volatility = (
            float(snapshot.volatility_63) if snapshot.volatility_63 is not None else None
        )
        targets.append(
            EtfSleeveTarget(
                symbol=snapshot.symbol,
                sleeve=sleeve,
                target_weight=0.0,
                current_weight=current_weights.get(snapshot.symbol, 0.0),
                delta_weight=-current_weights.get(snapshot.symbol, 0.0),
                eligibility=(),
                eligible=True,
                momentum_vol_ratio=(
                    round(momentum_vol_ratio, 6)
                    if momentum_vol_ratio is not None
                    else None
                ),
                momentum_252_21=(
                    round(momentum_252_21, 6) if momentum_252_21 is not None else None
                ),
                annualized_volatility=(
                    round(annualized_volatility, 6)
                    if annualized_volatility is not None
                    else None
                ),
                rationale="eligible but excluded by rank within sleeve budget",
                model_version=configured.model_version,
            )
        )
    for symbol, reasons in sorted(ineligible_reasons.items()):
        targets.append(
            EtfSleeveTarget(
                symbol=symbol,
                sleeve=sleeve,
                target_weight=0.0,
                current_weight=current_weights.get(symbol, 0.0),
                delta_weight=-current_weights.get(symbol, 0.0),
                eligibility=reasons,
                eligible=False,
                momentum_vol_ratio=None,
                momentum_252_21=None,
                annualized_volatility=None,
                rationale="excluded by ETF sleeve eligibility",
                model_version=configured.model_version,
            )
        )
    return tuple(targets)


def compose_multi_sleeve(
    *,
    equity_weights: dict[str, float],
    etf_weights: dict[str, float],
    returns: dict[str, pd.Series],
    portfolio_value: float,
    config: EtfSleeveConfig | None = None,
    sector_proxy: dict[str, str] | None = None,
) -> MultiSleeveComposition:
    """Combine sleeves and report joint risk / overlap honestly."""

    configured = config or EtfSleeveConfig()
    etf_total = sum(weight for weight in etf_weights.values() if weight > 0)
    gross_limit = 1.0 - configured.minimum_cash_weight
    budget = min(configured.core_budget + configured.tactical_budget, gross_limit)
    scaled_back = etf_total > budget
    if scaled_back and etf_total > 0:
        scale = budget / etf_total
        etf_weights = {symbol: weight * scale for symbol, weight in etf_weights.items()}
    combined = dict(equity_weights)
    for symbol, weight in etf_weights.items():
        combined[symbol] = combined.get(symbol, 0.0) + weight
    combined_gross = sum(weight for weight in combined.values() if weight > 0)
    cash_weight = max(0.0, 1.0 - combined_gross)
    largest = max((weight for weight in combined.values() if weight > 0), default=0.0)
    single_name_violations = tuple(
        symbol
        for symbol, weight in combined.items()
        if weight > configured.max_single_etf_weight and symbol in etf_weights
    )
    available = {symbol: series for symbol, series in returns.items() if series is not None}
    overlap_warnings: list[str] = []
    max_etf_stock_correlation: dict[str, float] = {}
    etf_etf_correlations: dict[str, float] = {}
    overlapping_clusters: list[str] = []
    for etf, etf_weight in sorted(etf_weights.items()):
        if etf_weight <= 0 or etf not in available:
            continue
        stock_correlations = []
        for stock, stock_weight in sorted(equity_weights.items()):
            if stock_weight <= 0 or stock not in available:
                continue
            aligned = pd.concat(
                [available[etf], available[stock]], axis=1, join="inner"
            ).dropna()
            if len(aligned) < 60:
                continue
            corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            stock_correlations.append((stock, corr))
        if stock_correlations:
            max_pair = max(stock_correlations, key=lambda pair: pair[1])
            max_etf_stock_correlation[etf] = round(max_pair[1], 4)
            if max_pair[1] >= configured.correlation_overlap_threshold:
                overlap_warnings.append(
                    f"{etf} overlaps equity {max_pair[0]} "
                    f"(corr={max_pair[1]:.2f}); look-through UNAVAILABLE"
                )
        other_etf_corrs = []
        for other, other_weight in sorted(etf_weights.items()):
            if other == etf or other_weight <= 0 or other not in available:
                continue
            aligned = pd.concat(
                [available[etf], available[other]], axis=1, join="inner"
            ).dropna()
            if len(aligned) < 60:
                continue
            corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            other_etf_corrs.append((other, corr))
        if other_etf_corrs:
            max_other = max(other_etf_corrs, key=lambda pair: pair[1])
            etf_etf_correlations[f"{etf}/{max_other[0]}"] = round(max_other[1], 4)
            if max_other[1] >= configured.correlation_overlap_threshold:
                overlapping_clusters.append(f"{etf}+{max_other[0]}")
    sector_exposure: dict[str, float] = {}
    sector_validated = True
    for symbol, weight in combined.items():
        if weight <= 0:
            continue
        label = (sector_proxy or {}).get(symbol)
        if label is None:
            sector_validated = False
            continue
        sector_exposure[label] = sector_exposure.get(label, 0.0) + weight
    overlap = OverlapReport(
        status=(
            "OVERLAP_WARNING" if overlap_warnings or overlapping_clusters else "NO_OVERLAP_DETECTED"
        ),
        look_through=ETF_LOOK_THROUGH_STATUS,
        max_etf_stock_correlation=max_etf_stock_correlation,
        etf_etf_correlations=etf_etf_correlations,
        overlapping_clusters=tuple(overlapping_clusters),
        warnings=tuple(overlap_warnings),
    )
    return MultiSleeveComposition(
        equity_weights=dict(sorted(equity_weights.items())),
        etf_weights=dict(sorted(etf_weights.items())),
        combined_weights=dict(sorted(combined.items())),
        combined_gross=round(combined_gross, 8),
        cash_weight=round(cash_weight, 8),
        largest_single_name=round(largest, 8),
        single_name_violations=single_name_violations,
        gross_budget_applied=round(budget, 8),
        scaled_back=scaled_back,
        overlap=overlap,
        sector_proxy_exposure={
            key: round(value, 6) for key, value in sorted(sector_exposure.items())
        },
        sector_exposure_status=(
            "SECTOR_EXPOSURE_VALIDATED"
            if sector_validated and sector_exposure
            else "SECTOR_EXPOSURE_NOT_VALIDATED"
        ),
        model_version=configured.model_version,
    )
