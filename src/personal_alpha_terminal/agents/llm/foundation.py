from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from personal_alpha_terminal.agents.llm.providers import LLMProvider, LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse


class LLMTaskType(StrEnum):
    EVENT_EXTRACTION = "EVENT_EXTRACTION"
    FILING_EXTRACTION = "FILING_EXTRACTION"
    RELATION_DISCOVERY = "RELATION_DISCOVERY"
    HYPOTHESIS_GENERATION = "HYPOTHESIS_GENERATION"
    EVIDENCE_EXPLANATION = "EVIDENCE_EXPLANATION"
    CONNECTIVITY_SMOKE = "CONNECTIVITY_SMOKE"


@dataclass(frozen=True, slots=True)
class LLMTask:
    task_type: LLMTaskType
    prompt_name: str
    prompt_version: str
    user_payload: dict[str, object]
    input_document_ids: tuple[str, ...] = ()
    as_of: datetime | None = None
    run_id: str | None = None
    high_capability: bool = False


class LLMValidationStatus(StrEnum):
    VALID = "VALID"
    SCHEMA_REJECTED = "SCHEMA_REJECTED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    version: str
    system_prompt: str


class PromptRegistry:
    def __init__(self, prompts: tuple[PromptSpec, ...] = ()) -> None:
        self._prompts = {(item.name, item.version): item for item in prompts}

    def register(self, prompt: PromptSpec) -> None:
        key = (prompt.name, prompt.version)
        if key in self._prompts:
            raise ValueError(f"prompt is already registered: {prompt.name}@{prompt.version}")
        self._prompts[key] = prompt

    def get(self, name: str, version: str) -> PromptSpec:
        try:
            return self._prompts[(name, version)]
        except KeyError as error:
            raise KeyError(f"unknown prompt: {name}@{version}") from error


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    role: str
    input_cost_per_million: float
    cached_input_cost_per_million: float
    output_cost_per_million: float


class ModelRegistry:
    def __init__(self, models: tuple[ModelSpec, ...]) -> None:
        self._models = {(item.provider, item.model): item for item in models}

    def get(self, provider: str, model: str) -> ModelSpec:
        try:
            return self._models[(provider, model)]
        except KeyError as error:
            raise KeyError(f"unregistered model: {provider}/{model}") from error


class LLMRouter:
    """Route bounded tasks by declared complexity, never by ticker or trade intent."""

    def __init__(self, *, standard: LLMProvider, high_capability: LLMProvider) -> None:
        self.standard = standard
        self.high_capability = high_capability

    def route(self, task: LLMTask) -> LLMProvider:
        return self.high_capability if task.high_capability else self.standard


class LLMCache(Protocol):
    def get(self, request_hash: str) -> LLMResponse | None: ...
    def put(self, request_hash: str, response: LLMResponse) -> None: ...


class InMemoryLLMCache:
    def __init__(self) -> None:
        self._responses: dict[str, LLMResponse] = {}

    def get(self, request_hash: str) -> LLMResponse | None:
        return self._responses.get(request_hash)

    def put(self, request_hash: str, response: LLMResponse) -> None:
        existing = self._responses.get(request_hash)
        if existing is not None and existing.response_hash != response.response_hash:
            raise ValueError("LLM cache identity is immutable")
        self._responses[request_hash] = response


@dataclass(frozen=True, slots=True)
class LLMUsageRecord:
    provider: str
    model: str
    task_type: str
    prompt_version: str
    request_hash: str
    response_hash: str | None
    input_document_ids: tuple[str, ...]
    as_of: datetime | None
    run_id: str | None
    generated_at: datetime
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    estimated_cost_usd: float
    retry_count: int
    validation_status: LLMValidationStatus
    error_category: str | None = None


class LLMUsageLedger(Protocol):
    def append(self, record: LLMUsageRecord) -> None: ...


class InMemoryLLMUsageLedger:
    def __init__(self) -> None:
        self.records: list[LLMUsageRecord] = []

    def append(self, record: LLMUsageRecord) -> None:
        self.records.append(record)


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class LLMStructuredOutput[T: BaseModel]:
    value: T
    response: LLMResponse
    schema_name: str
    schema_version: str


