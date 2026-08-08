from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.agents.llm.providers import LLMProvider
from personal_alpha_terminal.agents.llm.schemas import (
    EvidenceItem,
    LLMRequest,
    ResearchReportResult,
)

SYSTEM_PROMPT = """You are a quantitative research writing assistant.
Use only the supplied evidence objects. Never predict prices, invent facts, or issue
trade instructions.
Return one JSON object with: title, summary, conclusions, data_sources, analysis_logic,
and risk_factors. Every conclusion must contain text and evidence_ids. If evidence is insufficient,
state that explicitly and return no unsupported conclusion."""


class ResearchAgent:
    """Generate schema-checked narratives from an explicit database evidence package."""

    def __init__(self, provider: LLMProvider, *, temperature: float = 0.2) -> None:
        self._provider = provider
        self._temperature = temperature

    def generate(
        self,
        *,
        report_type: str,
        as_of_date: date,
        evidence: tuple[EvidenceItem, ...],
    ) -> ResearchReportResult:
        if not report_type.strip():
            raise ValueError("report_type is required")
        if not evidence:
            raise ValueError("AI research requires at least one database evidence item")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identifiers must be unique")
        payload = {
            "report_type": report_type,
            "as_of_date": as_of_date.isoformat(),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "source": item.source,
                    "as_of_date": item.as_of_date.isoformat(),
                    "payload": item.payload,
                }
                for item in evidence
            ],
        }
        response = self._provider.generate(
            LLMRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                temperature=self._temperature,
            )
        )
        parsed = _parse_grounded_json(response.content, evidence)
        return ResearchReportResult(
            title=parsed.title,
            summary=parsed.summary,
            conclusions=parsed.conclusions,
            data_sources=parsed.data_sources,
            analysis_logic=parsed.analysis_logic,
            risk_factors=parsed.risk_factors,
            provider=response.provider,
            model=response.model,
            is_mock=response.is_mock,
            fallback_reason=response.fallback_reason,
        )


@dataclass(frozen=True, slots=True)
class _ParsedResearch:
    title: str
    summary: str
    conclusions: tuple[dict[str, object], ...]
    data_sources: tuple[str, ...]
    analysis_logic: tuple[str, ...]
    risk_factors: tuple[str, ...]


def _parse_grounded_json(
    content: str,
    evidence: tuple[EvidenceItem, ...],
) -> _ParsedResearch:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("LLM output is not valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("LLM output must be a JSON object")
    title = raw.get("title")
    summary = raw.get("summary")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("LLM output field 'title' must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("LLM output field 'summary' must be a non-empty string")
    for key in ("conclusions", "data_sources", "analysis_logic", "risk_factors"):
        if not isinstance(raw.get(key), list):
            raise ValueError(f"LLM output field {key!r} must be a list")
    allowed_ids = {item.evidence_id for item in evidence}
    allowed_sources = {item.source for item in evidence}
    conclusions = raw["conclusions"]
    assert isinstance(conclusions, list)
    validated_conclusions: list[dict[str, object]] = []
    for conclusion in conclusions:
        if not isinstance(conclusion, dict):
            raise ValueError("each conclusion must be an object")
        text = conclusion.get("text")
        cited = conclusion.get("evidence_ids")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each conclusion requires non-empty text")
        if not isinstance(cited, list) or not cited:
            raise ValueError("each conclusion requires evidence_ids")
        if any(not isinstance(item, str) or item not in allowed_ids for item in cited):
            raise ValueError("LLM conclusion cites evidence outside the supplied package")
        validated_conclusions.append(conclusion)
    sources = raw["data_sources"]
    assert isinstance(sources, list)
    if any(not isinstance(item, str) or item not in allowed_sources for item in sources):
        raise ValueError("LLM output cites a data source outside the supplied package")
    validated_sources = tuple(item for item in sources if isinstance(item, str))
    analysis_logic = raw["analysis_logic"]
    risk_factors = raw["risk_factors"]
    assert isinstance(analysis_logic, list)
    assert isinstance(risk_factors, list)
    if any(not isinstance(item, str) or not item.strip() for item in analysis_logic):
        raise ValueError("analysis_logic must contain non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in risk_factors):
        raise ValueError("risk_factors must contain non-empty strings")
    return _ParsedResearch(
        title=title,
        summary=summary,
        conclusions=tuple(validated_conclusions),
        data_sources=validated_sources,
        analysis_logic=tuple(item for item in analysis_logic if isinstance(item, str)),
        risk_factors=tuple(item for item in risk_factors if isinstance(item, str)),
    )
