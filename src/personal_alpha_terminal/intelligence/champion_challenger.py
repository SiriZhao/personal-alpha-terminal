from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChallengerStatus(StrEnum):
    SHADOW = "SHADOW"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class OOSMetrics:
    observations: int
    rank_ic: float | None
    net_excess_return: float | None
    turnover: float | None
    transaction_cost: float | None
    max_drawdown: float | None
    brier_score: float | None
    log_loss: float | None


@dataclass(frozen=True, slots=True)
class ChampionChallengerEvidence:
    champion: OOSMetrics | None
    challenger: OOSMetrics | None
    status: ChallengerStatus
    blockers: tuple[str, ...]
    llm_can_affect_production: bool


def evaluate_challenger(
    *,
    research_data_certified: bool,
    text_pit_certified: bool,
    locked_oos_opened: bool,
    champion: OOSMetrics | None,
    challenger: OOSMetrics | None,
) -> ChampionChallengerEvidence:
    blockers: list[str] = []
    if not research_data_certified:
        blockers.append("RESEARCH_MARKET_DATA_NOT_CERTIFIED")
    if not text_pit_certified:
        blockers.append("HISTORICAL_TEXT_PIT_NOT_CERTIFIED")
    if not locked_oos_opened:
        blockers.append("LOCKED_OOS_NOT_OPENED")
    if champion is None or challenger is None:
        blockers.append("CHAMPION_CHALLENGER_OOS_EVIDENCE_UNAVAILABLE")
    if challenger is not None and challenger.observations < 252:
        blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
    if blockers:
        return ChampionChallengerEvidence(
            champion,
            challenger,
            ChallengerStatus.NOT_CERTIFIABLE,
            tuple(blockers),
            False,
        )
    assert champion is not None and challenger is not None
    approved = (
        challenger.net_excess_return is not None
        and champion.net_excess_return is not None
        and challenger.net_excess_return > champion.net_excess_return
        and challenger.rank_ic is not None
        and champion.rank_ic is not None
        and challenger.rank_ic > champion.rank_ic
        and challenger.max_drawdown is not None
        and champion.max_drawdown is not None
        and challenger.max_drawdown >= champion.max_drawdown
    )
    return ChampionChallengerEvidence(
        champion,
        challenger,
        ChallengerStatus.PRODUCTION_APPROVED if approved else ChallengerStatus.REJECTED,
        () if approved else ("NO_STABLE_AFTER_COST_INCREMENTAL_ALPHA",),
        approved,
    )
