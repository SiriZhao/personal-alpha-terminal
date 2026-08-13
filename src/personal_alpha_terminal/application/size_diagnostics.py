"""PIT-safe size exposure and size-tilt diagnostics.

These values are observational diagnostics only.  They do not alter Alpha,
factor selection, portfolio constraints, or risk calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    SizeExposureStatus,
)

_BUCKETS = (
    ("micro_cap", 0.0, 300_000_000.0),
    ("small_cap", 300_000_000.0, 2_000_000_000.0),
    ("mid_cap", 2_000_000_000.0, 10_000_000_000.0),
    ("large_cap", 10_000_000_000.0, 200_000_000_000.0),
    ("mega_cap", 200_000_000_000.0, float("inf")),
)


@dataclass(frozen=True, slots=True)
class WeightedDistribution:
    weighted_average: float | None
    weighted_median: float | None
    percentile: float | None
    bucket_counts: dict[str, int]
    largest_bucket_weight: tuple[str, float] | None
    small_micro_exposure: float | None
    smallest_value: float | None


def build_size_tilt_diagnostic(
    risk: RiskModelEstimate,
    *,
    candidate_symbols: tuple[str, ...],
    target_weights: dict[str, float],
    portfolio_value: float,
    transaction_cost: TransactionCostConfig,
    expected_transaction_cost: float,
) -> dict[str, object]:
    candidates = tuple(item for item in candidate_symbols if item in risk.market_caps)
    market_cap_valid_count = len(candidates)
    market_cap_missing_count = len(candidate_symbols) - market_cap_valid_count
    coverage_ratio = (
        market_cap_valid_count / len(candidate_symbols)
        if candidate_symbols
        else 0.0
    )
    candidate_distribution = _distribution(
        {
            symbol: risk.market_caps[symbol]
            for symbol in candidates
        },
        weights={
            symbol: 1.0 / len(candidates) if candidates else 0.0
            for symbol in candidates
        },
    )
    final_values = {
        symbol: risk.market_caps[symbol]
        for symbol, weight in target_weights.items()
        if weight > 0 and symbol in risk.market_caps
    }
    final_distribution = _distribution(final_values, target_weights)
    adv_values = {
        symbol: risk.average_daily_dollar_volume[symbol]
        for symbol in candidate_symbols
        if isfinite(risk.average_daily_dollar_volume.get(symbol, float("nan")))
        and risk.average_daily_dollar_volume[symbol] > 0
    }
    liquidity_percentile = _weighted_percentile(
        risk.average_daily_dollar_volume,
        target_weights,
        eligible=candidate_symbols,
    )
    impact_bps = (
        expected_transaction_cost / portfolio_value * 10_000
        if portfolio_value > 0
        else None
    )
    status = (
        "SIZE_EXPOSURE_VALIDATED"
        if risk.size_exposure_status is SizeExposureStatus.VALID
        and market_cap_missing_count == 0
        else "SIZE_EXPOSURE_UNAVAILABLE"
        if market_cap_valid_count == 0
        else "SIZE_EXPOSURE_DEGRADED"
    )
    return {
        "status": status,
        "optimizer_input_count": len(candidate_symbols),
        "market_cap_valid_count": market_cap_valid_count,
        "market_cap_missing_count": market_cap_missing_count,
        "coverage_ratio": coverage_ratio,
        "candidate_weighted_average_market_cap": candidate_distribution.weighted_average,
        "candidate_weighted_median_market_cap": candidate_distribution.weighted_median,
        "candidate_weighted_size_percentile": candidate_distribution.percentile,
        "portfolio_weighted_average_market_cap": final_distribution.weighted_average,
        "portfolio_weighted_median_market_cap": final_distribution.weighted_median,
        "portfolio_weighted_size_percentile": final_distribution.percentile,
        "candidate_size_bucket_counts": candidate_distribution.bucket_counts,
        "final_size_bucket_concentration": (
            final_distribution.largest_bucket_weight[0]
            if final_distribution.largest_bucket_weight
            else "N/A"
        ),
        "final_largest_size_bucket_weight": (
            final_distribution.largest_bucket_weight[1]
            if final_distribution.largest_bucket_weight
            else None
        ),
        "final_small_micro_exposure": final_distribution.small_micro_exposure,
        "smallest_holding_market_cap": final_distribution.smallest_value,
        "liquidity_percentile": liquidity_percentile,
        "average_daily_dollar_volume": (
            sum(adv_values.values()) / len(adv_values)
            if adv_values
            else None
        ),
        "spread_proxy_bps": transaction_cost.spread_bps,
        "expected_market_impact_bps": impact_bps,
        "missing_market_cap_symbols": tuple(
            symbol for symbol in candidate_symbols if symbol not in risk.market_caps
        ),
    }


def _distribution(
    values: dict[str, float],
    weights: dict[str, float],
) -> WeightedDistribution:
    valid = tuple(
        (symbol, float(value))
        for symbol, value in values.items()
        if value is not None and isfinite(value) and value > 0
    )
    if not valid:
        return WeightedDistribution(None, None, None, {}, None, None, None)
    weight_total = sum(max(0.0, weights.get(symbol, 0.0)) for symbol, _ in valid)
    if weight_total <= 0:
        equal = 1.0 / len(valid)
        pairs = tuple((symbol, value, equal) for symbol, value in valid)
    else:
        pairs = tuple(
            (symbol, value, max(0.0, weights.get(symbol, 0.0)) / weight_total)
            for symbol, value in valid
        )
    ordered = tuple(sorted(pairs, key=lambda item: item[1]))
    caps = [item[1] for item in ordered]
    bucket_counts = {name: 0 for name, _, _ in _BUCKETS}
    bucket_weights = {name: 0.0 for name, _, _ in _BUCKETS}
    small_micro = 0.0
    smallest = ordered[0][1]
    weighted_sum = 0.0
    for _symbol, value, weight in ordered:
        weighted_sum += value * weight
        for name, lower, upper in _BUCKETS:
            if lower <= value < upper:
                bucket_counts[name] += 1
                bucket_weights[name] += weight
                if name in {"micro_cap", "small_cap"}:
                    small_micro += weight
                break
    weighted_median = _weighted_median(ordered)
    percentile = _rank_percentile(caps, weighted_sum) if ordered else None
    largest_name, largest_weight = max(
        bucket_weights.items(), key=lambda item: item[1], default=("N/A", 0.0)
    )
    return WeightedDistribution(
        weighted_average=weighted_sum,
        weighted_median=weighted_median,
        percentile=percentile,
        bucket_counts=bucket_counts,
        largest_bucket_weight=(
            (largest_name, largest_weight) if largest_weight > 0 else None
        ),
        small_micro_exposure=small_micro,
        smallest_value=smallest,
    )


def _weighted_median(pairs: tuple[tuple[str, float, float], ...]) -> float | None:
    if not pairs:
        return None
    cumulative = 0.0
    for _symbol, value, weight in pairs:
        cumulative += weight
        if cumulative >= 0.5:
            return value
    return pairs[-1][1]


def _weighted_percentile(
    values_by_symbol: dict[str, float],
    weights: dict[str, float],
    *,
    eligible: tuple[str, ...],
) -> float | None:
    valid = tuple(
        symbol
        for symbol in eligible
        if symbol in values_by_symbol
        and isfinite(values_by_symbol[symbol])
        and values_by_symbol[symbol] > 0
    )
    if len(valid) < 2:
        return None
    ordered = tuple(sorted(valid, key=lambda symbol: values_by_symbol[symbol]))
    ranks = {symbol: index / (len(ordered) - 1) for index, symbol in enumerate(ordered)}
    total = sum(max(0.0, weights.get(symbol, 0.0)) for symbol in ordered)
    if total <= 0:
        return None
    return sum(
        max(0.0, weights.get(symbol, 0.0)) / total * ranks[symbol]
        for symbol in ordered
    )


def _rank_percentile(values: list[float], value: float) -> float | None:
    if len(values) < 2 or value <= 0:
        return None
    sorted_values = sorted(values)
    rank = next(
        (index for index, item in enumerate(sorted_values) if item >= value),
        len(sorted_values) - 1,
    )
    return rank / (len(sorted_values) - 1)
