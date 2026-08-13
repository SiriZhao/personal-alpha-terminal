"""Sanitized DeepSeek runtime diagnostics with no quantitative authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from personal_alpha_terminal.agents.llm.providers import (
    DeepSeekProvider,
    LLMProvider,
    LLMProviderError,
)
from personal_alpha_terminal.agents.llm.schemas import LLMRequest
from personal_alpha_terminal.core.config import Settings

PRODUCTION_INFLUENCE = "NONE"
DEFAULT_LLM_RUNTIME_STATUS_PATH = Path("var/llm/runtime_status.json")


@dataclass(frozen=True, slots=True)
class LLMRuntimeStatus:
    provider: str
    model: str
    base_url: str
    credential: str
    connectivity: str
    last_successful_call: datetime | None
    latency_ms: int | None
    production_influence: str = PRODUCTION_INFLUENCE
    error_classification: str | None = None
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.credential not in {"PRESENT", "MISSING"}:
            raise ValueError("LLM credential status must be PRESENT or MISSING")
        if self.production_influence != PRODUCTION_INFLUENCE:
            raise ValueError("LLM runtime cannot have quantitative production influence")
        for value in (self.last_successful_call, self.checked_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("LLM runtime timestamps must be timezone-aware")

    def public_document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "credential": self.credential,
            "connectivity": self.connectivity,
            "last_successful_call": (
                self.last_successful_call.isoformat()
                if self.last_successful_call is not None
                else None
            ),
            "latency_ms": self.latency_ms,
            "production_influence": self.production_influence,
        }

    def diagnostic_document(self) -> dict[str, object]:
        document = self.public_document()
        document["error_classification"] = self.error_classification
        document["checked_at"] = self.checked_at.isoformat() if self.checked_at else None
        return document


def llm_runtime_status(settings: Settings, status_path: Path) -> LLMRuntimeStatus:
    previous = _load_status(status_path)
    credential = "PRESENT" if settings.deepseek_api_key else "MISSING"
    previous_matches_config = bool(
        previous
        and previous.provider == "deepseek"
        and previous.model == settings.deepseek_model
        and previous.base_url == settings.deepseek_base_url
    )
    if credential == "MISSING":
        connectivity = "OPTIONAL_UNAVAILABLE"
    elif not previous_matches_config:
        connectivity = "NOT_TESTED"
    else:
        assert previous is not None
        connectivity = previous.connectivity
    return LLMRuntimeStatus(
        provider="deepseek",
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        credential=credential,
        connectivity=connectivity,
        last_successful_call=(
            previous.last_successful_call if previous_matches_config and previous else None
        ),
        latency_ms=previous.latency_ms if previous_matches_config and previous else None,
        error_classification=(
            previous.error_classification if previous_matches_config and previous else None
        ),
        checked_at=previous.checked_at if previous_matches_config and previous else None,
    )


def test_llm_runtime(
    settings: Settings,
    status_path: Path,
    *,
    provider: LLMProvider | None = None,
    now: datetime | None = None,
) -> LLMRuntimeStatus:
    checked_at = now or datetime.now(UTC)
    current = llm_runtime_status(settings, status_path)
    if not settings.deepseek_api_key and provider is None:
        result = replace(
            current,
            connectivity="OPTIONAL_UNAVAILABLE",
            error_classification="CREDENTIAL_MISSING",
            checked_at=checked_at,
        )
        _write_status(status_path, result)
        return result
    active_provider = provider or DeepSeekProvider(
        api_key=cast(str, settings.deepseek_api_key),
        model=settings.deepseek_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        base_url=settings.deepseek_base_url,
    )
    request = LLMRequest(
        system_prompt=(
            "Return only a JSON object matching the requested schema. "
            "Do not provide investment advice."
        ),
        user_prompt=(
            'Return {"status":"ok","schema_version":"pat-llm-runtime-v1"} exactly.'
        ),
        temperature=0.0,
        prompt_version="pat-llm-runtime-v1",
        as_of=checked_at,
        max_tokens=64,
        thinking="disabled",
    )
    try:
        response = active_provider.generate(request)
        payload = json.loads(response.content)
        if not isinstance(payload, dict):
            raise ValueError("structured response is not a JSON object")
        if payload != {"status": "ok", "schema_version": "pat-llm-runtime-v1"}:
            raise ValueError("structured response does not match the runtime schema")
        result = LLMRuntimeStatus(
            provider="deepseek",
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            credential="PRESENT",
            connectivity="AVAILABLE",
            last_successful_call=checked_at,
            latency_ms=response.latency_ms,
            error_classification=None,
            checked_at=checked_at,
        )
    except LLMProviderError as error:
        result = replace(
            current,
            connectivity="OPTIONAL_UNAVAILABLE",
            error_classification=error.category,
            checked_at=checked_at,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        result = replace(
            current,
            connectivity="OPTIONAL_UNAVAILABLE",
            error_classification="STRUCTURED_OUTPUT_INVALID",
            checked_at=checked_at,
        )
    _write_status(status_path, result)
    return result


def _write_status(path: Path, status: LLMRuntimeStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(status.diagnostic_document(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_status(path: Path) -> LLMRuntimeStatus | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        for key in ("last_successful_call", "checked_at"):
            if payload.get(key):
                payload[key] = datetime.fromisoformat(payload[key])
        allowed = {item.name for item in LLMRuntimeStatus.__dataclass_fields__.values()}
        return LLMRuntimeStatus(
            **{key: value for key, value in payload.items() if key in allowed}
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
