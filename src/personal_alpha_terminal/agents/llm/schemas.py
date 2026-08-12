from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    source: str
    as_of_date: date
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")
        if not self.source.strip():
            raise ValueError("evidence source is required")
        if not self.payload:
            raise ValueError("evidence payload cannot be empty")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    temperature: float
    response_format: Literal["json"] = "json"
    task_type: str = "structured_generation"
    prompt_version: str = "unversioned"
    input_document_ids: tuple[str, ...] = ()
    as_of: datetime | None = None
    run_id: str | None = None
    max_tokens: int = 2048
    thinking: Literal["enabled", "disabled"] = "disabled"
    reasoning_effort: Literal["low", "medium", "high", "max"] | None = None

    def __post_init__(self) -> None:
        if not self.system_prompt.strip() or not self.user_prompt.strip():
            raise ValueError("LLM prompts cannot be empty")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    is_mock: bool
    request_id: str | None = None
    fallback_reason: str | None = None
    request_hash: str | None = None
    response_hash: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    retry_count: int = 0
    validation_status: str = "NOT_VALIDATED"
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ResearchReportResult:
    title: str
    summary: str
    conclusions: tuple[dict[str, object], ...]
    data_sources: tuple[str, ...]
    analysis_logic: tuple[str, ...]
    risk_factors: tuple[str, ...]
    provider: str
    model: str
    is_mock: bool
    fallback_reason: str | None = None
