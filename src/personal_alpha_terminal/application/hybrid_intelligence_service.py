"""Compatibility entry point for the Agentic Shadow daily artifact."""

from __future__ import annotations

from personal_alpha_terminal.agents.llm.providers import LLMProvider
from personal_alpha_terminal.application.agentic_shadow_service import (
    AgenticShadowEvidence,
    build_agentic_shadow_document,
)
from personal_alpha_terminal.application.daily_result import StageResult
from personal_alpha_terminal.application.quant_daily_service import TodayResult
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig


def build_shadow_hybrid_document(
    *,
    workflow: TodayResult,
    llm_stage: StageResult | None,
    evidence: AgenticShadowEvidence | None = None,
    provider: LLMProvider | None = None,
    effective_config: EffectiveRuntimeConfig | None = None,
) -> dict[str, object]:
    """Run the real non-authoritative Shadow service."""

    return build_agentic_shadow_document(
        workflow=workflow,
        llm_stage=llm_stage,
        evidence=evidence,
        provider=provider,
        effective_config=effective_config,
    )
