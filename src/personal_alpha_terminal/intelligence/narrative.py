from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import exp, isfinite, log, tanh

from pydantic import Field

from personal_alpha_terminal.intelligence.research import ResearchFeatureStatus
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    StrictModel,
    UnifiedEvent,
    _aware,
)


class NarrativeSnapshot(StrictModel):
    narrative_id: str
    schema_version: str = "narrative-schema-v1"
    name: str
    strength: float = Field(ge=0, le=1)
    momentum: float = Field(ge=-1, le=1)
    acceleration: float = Field(ge=-1, le=1)
    source_diversity: float = Field(ge=0, le=1)
    entity_breadth: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    persistence: float = Field(ge=0, le=1)
    sentiment: float = Field(ge=-1, le=1)
    sentiment_change: float = Field(ge=-2, le=2)
    first_seen: datetime
    last_seen: datetime
    decay_score: float = Field(ge=0, le=1)
    data_cutoff: datetime
    event_ids: tuple[str, ...]
    evidence_references: tuple[str, ...]
    model_version: str
    taxonomy_version: str
    backtest_safety: BacktestSafety

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        for name, value in (
            ("first_seen", self.first_seen),
            ("last_seen", self.last_seen),
            ("data_cutoff", self.data_cutoff),
        ):
            _aware(value, name)
        if self.first_seen > self.last_seen or self.last_seen > self.data_cutoff:
            raise ValueError("narrative timestamps violate the PIT boundary")
        if not self.event_ids or not self.evidence_references:
            raise ValueError("narrative requires materialized event evidence")


class NarrativeAssetExposure(StrictModel):
    exposure_id: str
    narrative_id: str
    symbol: str
    exposure_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[str, ...]
    source: str
    last_updated: datetime
    data_cutoff: datetime
    decay_score: float = Field(ge=0, le=1)
    backtest_safety: BacktestSafety

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _aware(self.last_updated, "last_updated")
        _aware(self.data_cutoff, "data_cutoff")
        if self.last_updated > self.data_cutoff:
            raise ValueError("narrative exposure contains a future mapping")
        if not self.evidence:
            raise ValueError("narrative exposure requires evidence")


class NarrativeMomentumFeature(StrictModel):
    feature_id: str
    narrative_id: str
    symbol: str
    value: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    status: ResearchFeatureStatus = ResearchFeatureStatus.RESEARCH_ONLY
    observed_at: datetime
    data_cutoff: datetime
    model_version: str
    backtest_safety: BacktestSafety

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _aware(self.observed_at, "observed_at")
        _aware(self.data_cutoff, "data_cutoff")
        if self.observed_at > self.data_cutoff:
            raise ValueError("narrative momentum is not observable at cutoff")


@dataclass(frozen=True, slots=True)
class NarrativeConfig:
    half_life_days: float = 14.0
    momentum_window_days: int = 7
    maximum_single_event_strength: float = 0.25
    minimum_emerging_sources: int = 2
    source_diversity_target: int = 3
    entity_breadth_target: int = 5
    persistence_target_days: int = 30
    taxonomy_version: str = "narrative-taxonomy-v1"
    model_version: str = "deterministic-narrative-engine-v1"

    def __post_init__(self) -> None:
        if self.half_life_days <= 0 or self.momentum_window_days < 1:
            raise ValueError("narrative decay and momentum windows must be positive")
        if not 0 < self.maximum_single_event_strength <= 0.5:
            raise ValueError("single-event narrative strength cap is unsafe")
        if min(
            self.minimum_emerging_sources,
            self.source_diversity_target,
            self.entity_breadth_target,
            self.persistence_target_days,
        ) < 1:
            raise ValueError("narrative breadth and persistence targets must be positive")


@dataclass(frozen=True, slots=True)
class NarrativeResult:
    narratives: tuple[NarrativeSnapshot, ...]
    exposures: tuple[NarrativeAssetExposure, ...]
    momentum_features: tuple[NarrativeMomentumFeature, ...]
    unavailable_reason: str | None
    data_cutoff: datetime


