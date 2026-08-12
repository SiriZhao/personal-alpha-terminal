from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from personal_alpha_terminal.intelligence.factor_registry import (
    CrossSectionalEventFactorEngine,
    LLMFactorObservation,
)
from personal_alpha_terminal.intelligence.schemas import RawInformation, UnifiedEvent, _aware


class HistoricalAIReplayStatus(StrEnum):
    READY = "READY"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class HistoricalAIReplayResult:
    cutoff: datetime
    visible_document_ids: tuple[str, ...]
    visible_document_versions: tuple[str, ...]
    visible_event_ids: tuple[str, ...]
    factor_observations: tuple[LLMFactorObservation, ...]
    status: HistoricalAIReplayStatus
    blockers: tuple[str, ...]
    replay_hash: str


class HistoricalAIReplay:
    """Reconstruct only the information set available at a historical cutoff."""

    def __init__(self, factor_engine: CrossSectionalEventFactorEngine) -> None:
        self.factor_engine = factor_engine

    def run(
        self,
        *,
        cutoff: datetime,
        documents: tuple[RawInformation, ...],
        events: tuple[UnifiedEvent, ...],
        eligible_symbols: tuple[str, ...],
        sector_by_symbol: dict[str, str],
        market_data_certified: bool,
        text_data_certified: bool,
    ) -> HistoricalAIReplayResult:
        _aware(cutoff, "cutoff")
        visible_documents = tuple(
            sorted(
                (item for item in documents if item.visible_at(cutoff)),
                key=lambda item: item.raw_id,
            )
        )
        visible_events = tuple(
            item_at_cutoff
            for item in events
            if (item_at_cutoff := item.at_cutoff(cutoff)) is not None
        )
        factors = self.factor_engine.build(
            visible_events,
            as_of=cutoff,
            eligible_symbols=eligible_symbols,
            sector_by_symbol=sector_by_symbol,
        )
        blockers: list[str] = []
        if not market_data_certified:
            blockers.append("RESEARCH_MARKET_DATA_NOT_CERTIFIED")
        if not text_data_certified:
            blockers.append("HISTORICAL_TEXT_PIT_NOT_CERTIFIED")
        if not visible_documents:
            blockers.append("NO_VISIBLE_CERTIFIED_DOCUMENTS")
        identity = "|".join(
            (
                cutoff.isoformat(),
                *(
                    f"{item.document_id}|{item.revision_id or ''}|{item.raw_id}"
                    for item in visible_documents
                ),
                *(item.event_id for item in visible_events),
                *(item.observation_hash for item in factors),
                *blockers,
            )
        )
        return HistoricalAIReplayResult(
            cutoff=cutoff,
            visible_document_ids=tuple(item.raw_id for item in visible_documents),
            visible_document_versions=tuple(
                f"{item.document_id}|{item.revision_id or ''}|{item.raw_id}"
                for item in visible_documents
            ),
            visible_event_ids=tuple(item.event_id for item in visible_events),
            factor_observations=factors,
            status=(
                HistoricalAIReplayStatus.NOT_CERTIFIABLE
                if blockers
                else HistoricalAIReplayStatus.READY
            ),
            blockers=tuple(blockers),
            replay_hash=sha256(identity.encode()).hexdigest(),
        )
