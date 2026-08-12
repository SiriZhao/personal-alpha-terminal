from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from statistics import fmean, pstdev

from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    UnifiedEvent,
)


class LLMFactorStatus(StrEnum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True)
class LLMFactorDefinition:
    factor_name: str
    description: str
    data_dependency: str
    lookback_sessions: int
    horizon_sessions: int
    prompt_version: str
    model_version: str
    pit_requirement: str
    normalization: str
    missing_value_policy: str
    sector_neutrality_policy: str
    production_status: LLMFactorStatus
    approval_artifact_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMFactorObservation:
    symbol: str
    factor_name: str
    as_of: datetime
    raw_value: float
    normalized_value: float
    extraction_confidence: float
    statistical_probability: float | None
    event_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    model_version: str
    prompt_version: str
    production_status: LLMFactorStatus
    observation_hash: str

    @property
    def can_affect_production(self) -> bool:
        return (
            self.production_status is LLMFactorStatus.PRODUCTION_APPROVED
            and self.statistical_probability is not None
        )


class LLMFactorRegistry:
    def __init__(self, definitions: tuple[LLMFactorDefinition, ...]) -> None:
        self._definitions = {item.factor_name: item for item in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("duplicate LLM factor definition")
        for item in definitions:
            if (
                item.production_status is LLMFactorStatus.PRODUCTION_APPROVED
                and not item.approval_artifact_id
            ):
                raise ValueError("approved LLM factor requires an approval artifact")

    def get(self, factor_name: str) -> LLMFactorDefinition:
        return self._definitions[factor_name]

    def definitions(self) -> tuple[LLMFactorDefinition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))


class CrossSectionalEventFactorEngine:
    """Convert PIT-visible structured events into a reproducible SHADOW factor.

    Extraction confidence is retained as data-quality metadata. It is deliberately
    not treated as a calibrated return probability and cannot unlock production use.
    """

    FACTOR_NAME = "llm_event_intensity"

    def __init__(self, registry: LLMFactorRegistry) -> None:
        self.definition = registry.get(self.FACTOR_NAME)

    def build(
        self,
        events: tuple[UnifiedEvent, ...],
        *,
        as_of: datetime,
        eligible_symbols: tuple[str, ...],
        sector_by_symbol: dict[str, str] | None = None,
    ) -> tuple[LLMFactorObservation, ...]:
        visible: dict[str, list[UnifiedEvent]] = {symbol: [] for symbol in eligible_symbols}
        for event in events:
            point_in_time = event.at_cutoff(as_of)
            if (
                point_in_time is None
                or point_in_time.backtest_safety is not BacktestSafety.BACKTEST_SAFE
                or point_in_time.symbol not in visible
            ):
                continue
            visible[point_in_time.symbol].append(point_in_time)
        raw = {symbol: self._raw_value(items) for symbol, items in visible.items()}
        winsorized = _winsorize(raw)
        adjusted = _sector_demean(winsorized, sector_by_symbol or {})
        values = tuple(adjusted.values())
        mean = fmean(values) if values else 0.0
        scale = pstdev(values) if len(values) > 1 else 0.0
        observations: list[LLMFactorObservation] = []
        for symbol in sorted(adjusted):
            items = tuple(sorted(visible[symbol], key=lambda item: item.event_id))
            normalized = (adjusted[symbol] - mean) / scale if scale > 0 else 0.0
            event_ids = tuple(item.event_id for item in items)
            source_hashes = tuple(sorted({item.source_hash for item in items}))
            confidence = fmean(item.confidence for item in items) if items else 0.0
            identity = "|".join(
                (
                    symbol,
                    as_of.isoformat(),
                    self.definition.factor_name,
                    f"{raw[symbol]:.12g}",
                    f"{normalized:.12g}",
                    *event_ids,
                    *source_hashes,
                    self.definition.model_version,
                    self.definition.prompt_version,
                )
            )
            observations.append(
                LLMFactorObservation(
                    symbol=symbol,
                    factor_name=self.definition.factor_name,
                    as_of=as_of,
                    raw_value=raw[symbol],
                    normalized_value=normalized,
                    extraction_confidence=confidence,
                    statistical_probability=None,
                    event_ids=event_ids,
                    source_hashes=source_hashes,
                    model_version=self.definition.model_version,
                    prompt_version=self.definition.prompt_version,
                    production_status=self.definition.production_status,
                    observation_hash=sha256(identity.encode()).hexdigest(),
                )
            )
        return tuple(observations)

    @staticmethod
    def _raw_value(events: list[UnifiedEvent]) -> float:
        direction = {
            EventDirection.POSITIVE: 1.0,
            EventDirection.NEGATIVE: -1.0,
            EventDirection.MIXED: 0.0,
            EventDirection.NEUTRAL: 0.0,
            EventDirection.UNKNOWN: 0.0,
        }
        return sum(
            direction[item.direction]
            * item.relevance
            * item.novelty
            * min(abs(item.magnitude) if item.magnitude is not None else 1.0, 3.0)
            for item in events
        )


def default_llm_factor_registry(
    *,
    model_version: str = "deepseek-v4-flash",
    prompt_version: str = "event-extraction-v2",
) -> LLMFactorRegistry:
    return LLMFactorRegistry(
        (
            LLMFactorDefinition(
                factor_name="llm_event_intensity",
                description=(
                    "PIT structured event direction, relevance and novelty; "
                    "no subjective probability"
                ),
                data_dependency="CERTIFIED_HISTORICAL_TEXT_EVENTS",
                lookback_sessions=5,
                horizon_sessions=20,
                prompt_version=prompt_version,
                model_version=model_version,
                pit_requirement="document.available_at <= decision_as_of",
                normalization="daily winsorized cross-sectional z-score with sector demeaning",
                missing_value_policy=(
                    "zero only means no certified visible event, "
                    "never extraction failure"
                ),
                sector_neutrality_policy="demean sectors with at least two eligible securities",
                production_status=LLMFactorStatus.SHADOW,
            ),
        )
    )


def _winsorize(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.values())
    if len(ordered) < 3:
        return dict(values)
    low = ordered[max(0, int((len(ordered) - 1) * 0.05))]
    high = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
    return {key: min(max(value, low), high) for key, value in values.items()}


def _sector_demean(values: dict[str, float], sectors: dict[str, str]) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for symbol, value in values.items():
        sector = sectors.get(symbol)
        if sector:
            grouped.setdefault(sector, []).append(value)
    means = {sector: fmean(items) for sector, items in grouped.items() if len(items) >= 2}
    return {
        symbol: value - means.get(sectors.get(symbol, ""), 0.0) for symbol, value in values.items()
    }
