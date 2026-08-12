"""ROUND 8: Alpha Engine 2.0 — Champion/Challenger research framework."""

from personal_alpha_terminal.quant_engine.alpha_engine2.deflated import (
    DeflatedEvidence,
    deflate_sharpe,
    evaluate_deflated_evidence,
    parameter_instability,
    sample_dependence,
    subperiod_stability,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.factor_research import (
    FACTOR_CATALOG,
    FactorRedundancyReport,
    FactorResearchResult,
    factor_catalog,
    factor_redundancy,
    research_factor,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.probability_challenger import (
    ProbabilityChallengerEvidence,
    ProbabilityVerdict,
    evaluate_probability_challenger,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.promotion import (
    PromotionEvaluation,
    PromotionPolicy,
    PromotionVerdict,
    StrategyMetrics,
    evaluate_promotion,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.research_registry import (
    ExperimentStatus,
    ResearchExperiment,
    ResearchRegistry,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.shadow import (
    ShadowComparison,
    ShadowLedger,
    ShadowOutcome,
    ShadowPrediction,
    evaluate_shadow_comparison,
)

__all__ = [
    "DeflatedEvidence",
    "ExperimentStatus",
    "FACTOR_CATALOG",
    "FactorRedundancyReport",
    "FactorResearchResult",
    "ProbabilityChallengerEvidence",
    "ProbabilityVerdict",
    "PromotionEvaluation",
    "PromotionPolicy",
    "PromotionVerdict",
    "ResearchExperiment",
    "ResearchRegistry",
    "ShadowComparison",
    "ShadowLedger",
    "ShadowOutcome",
    "ShadowPrediction",
    "StrategyMetrics",
    "deflate_sharpe",
    "evaluate_deflated_evidence",
    "evaluate_probability_challenger",
    "evaluate_promotion",
    "evaluate_shadow_comparison",
    "factor_catalog",
    "factor_redundancy",
    "parameter_instability",
    "research_factor",
    "sample_dependence",
    "subperiod_stability",
]
