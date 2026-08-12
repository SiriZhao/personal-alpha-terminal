"""ROUND 9: LLM shadow research.

Runs Classical vs Classical + LLM Shadow Feature with a strict OOS split.  If
the LLM shadow feature adds no incremental value, the LLM stays explanation /
research-assistant only.  Nothing here promotes a shadow feature to production.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ShadowResearchVerdict(StrEnum):
    INCREMENTAL_VALUE = "INCREMENTAL_VALUE"
    NO_INCREMENTAL_VALUE = "NO_INCREMENTAL_VALUE"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class ShadowResearchResult:
    verdict: ShadowResearchVerdict
    classical_oos_net_return: float | None
    combined_oos_net_return: float | None
    oos_rank_ic_delta: float | None
    oos_sharpe_delta: float | None
    sample_size: int
    blockers: tuple[str, ...]
    feature_name: str

    def document(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "classical_oos_net_return": self.classical_oos_net_return,
            "combined_oos_net_return": self.combined_oos_net_return,
            "oos_rank_ic_delta": self.oos_rank_ic_delta,
            "oos_sharpe_delta": self.oos_sharpe_delta,
            "sample_size": self.sample_size,
            "blockers": list(self.blockers),
            "feature_name": self.feature_name,
        }


def evaluate_llm_shadow_research(
    *,
    feature_name: str,
    classical_oos_net_return: float | None,
    combined_oos_net_return: float | None,
    classical_oos_rank_ic: float | None,
    combined_oos_rank_ic: float | None,
    classical_oos_sharpe: float | None,
    combined_oos_sharpe: float | None,
    sample_size: int,
    min_sample_size: int = 252,
    min_rank_ic_delta: float = 0.01,
    min_sharpe_delta: float = 0.05,
) -> ShadowResearchResult:
    """Strict OOS comparison of Classical vs Classical + LLM shadow feature.

    The combined arm must improve net return, rank IC and Sharpe on the frozen
    OOS sample.  Any missing evidence or insufficient sample blocks the verdict.
    """
    if not feature_name.strip():
        raise ValueError("shadow feature name is required")
    if sample_size < min_sample_size:
        return ShadowResearchResult(
            verdict=ShadowResearchVerdict.NOT_CERTIFIABLE,
            classical_oos_net_return=classical_oos_net_return,
            combined_oos_net_return=combined_oos_net_return,
            oos_rank_ic_delta=None,
            oos_sharpe_delta=None,
            sample_size=sample_size,
            blockers=(f"OOS_SAMPLE_INSUFFICIENT:{sample_size}<{min_sample_size}",),
            feature_name=feature_name,
        )
    required = (
        classical_oos_net_return,
        combined_oos_net_return,
        classical_oos_rank_ic,
        combined_oos_rank_ic,
        classical_oos_sharpe,
        combined_oos_sharpe,
    )
    if any(value is None for value in required):
        return ShadowResearchResult(
            verdict=ShadowResearchVerdict.NOT_CERTIFIABLE,
            classical_oos_net_return=classical_oos_net_return,
            combined_oos_net_return=combined_oos_net_return,
            oos_rank_ic_delta=None,
            oos_sharpe_delta=None,
            sample_size=sample_size,
            blockers=("OOS_EVIDENCE_INCOMPLETE",),
            feature_name=feature_name,
        )
    assert combined_oos_net_return is not None
    assert combined_oos_rank_ic is not None
    assert combined_oos_sharpe is not None
    assert classical_oos_net_return is not None
    assert classical_oos_rank_ic is not None
    assert classical_oos_sharpe is not None
    ic_delta = combined_oos_rank_ic - classical_oos_rank_ic
    sharpe_delta = combined_oos_sharpe - classical_oos_sharpe
    has_value = bool(
        combined_oos_net_return > classical_oos_net_return
        and ic_delta >= min_rank_ic_delta
        and sharpe_delta >= min_sharpe_delta
    )
    return ShadowResearchResult(
        verdict=(
            ShadowResearchVerdict.INCREMENTAL_VALUE
            if has_value
            else ShadowResearchVerdict.NO_INCREMENTAL_VALUE
        ),
        classical_oos_net_return=classical_oos_net_return,
        combined_oos_net_return=combined_oos_net_return,
        oos_rank_ic_delta=ic_delta,
        oos_sharpe_delta=sharpe_delta,
        sample_size=sample_size,
        blockers=() if has_value else ("NO_INCREMENTAL_VALUE",),
        feature_name=feature_name,
    )
