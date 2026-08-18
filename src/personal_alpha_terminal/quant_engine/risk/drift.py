from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    _correlation_clusters,
    _members_by_label,
)
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    SizeExposureStatus,
    portfolio_volatility,
)


class RiskDriftStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    HARD_BREACH = "HARD_BREACH"


@dataclass(frozen=True, slots=True)
class RiskDriftEvent:
    constraint: str
    actual: float
    limit: float
    status: RiskDriftStatus
    required_action_class: str

    def document(self) -> dict[str, object]:
        return {
            "constraint": self.constraint,
            "actual": self.actual,
            "limit": self.limit,
            "status": self.status.value,
            "required_action_class": self.required_action_class,
        }


@dataclass(frozen=True, slots=True)
class RiskDriftReport:
    status: RiskDriftStatus
    events: tuple[RiskDriftEvent, ...]
    risk_reduction_only: bool

    @property
    def detail(self) -> str:
        if not self.events:
            suffix = " | RISK_REDUCTION_ONLY" if self.risk_reduction_only else ""
            return f"RISK DRIFT: OK{suffix}"
        displayed = self.events[:5]
        rendered = "; ".join(
            f"{item.constraint} actual={item.actual:.6f} limit={item.limit:.6f} "
            f"action={item.required_action_class}"
            for item in displayed
        )
        if len(self.events) > len(displayed):
            rendered = f"{rendered}; +{len(self.events) - len(displayed)} more"
        return f"RISK DRIFT: {self.status.value.replace('_', ' ')} | {rendered}"

    def document(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "risk_reduction_only": self.risk_reduction_only,
            "events": [item.document() for item in self.events],
        }


def evaluate_risk_drift(
    *,
    current_weights: dict[str, float],
    risk: RiskModelEstimate,
    constraints: PortfolioConstraints,
    risk_budget: RiskBudget,
    warning_ratio: float = 0.90,
) -> RiskDriftReport:
    if not 0 < warning_ratio < 1:
        raise ValueError("risk drift warning ratio must be in (0, 1)")
    missing = set(current_weights) - set(risk.symbols)
    if missing:
        event = RiskDriftEvent(
            constraint="RISK_UNIVERSE_COVERAGE",
            actual=float(len(missing)),
            limit=0.0,
            status=RiskDriftStatus.HARD_BREACH,
            required_action_class="BLOCK_AND_REPAIR_DATA",
        )
        return RiskDriftReport(
            RiskDriftStatus.HARD_BREACH,
            (event,),
            not risk_budget.allow_new_risk,
        )

    weights = np.asarray(
        [current_weights.get(symbol, 0.0) for symbol in risk.symbols],
        dtype=float,
    )
    if np.any(~np.isfinite(weights)) or np.any(weights < 0):
        event = RiskDriftEvent(
            constraint="LONG_ONLY_FINITE_WEIGHTS",
            actual=1.0,
            limit=0.0,
            status=RiskDriftStatus.HARD_BREACH,
            required_action_class="BLOCK_AND_REPAIR_DATA",
        )
        return RiskDriftReport(
            RiskDriftStatus.HARD_BREACH,
            (event,),
            not risk_budget.allow_new_risk,
        )

    gross_limit = min(
        constraints.maximum_gross_exposure,
        1 - constraints.minimum_cash_weight,
    ) * risk_budget.gross_exposure_multiplier
    position_limit = constraints.maximum_position_weight * risk_budget.position_cap_multiplier
    volatility_limit = (
        constraints.target_annualized_volatility * risk_budget.volatility_multiplier
    )
    cash_floor = max(constraints.minimum_cash_weight, 1 - gross_limit)
    events: list[RiskDriftEvent] = []

    def upper_event(name: str, actual: float, limit: float) -> None:
        if actual > limit + 1e-8:
            events.append(
                RiskDriftEvent(
                    name,
                    actual,
                    limit,
                    RiskDriftStatus.HARD_BREACH,
                    "RISK_REDUCTION_REQUIRED",
                )
            )
        elif limit > 0 and actual >= limit * warning_ratio:
            events.append(
                RiskDriftEvent(
                    name,
                    actual,
                    limit,
                    RiskDriftStatus.WARNING,
                    "MONITOR",
                )
            )

    gross = float(weights.sum())
    cash = 1 - gross
    upper_event("SINGLE_NAME", float(weights.max(initial=0.0)), position_limit)
    upper_event("GROSS_EXPOSURE", gross, gross_limit)
    if cash < cash_floor - 1e-8:
        events.append(
            RiskDriftEvent(
                "CASH_FLOOR",
                cash,
                cash_floor,
                RiskDriftStatus.HARD_BREACH,
                "RISK_REDUCTION_REQUIRED",
            )
        )
    elif cash <= cash_floor + (1 - warning_ratio) * max(cash_floor, 1e-12):
        events.append(
            RiskDriftEvent(
                "CASH_FLOOR",
                cash,
                cash_floor,
                RiskDriftStatus.WARNING,
                "MONITOR",
            )
        )
    upper_event("HHI", float(weights @ weights), constraints.maximum_hhi)

    sector_members = _members_by_label(risk.symbols, risk.sectors)
    for sector, members in sector_members.items():
        upper_event(
            f"SECTOR:{sector}",
            float(np.sum(weights[list(members)])),
            constraints.maximum_sector_weight,
        )
    cluster_members = _correlation_clusters(
        risk.symbols,
        risk.correlation,
        constraints.correlation_cluster_threshold,
    )
    for cluster, members in cluster_members.items():
        upper_event(
            f"CLUSTER:{cluster}",
            float(np.sum(weights[list(members)])),
            constraints.maximum_cluster_weight,
        )

    beta = np.asarray([risk.beta[symbol] for symbol in risk.symbols], dtype=float)
    portfolio_beta = float(beta @ weights)
    upper_event("BETA_MAX", portfolio_beta, constraints.maximum_beta)
    if portfolio_beta < constraints.minimum_beta - 1e-8:
        events.append(
            RiskDriftEvent(
                "BETA_MIN",
                portfolio_beta,
                constraints.minimum_beta,
                RiskDriftStatus.HARD_BREACH,
                "RISK_REDUCTION_REQUIRED",
            )
        )
    upper_event(
        "ANNUALIZED_VOLATILITY",
        portfolio_volatility(weights, risk.annualized_covariance),
        volatility_limit,
    )
    if risk.size_exposure_status is SizeExposureStatus.VALID:
        sizes = np.asarray([risk.size_scores[symbol] for symbol in risk.symbols], dtype=float)
        upper_event(
            "ABS_SIZE_EXPOSURE",
            abs(float(sizes @ weights)),
            constraints.maximum_size_exposure,
        )

    status = (
        RiskDriftStatus.HARD_BREACH
        if any(item.status is RiskDriftStatus.HARD_BREACH for item in events)
        else RiskDriftStatus.WARNING
        if events
        else RiskDriftStatus.OK
    )
    return RiskDriftReport(status, tuple(events), not risk_budget.allow_new_risk)
