from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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

    def __post_init__(self) -> None:
        if not self.system_prompt.strip() or not self.user_prompt.strip():
            raise ValueError("LLM prompts cannot be empty")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    is_mock: bool
    request_id: str | None = None
    fallback_reason: str | None = None


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
