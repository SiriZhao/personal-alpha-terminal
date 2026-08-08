from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from personal_alpha_terminal.terminal.market_sessions import MarketSession
from personal_alpha_terminal.terminal.quality import DataSafetyGate, DataSafetyStatus


class ExecutionStatus(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ExecutionInputs:
    action: str
    session: MarketSession
    data_safety: DataSafetyStatus
    price: float | None
    spread_rate: float | None
    average_daily_dollar_volume: float | None
    order_value: float
    annualized_volatility: float | None
    estimated_slippage_rate: float | None
    portfolio_exposure_after: float


@dataclass(frozen=True, slots=True)
class ExecutionAssessment:
    status: ExecutionStatus
    recommended_order_type: str
    recommended_session: str
    estimated_cost_rate: float | None
    reasons: tuple[str, ...]


class ExecutionFeasibilityEngine:
    """Conservative feasibility screen; it never submits a broker order."""

    def __init__(
        self,
        *,
        max_regular_spread: float = 0.01,
        max_extended_spread: float = 0.005,
        max_adv_participation: float = 0.01,
        max_portfolio_exposure: float = 1.0,
    ) -> None:
        self.max_regular_spread = max_regular_spread
        self.max_extended_spread = max_extended_spread
        self.max_adv_participation = max_adv_participation
        self.max_portfolio_exposure = max_portfolio_exposure
        self._gate = DataSafetyGate()

    def assess(self, inputs: ExecutionInputs) -> ExecutionAssessment:
        reasons: list[str] = []
        action = inputs.action.upper()
        if not self._gate.permits(action, inputs.data_safety):
            reasons.append("data safety gate does not permit an executable action")
        if inputs.session is MarketSession.NIGHT:
            reasons.append("night session is information-only; manual execution is disabled")
        elif inputs.session is not MarketSession.REGULAR:
            reasons.append(
                "wait for the regular session unless an independently reviewed limit plan exists"
            )
        if inputs.price is None or not isfinite(inputs.price) or inputs.price <= 0:
            reasons.append("valid reference price is unavailable")
        if inputs.portfolio_exposure_after > self.max_portfolio_exposure:
            reasons.append("post-trade portfolio exposure exceeds the configured limit")
        if inputs.average_daily_dollar_volume is None or inputs.average_daily_dollar_volume <= 0:
            reasons.append("ADV is unavailable")
        elif (
            abs(inputs.order_value) / inputs.average_daily_dollar_volume
            > self.max_adv_participation
        ):
            reasons.append("estimated participation exceeds the ADV limit")
        spread_limit = (
            self.max_regular_spread
            if inputs.session is MarketSession.REGULAR
            else self.max_extended_spread
        )
        if inputs.spread_rate is None:
            reasons.append("spread is unavailable")
        elif inputs.spread_rate > spread_limit:
            reasons.append("spread exceeds the session-specific limit")
        if inputs.estimated_slippage_rate is None:
            reasons.append("slippage estimate is unavailable")
        if inputs.annualized_volatility is None:
            reasons.append("volatility estimate is unavailable")

        hard_block = any(
            phrase in reason
            for reason in reasons
            for phrase in (
                "data safety gate",
                "reference price",
                "portfolio exposure",
                "ADV limit",
            )
        )
        if action in {"HOLD", "WATCH", "NO ACTION"}:
            status = ExecutionStatus.WAIT
        elif hard_block:
            status = ExecutionStatus.BLOCKED
        elif reasons:
            status = ExecutionStatus.WAIT
        else:
            status = ExecutionStatus.EXECUTABLE
        cost = None
        if inputs.spread_rate is not None and inputs.estimated_slippage_rate is not None:
            cost = inputs.spread_rate / 2 + inputs.estimated_slippage_rate
        return ExecutionAssessment(
            status,
            "LIMIT_FIRST",
            "REGULAR",
            cost,
            tuple(reasons) or ("all configured execution checks passed",),
        )
