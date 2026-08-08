from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np


@dataclass(frozen=True, slots=True)
class AttributionReport:
    symbol_contribution: dict[str, float]
    sector_contribution: dict[str, float]
    alpha_source_contribution: dict[str, float]
    risk_contribution: dict[str, float]
    regime_adjustment: float
    risk_reduction: float
    transaction_cost_drag: float
    reconciled_total: float


def attribute_portfolio_period(
    *,
    starting_weights: dict[str, float],
    asset_returns: dict[str, float],
    sectors: dict[str, str],
    alpha_source_weights: dict[str, dict[str, float]],
    covariance: np.ndarray,
    symbol_order: tuple[str, ...],
    regime_adjustment: float = 0.0,
    risk_reduction: float = 0.0,
    transaction_cost_drag: float = 0.0,
) -> AttributionReport:
    if set(starting_weights) - set(symbol_order):
        raise ValueError("attribution weights are outside the risk universe")
    symbol = {
        item: starting_weights.get(item, 0.0) * asset_returns.get(item, 0.0)
        for item in symbol_order
    }
    if any(not isfinite(value) for value in symbol.values()):
        raise ValueError("symbol attribution contains non-finite values")
    sector: dict[str, float] = {}
    for item, contribution in symbol.items():
        sector_name = sectors[item]
        sector[sector_name] = sector.get(sector_name, 0.0) + contribution
    alpha_source: dict[str, float] = {}
    for item, contribution in symbol.items():
        sources = alpha_source_weights.get(item, {})
        total = sum(max(0.0, value) for value in sources.values())
        if total <= 0:
            alpha_source["UNATTRIBUTED"] = alpha_source.get("UNATTRIBUTED", 0.0) + contribution
            continue
        for source, value in sources.items():
            alpha_source[source] = alpha_source.get(source, 0.0) + contribution * max(
                0.0, value
            ) / total
    weights = np.array([starting_weights.get(item, 0.0) for item in symbol_order])
    marginal = covariance @ weights
    variance = float(weights @ marginal)
    risk = {
        item: (float(weights[index] * marginal[index] / variance) if variance > 0 else 0.0)
        for index, item in enumerate(symbol_order)
    }
    total = (
        sum(symbol.values())
        + regime_adjustment
        + risk_reduction
        - transaction_cost_drag
    )
    return AttributionReport(
        symbol_contribution=symbol,
        sector_contribution=sector,
        alpha_source_contribution=alpha_source,
        risk_contribution=risk,
        regime_adjustment=regime_adjustment,
        risk_reduction=risk_reduction,
        transaction_cost_drag=transaction_cost_drag,
        reconciled_total=total,
    )
