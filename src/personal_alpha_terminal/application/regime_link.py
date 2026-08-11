"""Read-only link between the persisted market-regime evidence and the pipeline.

The regime engine is an OPTIONAL analytical overlay.  This module never
computes a regime score itself; it only restores what a completed, persisted
``MarketRegimeService`` run already recorded.  The core pipeline is protected:

- no recorded run (or nothing available at the decision cutoff) -> regime input
  is ``None`` and nothing downstream changes;
- a ``score_only`` run never becomes a ``RegimeRiskInput`` — an uncalibrated
  score cannot modify alpha, position sizing or risk limits;
- only a walk-forward calibrated run whose latest point-in-time observation
  carries validated probabilities is allowed to feed the risk budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from personal_alpha_terminal.analysis.market_regime.repository import (
    MarketRegimeRepository,
)
from personal_alpha_terminal.analysis.market_regime.service import MarketRegimeService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.quant_engine.risk.budget import RegimeRiskInput

REGIME_UNAVAILABLE = "REGIME_OPTIONAL_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RegimeLinkResult:
    regime_input: RegimeRiskInput | None
    display_status: str
    detail: str


def latest_regime_link(
    session: Session,
    settings: Settings,
    *,
    decision_time: datetime,
) -> RegimeLinkResult:
    """Restore the latest PIT-available regime evidence, fail-closed."""

    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    try:
        result = MarketRegimeService(
            MarketRegimeRepository(session), settings
        ).latest()
    except (LookupError, ValueError):
        return RegimeLinkResult(
            None,
            REGIME_UNAVAILABLE,
            "REGIME OPTIONAL: no readable market-regime run; core pipeline unaffected.",
        )
    if result is None:
        return RegimeLinkResult(
            None,
            REGIME_UNAVAILABLE,
            "REGIME OPTIONAL: no market-regime run recorded; core pipeline unaffected.",
        )
    cutoff = decision_time.date()
    point = next(
        (item for item in reversed(result.observations) if item.as_of_date <= cutoff),
        None,
    )
    if point is None:
        return RegimeLinkResult(
            None,
            REGIME_UNAVAILABLE,
            "REGIME OPTIONAL: no regime observation available at the decision cutoff.",
        )
    calibration = result.calibration
    if calibration.status != "calibrated":
        return RegimeLinkResult(
            None,
            f"REGIME_OPTIONAL_{point.regime.upper()}_SCORE_ONLY",
            (
                f"REGIME OPTIONAL: score-only state '{point.regime}' "
                f"(composite {point.composite_score:.3f}); uncalibrated scores never "
                "change alpha, position sizing or risk limits."
            ),
        )
    probabilities = point.probabilities
    if probabilities is None:
        return RegimeLinkResult(
            None,
            f"REGIME_OPTIONAL_{point.regime.upper()}_SCORE_ONLY",
            (
                f"REGIME OPTIONAL: calibrated run but no validated probabilities at "
                f"{point.as_of_date.isoformat()}; regime stays advisory."
            ),
        )
    regime_input = RegimeRiskInput(
        risk_on_probability=probabilities["risk_on"],
        neutral_probability=probabilities["neutral"],
        risk_off_probability=probabilities["risk_off"],
        confidence=1.0,
        calibrated=True,
        model_version=result.model_version,
    )
    brier = (
        f"; OOS Brier {calibration.brier_score:.4f}"
        if calibration.brier_score is not None
        else ""
    )
    return RegimeLinkResult(
        regime_input,
        f"REGIME_CALIBRATED_{point.regime.upper()}",
        (
            f"REGIME: walk-forward calibrated '{point.regime}' at "
            f"{point.as_of_date.isoformat()}{brier}; only a calibrated probability "
            "may reduce the risk budget, never alpha."
        ),
    )
