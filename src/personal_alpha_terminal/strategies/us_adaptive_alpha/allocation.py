from __future__ import annotations

from collections import defaultdict

from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    AllocationAsset,
    AllocationResult,
)


def allocate_assets(
    assets: tuple[AllocationAsset, ...],
    *,
    method: str,
    maximum_invested_weight: float = 0.80,
    maximum_asset_weight: float = 0.05,
    turnover_penalty: float = 0.25,
) -> AllocationResult:
    """Compare simple robust allocation methods without estimating expected returns."""

    if not assets:
        return AllocationResult(method, {}, 1.0, 0.0, ("no eligible assets",))
    if len({item.symbol for item in assets}) != len(assets):
        raise ValueError("assets must have unique symbols")
    if not 0 <= maximum_invested_weight <= 1 or not 0 < maximum_asset_weight <= 1:
        raise ValueError("allocation limits are invalid")
    if not 0 <= turnover_penalty <= 1:
        raise ValueError("turnover_penalty must be in [0, 1]")
    for item in assets:
        if item.volatility <= 0 or not 0 <= item.current_weight <= 1:
            raise ValueError("volatility must be positive and current weights valid")

    if method == "equal_weight":
        raw = {item.symbol: 1.0 for item in assets}
    elif method == "score_bucket_equal":
        threshold = sorted(item.score for item in assets)[len(assets) // 2]
        selected = tuple(item for item in assets if item.score >= threshold)
        raw = {item.symbol: 1.0 for item in selected}
    elif method == "inverse_volatility":
        raw = {item.symbol: 1 / item.volatility for item in assets}
    elif method == "cluster_risk":
        by_cluster: defaultdict[str, list[AllocationAsset]] = defaultdict(list)
        for item in assets:
            by_cluster[item.cluster].append(item)
        raw = {}
        for members in by_cluster.values():
            denominator = sum(1 / item.volatility for item in members)
            for item in members:
                raw[item.symbol] = (1 / len(by_cluster)) * (1 / item.volatility) / denominator
    elif method == "regularized_risk_budget":
        inverse = {item.symbol: 1 / item.volatility for item in assets}
        inverse_total = sum(inverse.values())
        equal = 1 / len(assets)
        raw = {
            item.symbol: (
                0.5 * equal
                + 0.5 * inverse[item.symbol] / inverse_total
            )
            * (1 - turnover_penalty)
            + item.current_weight * turnover_penalty
            for item in assets
        }
    else:
        raise ValueError(f"unsupported allocation method: {method}")

    normalized = _cap_and_redistribute(
        raw,
        target=maximum_invested_weight,
        cap=maximum_asset_weight,
    )
    current = {item.symbol: item.current_weight for item in assets}
    turnover = sum(
        abs(normalized.get(symbol, 0.0) - current.get(symbol, 0.0))
        for symbol in set(normalized) | set(current)
    )
    invested = sum(normalized.values())
    warnings: list[str] = []
    if invested < maximum_invested_weight - 1e-10:
        warnings.append("asset caps leave part of the risk budget in cash")
    if method == "regularized_risk_budget":
        warnings.append("regularization blends equal, inverse-volatility and current weights")
    return AllocationResult(
        method=method,
        weights=normalized,
        cash_weight=max(0.0, 1 - invested),
        turnover=turnover,
        warnings=tuple(warnings),
    )


def _cap_and_redistribute(
    raw: dict[str, float],
    *,
    target: float,
    cap: float,
) -> dict[str, float]:
    positive = {key: max(0.0, float(value)) for key, value in raw.items() if value > 0}
    if not positive or target <= 0:
        return {}
    weights = {key: target * value / sum(positive.values()) for key, value in positive.items()}
    fixed: set[str] = set()
    for _ in range(len(weights) + 1):
        breaches = {key for key, value in weights.items() if value > cap + 1e-12}
        new = breaches - fixed
        if not new:
            break
        fixed |= new
        for key in fixed:
            weights[key] = cap
        remaining = max(0.0, target - sum(weights[key] for key in fixed))
        flexible = [key for key in weights if key not in fixed]
        denominator = sum(positive[key] for key in flexible)
        if not flexible or denominator <= 0:
            break
        for key in flexible:
            weights[key] = remaining * positive[key] / denominator
    return {key: value for key, value in weights.items() if value > 1e-14}
