"""PIT-valid candidate selection feeding the portfolio optimizer.

The full current operational cross-section is factor-ranked and normalized
first. This module applies only existing economic and data-validity filters;
it deliberately has no arbitrary cardinality or Top-N cut. Every rejection is
recorded so the optimizer input remains explainable.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from personal_alpha_terminal.quant_engine.alpha import AlphaDataQuality, AlphaSignal


@dataclass(frozen=True, slots=True)
class CandidateStep:
    name: str
    count: int
    rejected: int
    reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandidateCompression:
    steps: tuple[CandidateStep, ...]
    candidate_symbols: tuple[str, ...]
    minimum_adv: float | None = None

    def document(self) -> dict[str, object]:
        return {
            "steps": [
                {
                    "name": step.name,
                    "count": step.count,
                    "rejected": step.rejected,
                    "reasons": dict(sorted(step.reasons.items())),
                }
                for step in self.steps
            ],
            "candidate_count": len(self.candidate_symbols),
            "candidate_symbols": list(self.candidate_symbols),
            "minimum_adv": self.minimum_adv,
        }


def compress_candidates(
    signals: tuple[AlphaSignal, ...],
    *,
    candidate_min_alpha: float,
    adv_by_symbol: Mapping[str, float] | None = None,
    minimum_adv: float | None = None,
) -> CandidateCompression:
    """Select the complete eligible ranked cross-section.

    Deterministic ordering: expected alpha descending, then symbol.  Nothing
    here reads future information; it only reorders the already-computed PIT
    cross-section.
    """
    steps: list[CandidateStep] = []
    total = len(signals)
    steps.append(CandidateStep("factor_ranked", total, 0, {}))

    positive = tuple(item for item in signals if item.expected_excess_return > 0)
    steps.append(
        CandidateStep(
            "alpha_positive",
            len(positive),
            total - len(positive),
            {"alpha_non_positive": total - len(positive)},
        )
    )

    above = tuple(
        item for item in positive if item.expected_excess_return >= candidate_min_alpha
    )
    steps.append(
        CandidateStep(
            "minimum_alpha",
            len(above),
            len(positive) - len(above),
            {"below_minimum_alpha": len(positive) - len(above)},
        )
    )

    if minimum_adv is not None and adv_by_symbol is not None:
        liquid = tuple(
            item
            for item in above
            if adv_by_symbol.get(item.symbol, 0.0) >= minimum_adv
        )
        steps.append(
            CandidateStep(
                "liquidity",
                len(liquid),
                len(above) - len(liquid),
                {"adv_below_threshold": len(above) - len(liquid)},
            )
        )
    else:
        liquid = above
        steps.append(CandidateStep("liquidity", len(liquid), 0, {"not_resent": 0}))

    risk_screened = tuple(
        item
        for item in liquid
        if item.data_quality is AlphaDataQuality.VALID and item.pit_valid
    )
    steps.append(
        CandidateStep(
            "risk_screening",
            len(risk_screened),
            len(liquid) - len(risk_screened),
            {"risk_invalid": len(liquid) - len(risk_screened)},
        )
    )

    ranked = tuple(
        sorted(risk_screened, key=lambda item: (-item.expected_excess_return, item.symbol))
    )
    steps.append(
        CandidateStep("optimizer_eligible", len(ranked), 0, {})
    )

    return CandidateCompression(
        tuple(steps),
        tuple(item.symbol for item in ranked),
        minimum_adv=minimum_adv,
    )
