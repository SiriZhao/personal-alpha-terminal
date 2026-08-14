"""ROUND24 DeepSeek Chinese brief client (B6, B7).

A failed call, timeout, quota error or schema violation quarantines the
payload and degrades the advisory layer only; the Classical pipeline is
never touched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from personal_alpha_terminal.agents.llm.schemas import LLMRequest
from personal_alpha_terminal.ai_advisory.prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from personal_alpha_terminal.ai_advisory.schemas import (
    PROMPT_VERSION,
    validate_brief,
)

BRIEF_STATUS_OK = "OK"
BRIEF_STATUS_TIMEOUT = "TIMEOUT"
BRIEF_STATUS_API_ERROR = "API_ERROR"
BRIEF_STATUS_QUOTA_ERROR = "QUOTA_ERROR"
BRIEF_STATUS_SCHEMA_INVALID = "SCHEMA_INVALID"
BRIEF_STATUS_EMPTY = "EMPTY_RESPONSE"


@dataclass(frozen=True, slots=True)
class BriefCallOutcome:
    status: str
    payload: dict[str, Any] | None
    error: str | None
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


ProviderFactory = Callable[[], Any]


def _json_payload(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        first = text.find("\n")
        last = text.rfind("```")
        text = text[first + 1 : last].strip() if first != -1 and last > first else text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def call_deepseek_brief(
    *,
    provider_factory: ProviderFactory,
    model: str,
    facts: dict[str, Any],
    schema_hint: str,
    allowed_symbols: frozenset[str],
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> BriefCallOutcome:
    """Call DeepSeek once and validate the strict schema."""

    request = LLMRequest(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(facts, schema_hint),
        temperature=temperature,
        prompt_version=PROMPT_VERSION,
        as_of=datetime.now(UTC),
        max_tokens=max_tokens,
        thinking="disabled",
    )
    try:
        provider = provider_factory()
        response = provider.generate(request)
    except TimeoutError as exc:
        return BriefCallOutcome(BRIEF_STATUS_TIMEOUT, None, str(exc), 0, 0, 0, 0.0)
    except Exception as exc:  # noqa: BLE001 - provider isolation boundary
        message = str(exc).lower()
        status = (
            BRIEF_STATUS_QUOTA_ERROR
            if any(word in message for word in ("quota", "insufficient", "balance", "402"))
            else BRIEF_STATUS_API_ERROR
        )
        return BriefCallOutcome(status, None, str(exc), 0, 0, 0, 0.0)
    content = str(response.content).strip()
    if not content:
        return BriefCallOutcome(
            BRIEF_STATUS_EMPTY,
            None,
            "provider returned an empty response",
            int(getattr(response, "latency_ms", 0) or 0),
            int(getattr(response, "prompt_tokens", 0) or 0),
            int(getattr(response, "completion_tokens", 0) or 0),
            float(getattr(response, "estimated_cost_usd", 0.0) or 0.0),
        )
    payload = _json_payload(content)
    if payload is None:
        return BriefCallOutcome(
            BRIEF_STATUS_SCHEMA_INVALID,
            None,
            "response is not a valid JSON object",
            int(getattr(response, "latency_ms", 0) or 0),
            int(getattr(response, "prompt_tokens", 0) or 0),
            int(getattr(response, "completion_tokens", 0) or 0),
            float(getattr(response, "estimated_cost_usd", 0.0) or 0.0),
        )
    ok, error = validate_brief(payload, allowed_symbols=allowed_symbols)
    if not ok:
        return BriefCallOutcome(
            BRIEF_STATUS_SCHEMA_INVALID,
            None,
            error,
            int(getattr(response, "latency_ms", 0) or 0),
            int(getattr(response, "prompt_tokens", 0) or 0),
            int(getattr(response, "completion_tokens", 0) or 0),
            float(getattr(response, "estimated_cost_usd", 0.0) or 0.0),
        )
    return BriefCallOutcome(
        BRIEF_STATUS_OK,
        payload,
        None,
        int(getattr(response, "latency_ms", 0) or 0),
        int(getattr(response, "prompt_tokens", 0) or 0),
        int(getattr(response, "completion_tokens", 0) or 0),
        float(getattr(response, "estimated_cost_usd", 0.0) or 0.0),
    )
