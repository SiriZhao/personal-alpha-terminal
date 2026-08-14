"""ROUND24 multi-sleeve architecture definitions.

Sleeves separate the equity alpha path from ETF core and ETF tactical paths.
ETF models are RESEARCH_CANDIDATE models: they never claim historical
certification and they never overwrite the Classical Champion.
"""

from __future__ import annotations

from dataclasses import dataclass

from personal_alpha_terminal.instruments.master import Sleeve

ETF_SLEEVE_MODEL_STATUS = "RESEARCH_CANDIDATE"
ETF_LOOK_THROUGH_STATUS = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SleevePolicy:
    sleeve: Sleeve
    label: str
    rebalance_logic: str
    factor_scope: str
    benchmark_policy: str
    model_status: str = ETF_SLEEVE_MODEL_STATUS


EQUITY_ALPHA_SLEEVE = SleevePolicy(
    sleeve=Sleeve.EQUITY_ALPHA,
    label="EQUITY_ALPHA_SLEEVE",
    rebalance_logic="CLASSICAL_CHAMPION_UNCHANGED",
    factor_scope="USAdaptiveAlphaCoreV1: momentum, trend, volatility (company-price factors)",
    benchmark_policy="SPY / QQQ",
    model_status="CLASSICAL_CHAMPION",
)

ETF_CORE_SLEEVE = SleevePolicy(
    sleeve=Sleeve.ETF_CORE,
    label="ETF_CORE_SLEEVE",
    rebalance_logic="LOW_TURNOVER",
    factor_scope=(
        "long-term trend, medium/long momentum, volatility, drawdown, "
        "liquidity, correlation, diversification contribution, "
        "benchmark-relative behavior"
    ),
    benchmark_policy="per-instrument catalog policy; self-comparison blocked",
)

ETF_TACTICAL_SLEEVE = SleevePolicy(
    sleeve=Sleeve.ETF_TACTICAL,
    label="ETF_TACTICAL_SLEEVE",
    rebalance_logic="TACTICAL_MOMENTUM",
    factor_scope=(
        "relative momentum, trend, volatility, drawdown, relative strength, "
        "correlation, risk-adjusted momentum, portfolio diversification benefit"
    ),
    benchmark_policy="per-instrument catalog policy; self-comparison blocked",
)

SLEEVES = (EQUITY_ALPHA_SLEEVE, ETF_CORE_SLEEVE, ETF_TACTICAL_SLEEVE)

SLEEVE_BY_VALUE = {policy.sleeve: policy for policy in SLEEVES}


def sleeve_label(sleeve: Sleeve) -> str:
    policy = SLEEVE_BY_VALUE.get(sleeve)
    return policy.label if policy else "UNKNOWN_SLEEVE"
