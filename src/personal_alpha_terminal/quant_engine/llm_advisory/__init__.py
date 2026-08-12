"""ROUND 9: LLM Quant Modernization -- Shadow -> Advisory Intelligence."""

from personal_alpha_terminal.quant_engine.llm_advisory.contracts import (
    AdvisoryEnvelope,
    DataAnomalyReport,
    EvidenceRef,
    PortfolioExplanation,
    ResearchCopilotNote,
    ShadowFeatureSuggestion,
)
from personal_alpha_terminal.quant_engine.llm_advisory.evaluation import (
    EvaluationThresholds,
    LLMEvaluation,
    evaluate_llm,
)
from personal_alpha_terminal.quant_engine.llm_advisory.guard import (
    LLMGuard,
    LLMGuardResult,
    LLMGuardStatus,
)
from personal_alpha_terminal.quant_engine.llm_advisory.identity import (
    PromptIdentity,
    build_prompt_identity,
    prompt_hash,
)
from personal_alpha_terminal.quant_engine.llm_advisory.service import (
    AdvisoryIntelligenceService,
    AdvisorySnapshot,
)
from personal_alpha_terminal.quant_engine.llm_advisory.shadow_research import (
    ShadowResearchResult,
    ShadowResearchVerdict,
    evaluate_llm_shadow_research,
)

__all__ = [
    "AdvisoryEnvelope",
    "AdvisoryIntelligenceService",
    "AdvisorySnapshot",
    "DataAnomalyReport",
    "EvaluationThresholds",
    "EvidenceRef",
    "LLMEvaluation",
    "LLMGuard",
    "LLMGuardResult",
    "LLMGuardStatus",
    "PortfolioExplanation",
    "PromptIdentity",
    "ResearchCopilotNote",
    "ShadowFeatureSuggestion",
    "ShadowResearchResult",
    "ShadowResearchVerdict",
    "build_prompt_identity",
    "evaluate_llm",
    "evaluate_llm_shadow_research",
    "prompt_hash",
]