class NarrativeDetectionEngine:
    """Builds frozen narratives from already materialized PIT-safe events."""

    def __init__(
        self,
        config: NarrativeConfig | None = None,
        *,
        known_narratives: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.config = config or NarrativeConfig()
        self.known_narratives = {
            _normalize_theme(name): tuple(_normalize_theme(alias) for alias in aliases)
            for name, aliases in (known_narratives or {}).items()
        }

    def detect(
        self,
        events: tuple[UnifiedEvent, ...],
        *,
        data_cutoff: datetime,
    ) -> NarrativeResult:
        _aware(data_cutoff, "data_cutoff")
        visible = tuple(
            event_at_cutoff
            for event in events
            if (event_at_cutoff := event.at_cutoff(data_cutoff)) is not None
        )
        grouped: dict[str, list[UnifiedEvent]] = {}
        for event in visible:
            for theme in event.themes:
                normalized = self._canonical_theme(theme)
                if normalized:
                    grouped.setdefault(normalized, []).append(event)
        narratives: list[NarrativeSnapshot] = []
        exposures: list[NarrativeAssetExposure] = []
        momentum: list[NarrativeMomentumFeature] = []
        for theme, items in sorted(grouped.items()):
            distinct_sources = {evidence.source for item in items for evidence in item.evidence}
            is_known = theme in self.known_narratives
            if not is_known and len(distinct_sources) < self.config.minimum_emerging_sources:
                # One source may be recorded, but it cannot establish an emerging narrative.
                continue
            snapshot = self._snapshot(theme, tuple(items), data_cutoff)
            narratives.append(snapshot)
            theme_exposures = self._exposures(snapshot, tuple(items), data_cutoff)
            exposures.extend(theme_exposures)
            for exposure in theme_exposures:
                momentum.append(
                    NarrativeMomentumFeature(
                        feature_id=_hash_id(
                            "narrative-feature",
                            snapshot.narrative_id,
                            exposure.symbol,
                            data_cutoff.isoformat(),
                        ),
                        narrative_id=snapshot.narrative_id,
                        symbol=exposure.symbol,
                        value=snapshot.momentum * exposure.exposure_score,
                        confidence=min(snapshot.source_diversity, exposure.confidence),
                        observed_at=snapshot.last_seen,
                        data_cutoff=data_cutoff,
                        model_version=self.config.model_version,
                        backtest_safety=(
                            BacktestSafety.BACKTEST_SAFE
                            if snapshot.backtest_safety is BacktestSafety.BACKTEST_SAFE
                            and exposure.backtest_safety is BacktestSafety.BACKTEST_SAFE
                            else BacktestSafety.NOT_BACKTEST_SAFE
                        ),
                    )
                )
        return NarrativeResult(
            tuple(narratives),
            tuple(exposures),
            tuple(momentum),
            None if narratives else "no sufficiently diverse narrative evidence",
            data_cutoff,
        )

    def _canonical_theme(self, raw: str) -> str:
        normalized = _normalize_theme(raw)
        for canonical, aliases in self.known_narratives.items():
            if normalized == canonical or normalized in aliases:
                return canonical
        return normalized

    def _snapshot(
        self,
        theme: str,
        events: tuple[UnifiedEvent, ...],
        cutoff: datetime,
    ) -> NarrativeSnapshot:
        ordered = tuple(sorted(events, key=lambda item: (item.observed_at, item.event_id)))
        contributions = tuple(self._event_contribution(item, cutoff) for item in ordered)
        strength = min(1.0, sum(contributions))
        recent_start = cutoff.timestamp() - self.config.momentum_window_days * 86_400
        prior_start = recent_start - self.config.momentum_window_days * 86_400
        recent = sum(
            value
            for item, value in zip(ordered, contributions, strict=True)
            if item.observed_at.timestamp() >= recent_start
        )
        prior = sum(
            value
            for item, value in zip(ordered, contributions, strict=True)
            if prior_start <= item.observed_at.timestamp() < recent_start
        )
        half_window = self.config.momentum_window_days * 86_400 / 2
        latest = sum(
            value
            for item, value in zip(ordered, contributions, strict=True)
            if item.observed_at.timestamp() >= cutoff.timestamp() - half_window
        )
        earlier = recent - latest
        momentum = tanh((recent - prior) / max(0.1, recent + prior))
        acceleration = tanh((latest - earlier) / max(0.1, latest + earlier))
        sentiment_values = tuple(_direction_value(item.direction) for item in ordered)
        recent_sentiment = mean_or_zero(
            tuple(
                value
                for item, value in zip(ordered, sentiment_values, strict=True)
                if item.observed_at.timestamp() >= recent_start
            )
        )
        prior_sentiment = mean_or_zero(
            tuple(
                value
                for item, value in zip(ordered, sentiment_values, strict=True)
                if prior_start <= item.observed_at.timestamp() < recent_start
            )
        )
        sources = {evidence.source for item in ordered for evidence in item.evidence}
        entities = {item.entity for item in ordered}
        first_seen = ordered[0].observed_at
        last_seen = ordered[-1].observed_at
        age_days = max(0.0, (cutoff - last_seen).total_seconds() / 86_400)
        duration_days = max(0.0, (last_seen - first_seen).total_seconds() / 86_400)
        safety = (
            BacktestSafety.BACKTEST_SAFE
            if all(item.backtest_safety is BacktestSafety.BACKTEST_SAFE for item in ordered)
            else BacktestSafety.NOT_BACKTEST_SAFE
        )
        event_ids = tuple(item.event_id for item in ordered)
        narrative_id = _hash_id("narrative", theme, *event_ids, cutoff.isoformat())
        return NarrativeSnapshot(
            narrative_id=narrative_id,
            name=theme,
            strength=strength,
            momentum=momentum,
            acceleration=acceleration,
            source_diversity=min(1.0, len(sources) / self.config.source_diversity_target),
            entity_breadth=min(1.0, len(entities) / self.config.entity_breadth_target),
            novelty=mean_or_zero(tuple(item.novelty for item in ordered)),
            persistence=min(1.0, duration_days / self.config.persistence_target_days),
            sentiment=mean_or_zero(sentiment_values),
            sentiment_change=recent_sentiment - prior_sentiment,
            first_seen=first_seen,
            last_seen=last_seen,
            decay_score=exp(-log(2) * age_days / self.config.half_life_days),
            data_cutoff=cutoff,
            event_ids=event_ids,
            evidence_references=tuple(
                sorted({evidence.reference for item in ordered for evidence in item.evidence})
            ),
            model_version=self.config.model_version,
            taxonomy_version=self.config.taxonomy_version,
            backtest_safety=safety,
        )

    def _event_contribution(self, event: UnifiedEvent, cutoff: datetime) -> float:
        age_days = max(0.0, (cutoff - event.observed_at).total_seconds() / 86_400)
        decay = exp(-log(2) * age_days / self.config.half_life_days)
        raw = event.confidence * event.relevance * event.novelty * decay
        return min(self.config.maximum_single_event_strength, raw)

    def _exposures(
        self,
        narrative: NarrativeSnapshot,
        events: tuple[UnifiedEvent, ...],
        cutoff: datetime,
    ) -> tuple[NarrativeAssetExposure, ...]:
        grouped: dict[str, list[UnifiedEvent]] = {}
        for event in events:
            assets = event.affected_assets or ((event.symbol,) if event.symbol else ())
            for symbol in assets:
                grouped.setdefault(symbol, []).append(event)
        output: list[NarrativeAssetExposure] = []
        for symbol, items in sorted(grouped.items()):
            evidence = tuple(
                sorted({item.reference for event in items for item in event.evidence})
            )
            confidence = mean_or_zero(tuple(item.confidence for item in items))
            exposure_score = min(1.0, sum(self._event_contribution(item, cutoff) for item in items))
            last_updated = max(item.observed_at for item in items)
            age_days = max(0.0, (cutoff - last_updated).total_seconds() / 86_400)
            output.append(
                NarrativeAssetExposure(
                    exposure_id=_hash_id(
                        "narrative-exposure", narrative.narrative_id, symbol, cutoff.isoformat()
                    ),
                    narrative_id=narrative.narrative_id,
                    symbol=symbol,
                    exposure_score=exposure_score,
                    confidence=confidence,
                    evidence=evidence,
                    source="materialized_event_evidence",
                    last_updated=last_updated,
                    data_cutoff=cutoff,
                    decay_score=exp(-log(2) * age_days / self.config.half_life_days),
                    backtest_safety=narrative.backtest_safety,
                )
            )
        return tuple(output)


def _normalize_theme(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _direction_value(direction: EventDirection) -> float:
    if direction is EventDirection.POSITIVE:
        return 1.0
    if direction is EventDirection.NEGATIVE:
        return -1.0
    return 0.0


def _hash_id(*parts: str) -> str:
    return sha256("|".join(parts).encode()).hexdigest()


def mean_or_zero(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    result = sum(values) / len(values)
    if not isfinite(result):
        raise ValueError("narrative metric is not finite")
    return result
