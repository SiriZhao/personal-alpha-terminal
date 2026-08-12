from personal_alpha_terminal.agents.llm.providers import (
    AnthropicProvider,
    CustomOpenAICompatibleProvider,
    DeepSeekProvider,
    DisabledProvider,
    LLMProvider,
    MockProvider,
    OpenAIProvider,
)
from personal_alpha_terminal.core.config import Settings


def build_llm_provider(settings: Settings) -> LLMProvider:
    selected = settings.llm_provider
    if selected == "disabled":
        return DisabledProvider()
    if selected == "mock":
        return MockProvider(fallback_reason="mock mode explicitly selected")
    if selected == "openai":
        if not settings.openai_api_key:
            return DisabledProvider()
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    if selected == "deepseek":
        if not settings.deepseek_api_key:
            return DisabledProvider()
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            base_url=settings.deepseek_base_url,
        )
    if selected == "anthropic":
        if not settings.anthropic_api_key:
            return DisabledProvider()
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            base_url=settings.anthropic_base_url,
        )
    if selected == "custom":
        if not settings.custom_api_key:
            return DisabledProvider()
        return CustomOpenAICompatibleProvider(
            api_key=settings.custom_api_key,
            model=settings.custom_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            base_url=settings.custom_base_url,
        )
    if settings.openai_api_key:
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    if settings.deepseek_api_key:
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            base_url=settings.deepseek_base_url,
        )
    if settings.anthropic_api_key:
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            base_url=settings.anthropic_base_url,
        )
    return DisabledProvider()
