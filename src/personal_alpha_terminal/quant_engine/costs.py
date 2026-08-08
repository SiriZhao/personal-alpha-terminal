from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt


@dataclass(frozen=True, slots=True)
class TransactionCostConfig:
    commission_bps: float = 0.5
    spread_bps: float = 4.0
    slippage_bps: float = 3.0
    impact_coefficient_bps: float = 10.0
    maximum_adv_participation: float = 0.02
    version: str = "us-daily-cost-v1"

    def __post_init__(self) -> None:
        numeric = (
            self.commission_bps,
            self.spread_bps,
            self.slippage_bps,
            self.impact_coefficient_bps,
            self.maximum_adv_participation,
        )
        if any(not isfinite(value) or value < 0 for value in numeric):
            raise ValueError("transaction cost parameters must be finite and non-negative")
        if not 0 < self.maximum_adv_participation <= 1:
            raise ValueError("maximum ADV participation must be in (0, 1]")
        if not self.version.strip():
            raise ValueError("transaction cost model version is required")


@dataclass(frozen=True, slots=True)
class TransactionCostEstimate:
    trade_value: float
    commission: float
    spread: float
    slippage: float
    market_impact: float
    total_cost: float
    participation_rate: float
    all_in_rate: float
    model_version: str


class TransactionCostModel:
    """Conservative daily-bar cost model shared by optimizer and trade generator."""

    def __init__(self, config: TransactionCostConfig | None = None) -> None:
        self.config = config or TransactionCostConfig()

    @property
    def conservative_rate(self) -> float:
        base = (
            self.config.commission_bps
            + self.config.spread_bps / 2
            + self.config.slippage_bps
            + self.config.impact_coefficient_bps
            * sqrt(self.config.maximum_adv_participation)
        )
        return base / 10_000

    def estimate(
        self, *, trade_value: float, average_daily_dollar_volume: float
    ) -> TransactionCostEstimate:
        if not isfinite(trade_value) or trade_value < 0:
            raise ValueError("trade value must be finite and non-negative")
        if not isfinite(average_daily_dollar_volume) or average_daily_dollar_volume <= 0:
            raise ValueError("known positive ADV is required for transaction-cost estimation")
        participation = trade_value / average_daily_dollar_volume
        if participation > self.config.maximum_adv_participation + 1e-12:
            raise ValueError("trade exceeds configured ADV participation limit")
        commission = trade_value * self.config.commission_bps / 10_000
        spread = trade_value * (self.config.spread_bps / 2) / 10_000
        slippage = trade_value * self.config.slippage_bps / 10_000
        impact = (
            trade_value
            * self.config.impact_coefficient_bps
            * sqrt(max(participation, 0.0))
            / 10_000
        )
        total = commission + spread + slippage + impact
        return TransactionCostEstimate(
            trade_value=trade_value,
            commission=commission,
            spread=spread,
            slippage=slippage,
            market_impact=impact,
            total_cost=total,
            participation_rate=participation,
            all_in_rate=(total / trade_value if trade_value else 0.0),
            model_version=self.config.version,
        )
