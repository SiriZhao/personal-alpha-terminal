from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.llm.factory import build_llm_provider
from personal_alpha_terminal.agents.llm.foundation import (
    LLMGateway,
    ModelRegistry,
    ModelSpec,
    deepseek_model_registry,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.intelligence.budget import (
    IntelligenceBudget,
    IntelligenceBudgetConfig,
)
from personal_alpha_terminal.intelligence.cross_asset import CrossAssetContextEngine
from personal_alpha_terminal.intelligence.extraction import StructuredEventExtractor
from personal_alpha_terminal.intelligence.narrative import NarrativeConfig, NarrativeDetectionEngine
from personal_alpha_terminal.intelligence.relationship import (
    MarketRelationshipGraphEngine,
    RelationshipGraphConfig,
)
from personal_alpha_terminal.intelligence.research import (
    HypothesisValidationConfig,
    HypothesisValidationEngine,
    ResearchBudgetConfig,
)
from personal_alpha_terminal.intelligence.scanner import DailyOpportunityScanner, ScannerConfig
from personal_alpha_terminal.intelligence.service import IntelligenceService
from personal_alpha_terminal.intelligence.storage import (
    DatabaseExtractionCache,
    DatabaseLLMUsageLedger,
)


def build_intelligence_service(session: Session, settings: Settings) -> IntelligenceService:
    provider = build_llm_provider(settings)
    model_registry = (
        deepseek_model_registry()
        if provider.name == "deepseek"
        else ModelRegistry((ModelSpec(provider.name, provider.model, "configured", 0, 0, 0),))
    )
    provider = LLMGateway(provider, DatabaseLLMUsageLedger(session), model_registry)
    budget = IntelligenceBudget(
        IntelligenceBudgetConfig(
            max_requests_per_run=settings.intelligence_max_requests_per_run,
            max_tokens_per_run=settings.intelligence_max_tokens_per_run,
            max_cost_per_run=settings.intelligence_max_cost_per_run,
            max_retries=settings.llm_max_retries,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
    cache = DatabaseExtractionCache(
        session,
        model_version=provider.model,
        prompt_version=StructuredEventExtractor.PROMPT_VERSION,
    )
    extractor = StructuredEventExtractor(
        provider,
        cache,
        budget,
        clock=lambda: datetime.now(UTC),
    )
    scanner = DailyOpportunityScanner(
        ScannerConfig(
            quant_weight=settings.intelligence_scanner_quant_weight,
            probability_weight=settings.intelligence_scanner_probability_weight,
            event_weight=settings.intelligence_scanner_event_weight,
            risk_penalty_weight=settings.intelligence_scanner_risk_penalty_weight,
            expected_return_scale=settings.intelligence_expected_return_scale,
            max_ai_feature_contribution=settings.intelligence_max_ai_contribution,
            max_event_feature_contribution=settings.intelligence_max_event_contribution,
            narrative_weight=settings.intelligence_scanner_narrative_weight,
            relationship_weight=settings.intelligence_scanner_relationship_weight,
            hypothesis_weight=settings.intelligence_scanner_hypothesis_weight,
            max_narrative_feature_contribution=(settings.intelligence_max_narrative_contribution),
            max_relationship_feature_contribution=(
                settings.intelligence_max_relationship_contribution
            ),
            max_hypothesis_feature_contribution=(settings.intelligence_max_hypothesis_contribution),
        )
    )
    narrative_engine = NarrativeDetectionEngine(
        NarrativeConfig(
            half_life_days=settings.intelligence_narrative_half_life_days,
            momentum_window_days=settings.intelligence_narrative_momentum_window_days,
            maximum_single_event_strength=(settings.intelligence_narrative_single_event_cap),
            minimum_emerging_sources=(settings.intelligence_narrative_minimum_emerging_sources),
            source_diversity_target=(settings.intelligence_narrative_source_diversity_target),
            entity_breadth_target=settings.intelligence_narrative_entity_breadth_target,
            persistence_target_days=settings.intelligence_narrative_persistence_days,
        )
    )
    relationship_engine = MarketRelationshipGraphEngine(
        RelationshipGraphConfig(
            windows=_parse_positive_ints(settings.intelligence_relationship_windows),
            minimum_sample_size=settings.intelligence_relationship_minimum_sample,
            maximum_lag=settings.intelligence_relationship_maximum_lag,
            fdr_threshold=settings.intelligence_relationship_fdr_threshold,
            minimum_abs_strength=settings.intelligence_relationship_minimum_effect,
            minimum_oos_survival=(settings.intelligence_relationship_minimum_oos_survival),
        )
    )
    hypothesis_engine = HypothesisValidationEngine(
        HypothesisValidationConfig(
            minimum_sample_size=settings.intelligence_hypothesis_minimum_sample,
            minimum_oos_sample_size=settings.intelligence_hypothesis_minimum_oos_sample,
            fdr_threshold=settings.intelligence_hypothesis_fdr_threshold,
            minimum_effect_size=settings.intelligence_hypothesis_minimum_effect,
            minimum_oos_stability=(settings.intelligence_hypothesis_minimum_oos_stability),
            minimum_regime_stability=(settings.intelligence_hypothesis_minimum_regime_stability),
            maximum_drawdown=settings.intelligence_hypothesis_maximum_drawdown,
            maximum_turnover=settings.intelligence_hypothesis_maximum_turnover,
        ),
        ResearchBudgetConfig(
            max_hypotheses_per_run=settings.intelligence_hypothesis_max_per_run,
            max_parameter_combinations=(
                settings.intelligence_hypothesis_max_parameter_combinations
            ),
            max_threshold_combinations=(
                settings.intelligence_hypothesis_max_threshold_combinations
            ),
            max_horizon_combinations=(settings.intelligence_hypothesis_max_horizon_combinations),
        ),
    )
    return IntelligenceService(
        session,
        extractor,
        scanner=scanner,
        narrative_engine=narrative_engine,
        relationship_engine=relationship_engine,
        hypothesis_engine=hypothesis_engine,
        cross_asset_engine=CrossAssetContextEngine(),
    )


def _parse_positive_ints(raw: str) -> tuple[int, ...]:
    values = tuple(sorted({int(item.strip()) for item in raw.split(",") if item.strip()}))
    if not values or any(item <= 0 for item in values):
        raise ValueError("relationship windows must contain positive integers")
    return values
