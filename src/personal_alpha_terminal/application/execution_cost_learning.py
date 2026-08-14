"""ROUND25 PHASE 15: REALIZED_EXECUTION_COST_OBSERVATION (research only).

Once real ``mark-executed`` fills exist, each fill is paired with its order's
decision reference price and planned quantity to compute realized slippage and
fees.  This is observational research: the production cost model is never
updated automatically.  With enough samples the module only emits
``COST_MODEL_RECALIBRATION_CANDIDATE`` for human approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import ManualExecutionFill, ManualExecutionOrder

MINIMUM_SAMPLES_FOR_RECALIBRATION = 20


@dataclass(frozen=True, slots=True)
class CostObservation:
    recommendation_id: str
    symbol: str
    side: str
    decision_price: float
    planned_quantity: float
    fill_price: float
    fill_quantity: float
    fee: float
    slippage_bps: float
    executed_at: str

    def document(self) -> dict[str, object]:
        return {
            "recommendation_id": self.recommendation_id,
            "symbol": self.symbol,
            "side": self.side,
            "decision_price": self.decision_price,
            "planned_quantity": self.planned_quantity,
            "fill_price": self.fill_price,
            "fill_quantity": self.fill_quantity,
            "fee": self.fee,
            "slippage_bps": round(self.slippage_bps, 4),
            "executed_at": self.executed_at,
        }


def _slippage_bps(side: str, decision_price: float, fill_price: float) -> float:
    if decision_price <= 0:
        return 0.0
    signed = (fill_price / decision_price - 1.0) * 10_000.0
    return signed if side == "BUY" else -signed


def collect_cost_observations(session: Session) -> tuple[CostObservation, ...]:
    rows = session.execute(
        select(
            ManualExecutionFill,
            ManualExecutionOrder.expected_price,
            ManualExecutionOrder.approved_quantity,
        )
        .join(ManualExecutionOrder, ManualExecutionOrder.id == ManualExecutionFill.order_id)
        .order_by(ManualExecutionFill.executed_at, ManualExecutionFill.id)
    ).all()
    observations: list[CostObservation] = []
    for fill, expected_price, approved_quantity in rows:
        observations.append(
            CostObservation(
                recommendation_id=fill.recommendation_id,
                symbol=fill.symbol,
                side=fill.side,
                decision_price=float(expected_price),
                planned_quantity=float(approved_quantity),
                fill_price=float(fill.price),
                fill_quantity=float(fill.quantity),
                fee=float(fill.fee),
                slippage_bps=_slippage_bps(
                    fill.side, float(expected_price), float(fill.price)
                ),
                executed_at=fill.executed_at.isoformat(),
            )
        )
    return tuple(observations)


def summarize_cost_observations(
    observations: tuple[CostObservation, ...],
) -> dict[str, object]:
    if not observations:
        return {
            "status": "NO_REALIZED_EXECUTION_OBSERVATIONS",
            "sample_size": 0,
            "production_cost_model_updated": False,
            "recalibration_candidate": False,
        }
    slippage = [item.slippage_bps for item in observations]
    fees = [item.fee for item in observations]
    candidate = len(observations) >= MINIMUM_SAMPLES_FOR_RECALIBRATION
    return {
        "status": (
            "COST_MODEL_RECALIBRATION_CANDIDATE"
            if candidate
            else "REALIZED_EXECUTION_COST_OBSERVATION"
        ),
        "sample_size": len(observations),
        "mean_slippage_bps": round(mean(slippage), 4),
        "median_slippage_bps": round(median(slippage), 4),
        "worst_slippage_bps": round(max(slippage), 4),
        "best_slippage_bps": round(min(slippage), 4),
        "total_fees_usd": round(sum(fees), 4),
        "production_cost_model_updated": False,
        "recalibration_candidate": candidate,
        "recalibration_requires_human_approval": True,
    }


def execution_cost_evidence(session: Session) -> dict[str, object]:
    observations = collect_cost_observations(session)
    summary = summarize_cost_observations(observations)
    return {
        "summary": summary,
        "observations": [item.document() for item in observations],
        "research_only": True,
    }
