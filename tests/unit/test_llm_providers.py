import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from personal_alpha_terminal.agents.llm import (
    AnthropicProvider,
    CustomOpenAICompatibleProvider,
    DeepSeekProvider,
    DisabledProvider,
    EvidenceItem,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    MockProvider,
    OpenAIProvider,
    build_llm_provider,
)
from personal_alpha_terminal.agents.research import ResearchAgent
from personal_alpha_terminal.core.config import Settings


def request() -> LLMRequest:
    return LLMRequest(
        system_prompt="Return JSON.",
        user_prompt='{"evidence": []}',
        temperature=0.2,
    )


def test_factory_disables_external_ai_when_no_key_is_configured() -> None:
    provider = build_llm_provider(
        Settings(
            _env_file=None,
            llm_provider="auto",
            openai_api_key=None,
            deepseek_api_key=None,
        )
    )

    assert isinstance(provider, DisabledProvider)
    with pytest.raises(LLMProviderError, match="disabled"):
        provider.generate(request())


def test_explicit_provider_without_key_is_disabled_not_mocked() -> None:
    provider = build_llm_provider(
        Settings(_env_file=None, llm_provider="deepseek", deepseek_api_key=None)
    )

    assert isinstance(provider, DisabledProvider)
    with pytest.raises(LLMProviderError, match="disabled"):
        provider.generate(request())


def test_openai_provider_uses_responses_api_without_storage() -> None:
    calls: list[dict[str, Any]] = []

    class Responses:
        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(id="resp-1", output_text='{"ok": true}')

    provider = OpenAIProvider(
        api_key="test-only",
        model="test-model",
        timeout_seconds=10,
        max_retries=0,
        client=SimpleNamespace(responses=Responses()),
    )

    response = provider.generate(request())

    assert response.content == '{"ok": true}'
    assert response.request_id == "resp-1"
    assert calls[0]["store"] is False
    assert calls[0]["text"] == {"format": {"type": "json_object"}}


def test_deepseek_provider_uses_openai_compatible_json_chat() -> None:
    calls: list[dict[str, Any]] = []

    class Completions:
        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                id="chat-1",
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = DeepSeekProvider(
        api_key="test-only",
        model="deepseek-v4-flash",
        timeout_seconds=10,
        max_retries=0,
        client=client,
    )

    response = provider.generate(request())

    assert response.content == '{"ok": true}'
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["stream"] is False


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (TimeoutError("deadline"), "TIMEOUT"),
        (
            type("RateLimitError", (RuntimeError,), {"status_code": 429})("slow down"),
            "RATE_LIMITED",
        ),
        (
            type("ProviderError", (RuntimeError,), {"status_code": 503})("offline"),
            "PROVIDER_UNAVAILABLE",
        ),
    ],
)
def test_deepseek_provider_classifies_failures_without_exposing_credentials(
    error: Exception, category: str
) -> None:
    class Completions:
        @staticmethod
        def create(**_kwargs: Any) -> SimpleNamespace:
            raise error

    provider = DeepSeekProvider(
        api_key="test-only",
        model="deepseek-v4-flash",
        timeout_seconds=10,
        max_retries=0,
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.generate(request())

    assert raised.value.category == category
    assert "test-only" not in str(raised.value)


def test_custom_provider_uses_configured_openai_compatible_client() -> None:
    calls: list[dict[str, Any]] = []

    class Completions:
        @staticmethod
        def create(**kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                id="custom-1",
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            )

    provider = CustomOpenAICompatibleProvider(
        api_key="test-only",
        model="custom-model",
        timeout_seconds=10,
        max_retries=0,
        base_url="https://example.test/v1",
        client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
    )

    response = provider.generate(request())

    assert response.provider == "custom"
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_anthropic_provider_uses_messages_contract_without_exposing_key() -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return b'{"id":"msg-1","content":[{"type":"text","text":"{\\"ok\\":true}"}]}'

    def http_open(http_request: Any, *, timeout: float) -> Response:
        captured["request"] = http_request
        captured["timeout"] = timeout
        return Response()

    provider = AnthropicProvider(
        api_key="test-only-secret",
        model="claude-test",
        timeout_seconds=10,
        max_retries=0,
        http_open=http_open,
    )
    response = provider.generate(request())

    assert response.content == '{"ok":true}'
    assert response.request_id == "msg-1"
    assert captured["timeout"] == 10
    assert captured["request"].get_header("Anthropic-version") == "2023-06-01"


def test_research_agent_accepts_grounded_mock_output() -> None:
    evidence = (
        EvidenceItem(
            evidence_id="risk:1",
            source="portfolio_risk_metrics",
            as_of_date=date(2026, 7, 31),
            payload={"maximum_drawdown": -0.2},
        ),
    )

    result = ResearchAgent(MockProvider(), temperature=0.0).generate(
        report_type="portfolio_risk",
        as_of_date=date(2026, 7, 31),
        evidence=evidence,
    )

    assert result.is_mock
    assert result.data_sources == ("portfolio_risk_metrics",)
    assert result.risk_factors


def test_research_agent_rejects_unsupported_citation() -> None:
    class HallucinatingProvider:
        name = "test"
        model = "test"

        def generate(self, _request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                content=json.dumps(
                    {
                        "title": "Invalid",
                        "summary": "Unsupported source",
                        "conclusions": [{"text": "Buy now", "evidence_ids": ["invented:1"]}],
                        "data_sources": ["internet"],
                        "analysis_logic": ["invented"],
                        "risk_factors": ["unknown"],
                    }
                ),
                provider=self.name,
                model=self.model,
                is_mock=False,
            )

    evidence = (
        EvidenceItem(
            evidence_id="db:1",
            source="prices",
            as_of_date=date(2026, 7, 31),
            payload={"close": 100.0},
        ),
    )

    with pytest.raises(ValueError, match="outside the supplied package"):
        ResearchAgent(HallucinatingProvider()).generate(
            report_type="daily",
            as_of_date=date(2026, 7, 31),
            evidence=evidence,
        )


def test_research_agent_rejects_empty_evidence() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        ResearchAgent(MockProvider()).generate(
            report_type="daily",
            as_of_date=date(2026, 7, 31),
            evidence=(),
        )
