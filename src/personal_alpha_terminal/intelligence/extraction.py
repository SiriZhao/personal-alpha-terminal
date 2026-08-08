from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from pydantic import ValidationError

from personal_alpha_terminal.agents.llm.providers import LLMProvider, LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest
from personal_alpha_terminal.intelligence.budget import IntelligenceBudget, estimate_tokens
from personal_alpha_terminal.intelligence.cache import ExtractionCache, extraction_cache_key
from personal_alpha_terminal.intelligence.normalization import (
    normalize_event_type,
    normalize_symbol,
    normalize_tags,
)
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    EventEvidence,
    IntelligenceStatus,
    RawInformation,
    StrictModel,
    UnifiedEvent,
)


class ExtractedEventPayload(StrictModel):
    symbol: str | None = None
    entity: str
    sector: str | None = None
    industry: str | None = None
    event_type: str
    event_subtype: str | None = None
    summary: str
    direction: EventDirection = EventDirection.UNKNOWN
    magnitude: float | None = None
    surprise: float | None = None
    relevance: float
    novelty: float
    confidence: float
    expected_horizon: int
    affected_assets: tuple[str, ...] = ()
    affected_sectors: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    effective_at: datetime
    earnings_features: EarningsFeatures | None = None
    macro_features: MacroFeatures | None = None


class EarningsFeatures(StrictModel):
    eps_surprise: float | None = None
    revenue_surprise: float | None = None
    guidance_change: float | None = None
    margin_change: float | None = None
    estimate_revision: float | None = None
    management_tone: float | None = None
    capex_revision: float | None = None


class MacroFeatures(StrictModel):
    release: str
    actual: float | None = None
    consensus: float | None = None
    prior: float | None = None
    revision: float | None = None
    unit: str | None = None
    surprise: float | None = None
    policy_stance: float | None = None


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    status: IntelligenceStatus
    event: UnifiedEvent | None
    error: str | None
    cache_hit: bool
    provider: str


class StructuredEventExtractor:
    PROMPT_VERSION = "event-extraction-v1"

    def __init__(
        self,
        provider: LLMProvider,
        cache: ExtractionCache,
        budget: IntelligenceBudget,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.budget = budget
        self.clock = clock

    def extract(self, raw: RawInformation) -> ExtractionOutcome:
        key = extraction_cache_key(
            raw.source_hash or "", self.provider.model, self.PROMPT_VERSION
        )
        cached = self.cache.get(key)
        if cached is not None:
            return self._parse(cached, raw, cache_hit=True, is_mock=False)
        prompt = json.dumps(
            {
                "schema": ExtractedEventPayload.model_json_schema(),
                "information": raw.model_dump(mode="json"),
                "rules": [
                    "Use only the supplied information and its data cutoff.",
                    "Do not predict price, recommend trades, or invent missing values.",
                    "Return one JSON object matching schema exactly.",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if not self.budget.reserve(estimate_tokens(prompt)):
            return ExtractionOutcome(
                IntelligenceStatus.AI_BUDGET_EXCEEDED, None, "AI run budget exhausted", False,
                self.provider.name,
            )
        request = LLMRequest(
            system_prompt=(
                "You structure observable financial events. Output strict JSON only. "
                "Never create a trading recommendation or infer unprovided facts."
            ),
            user_prompt=prompt,
            temperature=0.0,
        )
        last_error: str | None = None
        for attempt in range(self.budget.config.max_retries + 1):
            try:
                response = self.provider.generate(request)
            except LLMProviderError as error:
                return ExtractionOutcome(
                    IntelligenceStatus.UNAVAILABLE, None, str(error), False, self.provider.name
                )
            if response.is_mock:
                return ExtractionOutcome(
                    IntelligenceStatus.DEGRADED,
                    None,
                    "mock AI output is never accepted as market intelligence",
                    False,
                    response.provider,
                )
            outcome = self._parse(response.content, raw, cache_hit=False, is_mock=False)
            if outcome.event is not None:
                self.cache.put(key, response.content)
                return outcome
            last_error = outcome.error
            if attempt < self.budget.config.max_retries:
                if not self.budget.reserve(estimate_tokens(prompt)):
                    return ExtractionOutcome(
                        IntelligenceStatus.AI_BUDGET_EXCEEDED, None,
                        "AI retry budget exhausted", False, self.provider.name,
                    )
        return ExtractionOutcome(
            IntelligenceStatus.AI_PARSE_FAILED, None, last_error, False, self.provider.name
        )

    def _parse(
        self,
        content: str,
        raw: RawInformation,
        *,
        cache_hit: bool,
        is_mock: bool,
    ) -> ExtractionOutcome:
        if is_mock:
            return ExtractionOutcome(
                IntelligenceStatus.DEGRADED, None, "mock intelligence is blocked", cache_hit,
                self.provider.name,
            )
        try:
            payload = ExtractedEventPayload.model_validate_json(content)
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("extractor clock must return timezone-aware datetime")
            if payload.effective_at.tzinfo is None or payload.effective_at.utcoffset() is None:
                raise ValueError("effective_at must be timezone-aware")
            evidence = EventEvidence(
                evidence_id=raw.raw_id,
                source=raw.source,
                source_identifier=raw.source_identifier,
                source_hash=raw.source_hash or "",
                published_at=raw.published_at,
                observed_at=raw.observed_at,
                reference=raw.source_url or raw.source_identifier,
                extraction_confidence=payload.confidence,
            )
            event_hash = sha256(
                f"{raw.source_hash}|{payload.entity}|{payload.event_type}|{payload.effective_at.isoformat()}".encode()
            ).hexdigest()
            event = UnifiedEvent(
                event_id=event_hash,
                symbol=normalize_symbol(payload.symbol),
                entity=payload.entity.strip(),
                sector=payload.sector,
                industry=payload.industry,
                event_type=normalize_event_type(payload.event_type),
                event_subtype=payload.event_subtype,
                title=raw.title,
                summary=payload.summary,
                published_at=raw.published_at,
                observed_at=raw.observed_at,
                effective_at=payload.effective_at,
                ingested_at=raw.ingested_at,
                source=raw.source,
                source_identifier=raw.source_identifier,
                source_hash=raw.source_hash or "",
                direction=payload.direction,
                magnitude=payload.magnitude,
                surprise=payload.surprise,
                relevance=payload.relevance,
                novelty=payload.novelty,
                confidence=payload.confidence,
                expected_horizon=payload.expected_horizon,
                affected_assets=normalize_tags(list(payload.affected_assets)),
                affected_sectors=normalize_tags(list(payload.affected_sectors)),
                themes=normalize_tags(list(payload.themes)),
                structured_features={
                    key: value
                    for key, value in {
                        "earnings": (
                            payload.earnings_features.model_dump()
                            if payload.earnings_features is not None
                            else None
                        ),
                        "macro": (
                            payload.macro_features.model_dump()
                            if payload.macro_features is not None
                            else None
                        ),
                    }.items()
                    if value is not None
                },
                evidence=(evidence,),
                model_version=self.provider.model,
                prompt_version=self.PROMPT_VERSION,
                data_cutoff=raw.data_cutoff,
                created_at=now,
                backtest_safety=BacktestSafety.BACKTEST_SAFE,
            )
            return ExtractionOutcome(
                IntelligenceStatus.READY, event, None, cache_hit, self.provider.name
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            return ExtractionOutcome(
                IntelligenceStatus.AI_PARSE_FAILED,
                None,
                f"structured extraction rejected: {type(error).__name__}",
                cache_hit,
                self.provider.name,
            )