class LLMGateway:
    """Audited structured-output boundary around any configured provider.

    The gateway never receives credentials and never persists prompts or document
    bodies in the usage ledger. Only identities, hashes, timing and token/cost
    metadata cross this boundary.
    """

    def __init__(
        self,
        provider: LLMProvider,
        ledger: LLMUsageLedger,
        models: ModelRegistry,
    ) -> None:
        self.provider = provider
        self.ledger = ledger
        self.models = models
        self.name = provider.name
        self.model = provider.model

    def generate(self, request: LLMRequest) -> LLMResponse:
        request_hash = _request_hash(request)
        response_hash: str | None = None
        generated_at = datetime.now(UTC)
        try:
            response = self.provider.generate(request)
            parsed = json.loads(response.content)
            if not isinstance(parsed, dict):
                raise ValueError("structured LLM output must be a JSON object")
            response_hash = sha256(response.content.encode("utf-8")).hexdigest()
            cost = self._cost(response)
            audited = replace(
                response,
                request_hash=request_hash,
                response_hash=response_hash,
                validation_status=LLMValidationStatus.VALID.value,
                estimated_cost_usd=cost,
            )
            self._record(request, audited, generated_at, None)
            return audited
        except (json.JSONDecodeError, ValueError) as error:
            self._record_failure(
                request,
                request_hash,
                generated_at,
                LLMValidationStatus.SCHEMA_REJECTED,
                type(error).__name__,
                response_hash,
            )
            raise LLMProviderError(
                "LLM structured output validation failed",
                category="SCHEMA_VALIDATION_FAILED",
            ) from error
        except LLMProviderError as error:
            self._record_failure(
                request,
                request_hash,
                generated_at,
                LLMValidationStatus.PROVIDER_FAILED,
                error.category,
                response_hash,
            )
            raise

    def validate(self, response: LLMResponse, schema: type[T]) -> T:
        try:
            return schema.model_validate_json(response.content)
        except ValidationError as error:
            raise LLMProviderError(
                "LLM typed schema validation failed",
                category="SCHEMA_VALIDATION_FAILED",
            ) from error

    def _cost(self, response: LLMResponse) -> float:
        spec = self.models.get(response.provider, response.model)
        uncached = max(0, response.prompt_tokens - response.cached_tokens)
        return (
            uncached * spec.input_cost_per_million
            + response.cached_tokens * spec.cached_input_cost_per_million
            + response.completion_tokens * spec.output_cost_per_million
        ) / 1_000_000

    def _record(
        self,
        request: LLMRequest,
        response: LLMResponse,
        generated_at: datetime,
        error_category: str | None,
    ) -> None:
        self.ledger.append(
            LLMUsageRecord(
                provider=response.provider,
                model=response.model,
                task_type=request.task_type,
                prompt_version=request.prompt_version,
                request_hash=response.request_hash or _request_hash(request),
                response_hash=response.response_hash,
                input_document_ids=request.input_document_ids,
                as_of=request.as_of,
                run_id=request.run_id,
                generated_at=generated_at,
                latency_ms=response.latency_ms,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                cached_tokens=response.cached_tokens,
                estimated_cost_usd=response.estimated_cost_usd,
                retry_count=response.retry_count,
                validation_status=LLMValidationStatus(response.validation_status),
                error_category=error_category,
            )
        )

    def _record_failure(
        self,
        request: LLMRequest,
        request_hash: str,
        generated_at: datetime,
        status: LLMValidationStatus,
        category: str,
        response_hash: str | None,
    ) -> None:
        self.ledger.append(
            LLMUsageRecord(
                provider=self.name,
                model=self.model,
                task_type=request.task_type,
                prompt_version=request.prompt_version,
                request_hash=request_hash,
                response_hash=response_hash,
                input_document_ids=request.input_document_ids,
                as_of=request.as_of,
                run_id=request.run_id,
                generated_at=generated_at,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                cached_tokens=0,
                estimated_cost_usd=0.0,
                retry_count=0,
                validation_status=status,
                error_category=category,
            )
        )


def deepseek_model_registry() -> ModelRegistry:
    # Prices are versioned engineering metadata and must be refreshed when the
    # provider changes its public price card.
    return ModelRegistry(
        (
            ModelSpec("deepseek", "deepseek-v4-flash", "structured", 0.14, 0.0028, 0.28),
            ModelSpec("deepseek", "deepseek-v4-pro", "reasoning", 0.435, 0.003625, 0.87),
        )
    )


def _request_hash(request: LLMRequest) -> str:
    payload = {
        "system_prompt": request.system_prompt,
        "user_prompt": request.user_prompt,
        "temperature": request.temperature,
        "response_format": request.response_format,
        "task_type": request.task_type,
        "prompt_version": request.prompt_version,
        "input_document_ids": request.input_document_ids,
        "as_of": request.as_of.isoformat() if request.as_of else None,
        "run_id": request.run_id,
        "max_tokens": request.max_tokens,
        "thinking": request.thinking,
        "reasoning_effort": request.reasoning_effort,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
