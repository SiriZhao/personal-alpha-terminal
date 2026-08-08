from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256

from personal_alpha_terminal.intelligence.schemas import EventEvidence, UnifiedEvent


@dataclass(frozen=True, slots=True)
class DeduplicationConfig:
    maximum_time_distance: timedelta = timedelta(hours=36)
    minimum_headline_similarity: float = 0.55


def headline_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


class CanonicalEventDeduplicator:
    """Deterministic clustering after semantic extraction has normalized type/entity."""

    def __init__(self, config: DeduplicationConfig | None = None) -> None:
        self.config = config or DeduplicationConfig()

    def cluster(self, events: tuple[UnifiedEvent, ...]) -> tuple[UnifiedEvent, ...]:
        canonical: list[UnifiedEvent] = []
        for event in sorted(events, key=lambda item: (item.observed_at, item.event_id)):
            match = self._find_match(canonical, event)
            if match is None:
                canonical.append(
                    event.model_copy(
                        update={
                            "canonical_cluster_id": (
                                event.canonical_cluster_id or _cluster_id(event)
                            )
                        }
                    )
                )
            else:
                canonical[match] = self._merge(canonical[match], event)
        return tuple(canonical)

    def _find_match(self, canonical: list[UnifiedEvent], event: UnifiedEvent) -> int | None:
        for index, candidate in enumerate(canonical):
            same_entity = candidate.entity.casefold() == event.entity.casefold()
            same_type = candidate.event_type is event.event_type
            close_in_time = (
                abs(candidate.effective_at - event.effective_at)
                <= self.config.maximum_time_distance
            )
            similar = (
                headline_similarity(candidate.title, event.title)
                >= self.config.minimum_headline_similarity
            )
            if same_entity and same_type and close_in_time and similar:
                return index
        return None

    @staticmethod
    def _merge(left: UnifiedEvent, right: UnifiedEvent) -> UnifiedEvent:
        left_evidence = tuple(
            item.model_copy(
                update={
                    "extraction_confidence": (
                        item.extraction_confidence
                        if item.extraction_confidence is not None
                        else left.confidence
                    )
                }
            )
            for item in left.evidence
        )
        right_evidence = tuple(
            item.model_copy(
                update={
                    "extraction_confidence": (
                        item.extraction_confidence
                        if item.extraction_confidence is not None
                        else right.confidence
                    )
                }
            )
            for item in right.evidence
        )
        evidence_map: dict[str, EventEvidence] = {
            item.source_hash: item for item in (*left_evidence, *right_evidence)
        }
        evidence = tuple(
            sorted(evidence_map.values(), key=lambda item: (item.observed_at, item.evidence_id))
        )
        distinct_sources = len({item.source for item in evidence})
        cluster_id = left.canonical_cluster_id or _cluster_id(left)
        version_id = sha256(
            "|".join(sorted(evidence_map)).encode()
        ).hexdigest()
        # Source diversity may modestly increase extraction confidence.  It never
        # multiplies direction, magnitude, expected return, or sample count.
        confidence = min(
            max(left.confidence, right.confidence) + 0.02 * (distinct_sources - 1),
            1.0,
        )
        return left.model_copy(
            update={
                "event_id": version_id,
                "published_at": min(left.published_at, right.published_at),
                "observed_at": min(left.observed_at, right.observed_at),
                "ingested_at": max(left.ingested_at, right.ingested_at),
                "created_at": max(left.created_at, right.created_at),
                "data_cutoff": max(left.data_cutoff, right.data_cutoff),
                "evidence": evidence,
                "confidence": confidence,
                "canonical_cluster_id": cluster_id,
                "affected_assets": tuple(
                    sorted(set(left.affected_assets) | set(right.affected_assets))
                ),
                "affected_sectors": tuple(
                    sorted(set(left.affected_sectors) | set(right.affected_sectors))
                ),
                "themes": tuple(sorted(set(left.themes) | set(right.themes))),
            }
        )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1
    }


def _cluster_id(event: UnifiedEvent) -> str:
    payload = (
        f"{event.entity.casefold()}|{event.event_type}|{event.effective_at.isoformat()}"
    )
    return sha256(payload.encode()).hexdigest()[:24]
