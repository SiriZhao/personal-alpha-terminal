"""ROUND24 Alpha 2.0 research agenda (PHASE E).

Price-only research candidates that may eventually upgrade the long-term
risk-adjusted return.  Fundamentals-based factors are scaffolded but
explicitly BLOCKED_BY_PIT_FUNDAMENTALS.  No candidate is auto-promoted:
promotion requires PIT, purged walk-forward, embargo, locked OOS, cost,
SPY/QQQ benchmark and stress evidence (E2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MODEL_VERSION = "round24-alpha-research-agenda-v1"


class CandidateStatus(StrEnum):
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    BLOCKED_BY_PIT_FUNDAMENTALS = "BLOCKED_BY_PIT_FUNDAMENTALS"
    ALPHA_PROMOTION_CANDIDATE = "ALPHA_PROMOTION_CANDIDATE"


@dataclass(frozen=True, slots=True)
class AlphaResearchCandidate:
    name: str
    description: str
    price_only: bool
    status: CandidateStatus
    data_requirement: str
    promotion_gates: tuple[str, ...]
    relationship_to_existing: str

    def document(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "price_only": self.price_only,
            "status": self.status.value,
            "data_requirement": self.data_requirement,
            "promotion_gates": list(self.promotion_gates),
            "relationship_to_existing": self.relationship_to_existing,
        }


PROMOTION_GATES = (
    "PIT_VERIFICATION",
    "PURGED_WALK_FORWARD",
    "EMBARGO",
    "LOCKED_OOS",
    "COST_ANALYSIS",
    "SPY_QQQ_BENCHMARK",
    "STRESS_EXAM",
)

CANDIDATES: tuple[AlphaResearchCandidate, ...] = (
    AlphaResearchCandidate(
        "residual_momentum",
        (
            "Momentum of residuals against a market/beta proxy; "
            "reduces factor crowding in broad momentum."
        ),
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (252+ sessions)",
        PROMOTION_GATES,
        "de-correlated variant of existing momentum",
    ),
    AlphaResearchCandidate(
        "volatility_managed_momentum",
        "Momentum scaled by realized volatility; aims to smooth drawdowns.",
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (252+ sessions)",
        PROMOTION_GATES,
        "A/B against champion momentum only",
    ),
    AlphaResearchCandidate(
        "trend_strength",
        (  # noqa: E501
            "Slope + consistency (R2) composite; already used by champion "
            "trend, formalized as standalone candidate."
        ),
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (126+ sessions)",
        PROMOTION_GATES,
        "formalizes existing trend factor",
    ),
    AlphaResearchCandidate(
        "short_term_reversal",
        (
            "One-month reversal; high-turnover by nature, "
            "must clear cost gates before any promotion."
        ),
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (60+ sessions)",
        PROMOTION_GATES,
        "negatively correlated with momentum; diversification benefit",
    ),
    AlphaResearchCandidate(
        "idiosyncratic_volatility",
        "Residual volatility after removing market factor; risk-control flavor.",
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (63+ sessions)",
        PROMOTION_GATES,
        "overlaps low-volatility champion factor; correlation must be measured",
    ),
    AlphaResearchCandidate(
        "liquidity_factor",
        (  # noqa: E501
            "Amihud-style illiquidity / ADV percentile; cost sensitive."
        ),
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price + volume (63+ sessions)",
        PROMOTION_GATES,
        "new source of risk premium evidence",
    ),
    AlphaResearchCandidate(
        "cross_sectional_breadth",
        "Universe-level breadth as timing/overlay signal, not a stock selector.",
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "universe price only",
        PROMOTION_GATES,
        "portfolio-level overlay; never selects stocks",
    ),
    AlphaResearchCandidate(
        "relative_strength",
        "Momentum relative to SPY/QQQ benchmark.",
        True,
        CandidateStatus.RESEARCH_CANDIDATE,
        "price only (252 sessions)",
        PROMOTION_GATES,
        "benchmark-relative momentum; correlation with momentum must be measured",
    ),
    AlphaResearchCandidate(
        "value",
        "Book/earnings-to-price; requires PIT fundamental history.",
        False,
        CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS,
        "PIT fundamentals (unavailable)",
        PROMOTION_GATES,
        "blocked until PIT fundamentals exist",
    ),
    AlphaResearchCandidate(
        "quality",
        "Profitability/leverage quality; requires PIT fundamental history.",
        False,
        CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS,
        "PIT fundamentals (unavailable)",
        PROMOTION_GATES,
        "blocked until PIT fundamentals exist",
    ),
    AlphaResearchCandidate(
        "profitability",
        "Gross/operating profitability; requires PIT fundamental history.",
        False,
        CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS,
        "PIT fundamentals (unavailable)",
        PROMOTION_GATES,
        "blocked until PIT fundamentals exist",
    ),
    AlphaResearchCandidate(
        "earnings_revision",
        "Analyst revision momentum; requires PIT estimate history.",
        False,
        CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS,
        "PIT estimates (unavailable)",
        PROMOTION_GATES,
        "blocked until PIT estimate history exists",
    ),
    AlphaResearchCandidate(
        "fundamental_growth",
        "Revenue/earnings growth; requires PIT fundamental history.",
        False,
        CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS,
        "PIT fundamentals (unavailable)",
        PROMOTION_GATES,
        "blocked until PIT fundamentals exist",
    ),
)


def research_agenda_document() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "promotion_gates": list(PROMOTION_GATES),
        "candidates": [item.document() for item in CANDIDATES],
        "auto_promotion": False,
        "classical_champion_unchanged": True,
    }
