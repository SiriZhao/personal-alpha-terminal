"""Canonical DeepSeek extraction for ROUND 13.1 SEC contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from personal_alpha_terminal.agents.llm.providers import LLMProvider, LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.intelligence.cache import ExtractionCache, extraction_cache_key
from personal_alpha_terminal.intelligence.round13_contracts import (
    PROMPT_VERSION,
    AcceptedSecEvent,
    EvidenceStatus,
    SecDocumentExtraction,
    validate_evidence,
)
from personal_alpha_terminal.intelligence.schemas import RawInformation


@dataclass(frozen=True, slots=True)
class Round13ExtractionResult:
    raw_id: str
    cache_hit: bool
    llm_calls: int
    accepted: tuple[AcceptedSecEvent, ...]
    quarantine_reasons: tuple[str, ...]
    response_hash: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    structured_events: int = 0


class Round13SecExtractor:
    def __init__(self, provider: LLMProvider, cache: ExtractionCache) -> None:
        self.provider = provider
        self.cache = cache

    def extract(self, raw: RawInformation) -> Round13ExtractionResult:
        preflight = _preflight(raw)
        if preflight:
            return Round13ExtractionResult(raw.raw_id, False, 0, (), (preflight,), None)
        key = extraction_cache_key(raw.source_hash or "", self.provider.model, PROMPT_VERSION)
        cached = self.cache.get(key)
        if cached is not None:
            return self._validate(cached, raw, cache_hit=True, response=None)
        assert raw.available_at is not None
        evidence_text = sanitize_and_select(raw.body)
        request = LLMRequest(
            system_prompt=(
                "Extract evidence-backed events from an SEC filing. Return strict JSON only. "
                "Never recommend trades or output price probability, alpha, risk, or weights. "
                "Every event must copy a literal source_span from content."
            ),
            user_prompt=json.dumps(
                {
                    "schema": SecDocumentExtraction.model_json_schema(),
                    "metadata": {
                        "issuer_id": raw.issuer_id,
                        "ticker_asof": raw.ticker_as_of,
                        "form_type": raw.document_type,
                        "accession_number": raw.source_identifier,
                        "accepted_at": raw.accepted_at.isoformat() if raw.accepted_at else None,
                        "available_at": raw.available_at.isoformat(),
                        "model": self.provider.model,
                        "prompt_version": PROMPT_VERSION,
                    },
                    "content": evidence_text,
                    "rules": (
                        "Use only supplied content and metadata.",
                        "Copy source_span exactly.",
                        "extraction_confidence means extraction correctness only.",
                        "Return an empty events array when evidence is insufficient.",
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            temperature=0.0,
            task_type="FILING_EXTRACTION",
            prompt_version=PROMPT_VERSION,
            input_document_ids=(raw.raw_id,),
            as_of=raw.available_at,
            max_tokens=4096,
            thinking="disabled",
        )
        try:
            response = self.provider.generate(request)
        except LLMProviderError as error:
            return Round13ExtractionResult(
                raw.raw_id, False, 1, (), (f"MODEL_FAILURE:{error.category}",), None
            )
        if response.is_mock:
            return Round13ExtractionResult(
                raw.raw_id, False, 1, (), ("MOCK_OUTPUT_REJECTED",), None
            )
        result = self._validate(
            response.content,
            raw,
            cache_hit=False,
            response=response,
            evidence_text=evidence_text,
        )
        if result.accepted or not result.quarantine_reasons:
            self.cache.put(key, response.content)
        return result

    def _validate(
        self,
        content: str,
        raw: RawInformation,
        *,
        cache_hit: bool,
        response: LLMResponse | None,
        evidence_text: str | None = None,
    ) -> Round13ExtractionResult:
        try:
            payload = SecDocumentExtraction.model_validate_json(content)
        except ValueError:
            return Round13ExtractionResult(
                raw.raw_id,
                cache_hit,
                int(not cache_hit),
                (),
                ("MALFORMED_OR_SCHEMA_INVALID_JSON",),
                None,
            )
        accepted: list[AcceptedSecEvent] = []
        rejected: list[str] = []
        seen: set[str] = set()
        response_hash = (
            response.response_hash
            if response and response.response_hash
            else sha256(content.encode("utf-8")).hexdigest()
        )
        for item in payload.events:
            reason = validate_evidence(
                item,
                raw,
                evidence_text=evidence_text or sanitize_and_select(raw.body),
                expected_model=self.provider.model,
            )
            event_id = sha256(
                f"{raw.source_hash}|{item.event_type}|{item.source_span}|{item.event_timestamp.isoformat()}".encode()
            ).hexdigest()
            if event_id in seen:
                reason = reason or EvidenceStatus.CONFLICTING_EVIDENCE
            seen.add(event_id)
            if reason:
                rejected.append(reason)
                continue
            accepted.append(
                AcceptedSecEvent(
                    event_id=event_id,
                    raw_id=raw.raw_id,
                    issuer_id=item.issuer_id,
                    ticker_asof=item.ticker_asof,
                    event_type=item.event_type.value,
                    direction=item.direction.value,
                    magnitude=item.magnitude,
                    materiality=item.materiality.value,
                    novelty=item.novelty.value,
                    horizon=item.horizon.value,
                    extraction_confidence=item.extraction_confidence,
                    source_section=item.source_section.strip(),
                    source_span=item.source_span,
                    summary=item.summary,
                    evidence_hash=sha256(item.source_span.encode("utf-8")).hexdigest(),
                    event_timestamp=item.event_timestamp,
                    available_at=item.available_at,
                    model_provider=self.provider.name,
                    model_name=self.provider.model,
                    response_hash=response_hash,
                    prompt_version=item.prompt_version,
                )
            )
        return Round13ExtractionResult(
            raw.raw_id,
            cache_hit,
            int(not cache_hit),
            tuple(accepted),
            tuple(rejected),
            response_hash,
            response.prompt_tokens if response else 0,
            response.completion_tokens if response else 0,
            response.estimated_cost_usd if response else 0.0,
            response.latency_ms if response else 0,
            len(payload.events),
        )


def sanitize_and_select(body: str, *, maximum_chars: int = 80_000) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
    text = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", text).strip()[:maximum_chars]


def _preflight(raw: RawInformation) -> str | None:
    if raw.source != "sec-edgar":
        return "SOURCE_NOT_SEC_EDGAR"
    if raw.accepted_at is None or raw.available_at is None:
        return "ACQUIRED_NOT_PIT_CERTIFIED"
    if raw.available_at != raw.accepted_at:
        return "SEC_AVAILABILITY_NOT_ACCEPTED_TIMESTAMP"
    if not raw.issuer_id:
        return "ISSUER_ID_MISSING"
    return None
