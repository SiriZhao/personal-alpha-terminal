from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ChallengerStatus(StrEnum):
    SHADOW = "SHADOW"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class ChampionChallengerIdentity:
    """Immutable identity shared by both arms of a valid experiment.

    A promotion is only meaningful when both arms consume the same research
    dataset, universe, benchmark, transaction-cost model, portfolio/risk
    constraints and frozen locked-OOS definition. The sole allowed variable is
    the candidate LLM feature contribution.
    """

    research_data_version: str
    universe_version: str
    benchmark: str
    cost_model_version: str
    portfolio_constraint_hash: str
    risk_model_hash: str
    locked_oos_definition_hash: str


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
    data_version: str | None = None
    universe_version: str | None = None
    benchmark: str | None = None
    cost_model_version: str | None = None
    portfolio_constraint_hash: str | None = None
    risk_model_hash: str | None = None
    locked_oos_definition_hash: str | None = None


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
    identity: ChampionChallengerIdentity | None = None,
) -> ChampionChallengerEvidence:
    blockers: list[str] = []
    not_certifiable = False
    if not research_data_certified:
        blockers.append("RESEARCH_MARKET_DATA_NOT_CERTIFIED")
        not_certifiable = True
    if not text_pit_certified:
        blockers.append("HISTORICAL_TEXT_PIT_NOT_CERTIFIED")
        not_certifiable = True
    if not locked_oos_opened:
        blockers.append("LOCKED_OOS_NOT_OPENED")
        not_certifiable = True
    if champion is None or challenger is None:
        blockers.append("CHAMPION_CHALLENGER_OOS_EVIDENCE_UNAVAILABLE")
        not_certifiable = True
    if identity is None:
        blockers.append("COMPARISON_IDENTITY_INCOMPLETE")
        not_certifiable = True
    elif any(not value.strip() for value in asdict(identity).values()):
        blockers.append("COMPARISON_IDENTITY_INCOMPLETE")
        not_certifiable = True
    if champion is not None and champion.observations < 252:
        blockers.append("CHAMPION_LOCKED_OOS_SAMPLE_INSUFFICIENT")
        not_certifiable = True
    if challenger is not None and challenger.observations < 252:
        blockers.append("CHALLENGER_LOCKED_OOS_SAMPLE_INSUFFICIENT")
        not_certifiable = True
    if champion is not None and challenger is not None:
        required = (
            champion.rank_ic,
            champion.net_excess_return,
            champion.turnover,
            champion.transaction_cost,
            champion.max_drawdown,
            champion.brier_score,
            champion.log_loss,
            challenger.rank_ic,
            challenger.net_excess_return,
            challenger.turnover,
            challenger.transaction_cost,
            challenger.max_drawdown,
            challenger.brier_score,
            challenger.log_loss,
        )
        if any(item is None for item in required):
            blockers.append("CHAMPION_CHALLENGER_METRICS_INCOMPLETE")
            not_certifiable = True
        elif identity is not None:
            champion_identity = _metric_identity(champion)
            challenger_identity = _metric_identity(challenger)
            expected = (
                identity.research_data_version,
                identity.universe_version,
                identity.benchmark,
                identity.cost_model_version,
                identity.portfolio_constraint_hash,
                identity.risk_model_hash,
                identity.locked_oos_definition_hash,
            )
            if champion_identity != expected or challenger_identity != expected:
                blockers.append("COMPARISON_IDENTITY_MISMATCH")
                not_certifiable = True
    if not_certifiable:
        return ChampionChallengerEvidence(
            champion,
            challenger,
            ChallengerStatus.NOT_CERTIFIABLE,
            tuple(blockers),
            False,
        )
    assert champion is not None and challenger is not None
    assert identity is not None
    assert champion.rank_ic is not None
    assert champion.net_excess_return is not None
    assert champion.max_drawdown is not None
    assert champion.brier_score is not None
    assert champion.log_loss is not None
    assert challenger.rank_ic is not None
    assert challenger.net_excess_return is not None
    assert challenger.max_drawdown is not None
    assert challenger.brier_score is not None
    assert challenger.log_loss is not None
    approved = (
        challenger.net_excess_return > champion.net_excess_return
        and challenger.rank_ic > champion.rank_ic
        and challenger.max_drawdown >= champion.max_drawdown
        and challenger.brier_score <= champion.brier_score
        and challenger.log_loss <= champion.log_loss
    )
    return ChampionChallengerEvidence(
        champion,
        challenger,
        ChallengerStatus.PRODUCTION_APPROVED if approved else ChallengerStatus.REJECTED,
        () if approved else ("NO_STABLE_AFTER_COST_INCREMENTAL_ALPHA",),
        approved,
    )


def _metric_identity(metrics: OOSMetrics) -> tuple[str | None, ...]:
    return (
        metrics.data_version,
        metrics.universe_version,
        metrics.benchmark,
        metrics.cost_model_version,
        metrics.portfolio_constraint_hash,
        metrics.risk_model_hash,
        metrics.locked_oos_definition_hash,
    )
