from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.agents.llm.providers import LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.intelligence.llm_runtime import (
    llm_runtime_status,
)
from personal_alpha_terminal.intelligence.llm_runtime import (
    test_llm_runtime as run_llm_runtime_test,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


class _Provider:
    name = "deepseek"
    model = "deepseek-v4-flash"

    def __init__(self, content: str) -> None:
        self.content = content

    def generate(self, request: LLMRequest) -> LLMResponse:
        assert request.temperature == 0.0
        return LLMResponse(
            content=self.content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            latency_ms=12,
        )


class _FailingProvider(_Provider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise LLMProviderError("sanitized", category="AUTHENTICATION_FAILED")


def test_llm_status_redacts_credential_and_has_no_quant_influence(tmp_path: Path) -> None:
    key = "unit-test-secret-never-render"
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY=key)
    status = llm_runtime_status(settings, tmp_path / "status.json")
    rendered = json.dumps(status.public_document())

    assert status.credential == "PRESENT"
    assert status.production_influence == "NONE"
    assert key not in rendered
    assert set(status.public_document()) == {
        "provider",
        "model",
        "base_url",
        "credential",
        "connectivity",
        "last_successful_call",
        "latency_ms",
        "production_influence",
    }


def test_llm_test_validates_structured_json_and_persists_only_sanitized_status(
    tmp_path: Path,
) -> None:
    key = "unit-test-secret-never-persist"
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY=key)
    path = tmp_path / "status.json"
    status = run_llm_runtime_test(
        settings,
        path,
        provider=_Provider('{"status":"ok","schema_version":"pat-llm-runtime-v1"}'),
        now=NOW,
    )

    assert status.connectivity == "AVAILABLE"
    assert status.last_successful_call == NOW
    assert key not in path.read_text(encoding="utf-8")


def test_llm_failure_is_optional_and_classified(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="unit-test-key")
    status = run_llm_runtime_test(
        settings,
        tmp_path / "status.json",
        provider=_FailingProvider(""),
        now=NOW,
    )

    assert status.connectivity == "OPTIONAL_UNAVAILABLE"
    assert status.error_classification == "AUTHENTICATION_FAILED"
    assert status.production_influence == "NONE"


def test_llm_status_ignores_malformed_or_different_model_state(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    path.write_text("not-json", encoding="utf-8")
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="unit-test-key")

    malformed = llm_runtime_status(settings, path)

    assert malformed.connectivity == "NOT_TESTED"
    path.write_text(
        json.dumps(
            {
                **malformed.diagnostic_document(),
                "model": "retired-or-different-model",
                "connectivity": "AVAILABLE",
            }
        ),
        encoding="utf-8",
    )

    changed = llm_runtime_status(settings, path)

    assert changed.connectivity == "NOT_TESTED"
    assert changed.last_successful_call is None
