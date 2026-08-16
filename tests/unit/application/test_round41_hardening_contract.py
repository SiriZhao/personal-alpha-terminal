from __future__ import annotations

from personal_alpha_terminal.application.round41_audit import (
    build_round41_failure_injection,
)


def test_round41_failure_injection_includes_llm_independence() -> None:
    result = build_round41_failure_injection()
    assert result["quant_chain_llm_independent"] is True
    assert "LLM timeout" in result["cases"]
