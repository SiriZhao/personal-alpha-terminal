from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, request: LLMRequest) -> LLMResponse: ...


class LLMProviderError(RuntimeError):
    """Raised when a configured external provider cannot return a valid response."""


class DisabledProvider:
    name = "disabled"
    model = "disabled"

    def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise LLMProviderError("AI provider is disabled in settings")


class MockProvider:
    name = "mock"
    model = "deterministic-grounded-mock-v1"

    def __init__(self, *, fallback_reason: str | None = None) -> None:
        self._fallback_reason = fallback_reason

    def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            request_payload = json.loads(request.user_prompt)
        except json.JSONDecodeError:
            request_payload = {}
        evidence = request_payload.get("evidence", []) if isinstance(request_payload, dict) else []
        sources = sorted(
            {
                str(item["source"])
                for item in evidence
                if isinstance(item, dict) and isinstance(item.get("source"), str)
            }
        )
        payload = {
            "title": f"Mock {request_payload.get('report_type', 'research')} report",
            "summary": "Mock mode is active; no external model was called.",
            "conclusions": [],
            "data_sources": sources,
            "analysis_logic": [
                "Return a deterministic schema so local workflows remain testable.",
                "Do not infer prices or investment actions without database evidence.",
            ],
            "risk_factors": [
                "Mock output is not investment research and must not be used for decisions."
            ],
            "request_echo": asdict(request),
        }
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            provider=self.name,
            model=self.model,
            is_mock=True,
            fallback_reason=self._fallback_reason,
        )


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        self.model = model
        self._client = client or _openai_client(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=request.system_prompt,
                input=request.user_prompt,
                temperature=request.temperature,
                text={"format": {"type": "json_object"}},
                store=False,
            )
            content = str(response.output_text).strip()
        except Exception as error:
            raise LLMProviderError(f"OpenAI request failed: {type(error).__name__}") from error
        if not content:
            raise LLMProviderError("OpenAI returned empty output")
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id=cast(str | None, getattr(response, "id", None)),
        )


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str = "https://api.deepseek.com",
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key is required")
        self.model = model
        self._client = client or _openai_client(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            base_url=base_url,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                temperature=request.temperature,
                response_format={"type": "json_object"},
                stream=False,
            )
            content = response.choices[0].message.content
        except Exception as error:
            raise LLMProviderError(f"DeepSeek request failed: {type(error).__name__}") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("DeepSeek returned empty output")
        return LLMResponse(
            content=content.strip(),
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id=cast(str | None, getattr(response, "id", None)),
        )


class CustomOpenAICompatibleProvider(DeepSeekProvider):
    """User-configured OpenAI-compatible endpoint with no business-logic coupling."""

    name = "custom"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            base_url=base_url,
            client=client,
        )


class AnthropicProvider:
    """Minimal Anthropic Messages API adapter for grounded report generation."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str = "https://api.anthropic.com",
        http_open: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Anthropic API key is required")
        self.model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._endpoint = base_url.rstrip("/") + "/v1/messages"
        self._http_open = http_open or urlopen
        self._sleep = sleep

    def generate(self, request: LLMRequest) -> LLMResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "max_tokens": 2048,
                "temperature": request.temperature,
                "system": request.system_prompt,
                "messages": [{"role": "user", "content": request.user_prompt}],
            }
        ).encode("utf-8")
        http_request = Request(
            self._endpoint,
            data=payload,
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        response_payload: object = {}
        for attempt in range(self._max_retries + 1):
            try:
                with self._http_open(
                    http_request, timeout=self._timeout_seconds
                ) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except (
                HTTPError,
                URLError,
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as error:
                if attempt >= self._max_retries:
                    raise LLMProviderError(
                        f"Anthropic request failed: {type(error).__name__}"
                    ) from error
                self._sleep(min(2**attempt, 8))
        blocks = response_payload.get("content") if isinstance(response_payload, dict) else None
        if not isinstance(blocks, list):
            raise LLMProviderError("Anthropic returned an invalid content payload")
        content = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not content:
            raise LLMProviderError("Anthropic returned empty output")
        request_id = response_payload.get("id") if isinstance(response_payload, dict) else None
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            request_id=request_id if isinstance(request_id, str) else None,
        )


def _openai_client(
    *,
    api_key: str,
    timeout_seconds: float,
    max_retries: int,
    base_url: str | None = None,
) -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise LLMProviderError(
            "OpenAI SDK is not installed; install the project with the 'ai' extra"
        ) from error
    if base_url is not None:
        return OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            base_url=base_url,
        )
    return OpenAI(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=max_retries,
    )
