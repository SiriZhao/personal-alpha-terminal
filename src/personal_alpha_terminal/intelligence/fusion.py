from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite, tanh

from personal_alpha_terminal.intelligence.research import PromotionStatus
from personal_alpha_terminal.intelligence.schemas import BacktestSafety, _aware


class ResearchFeatureType(StrEnum):
    NARRATIVE = "NARRATIVE"
    RELATIONSHIP = "RELATIONSHIP"
    HYPOTHESIS = "HYPOTHESIS"


@dataclass(frozen=True, slots=True)
class ValidatedResearchFeature:
    feature_id: str
    symbol: str
    feature_type: ResearchFeatureType
    expected_return_lift: float
    confidence: float
    promotion_status: PromotionStatus
    backtest_safety: BacktestSafety
    data_cutoff: datetime
    valid_until: datetime
    source_ids: tuple[str, ...]
    model_version: str
    data_version: str
    real_data_validated: bool

    def __post_init__(self) -> None:
        _aware(self.data_cutoff, "data_cutoff")
        _aware(self.valid_until, "valid_until")
        if self.valid_until <= self.data_cutoff:
            raise ValueError("research feature validity must follow its cutoff")
        if not isfinite(self.expected_return_lift) or not 0 <= self.confidence <= 1:
            raise ValueError("research feature value/confidence is invalid")
        if not self.feature_id or not self.symbol or not self.source_ids:
            raise ValueError("research feature lineage is incomplete")

    def production_eligible(self, as_of: datetime) -> bool:
        return (
            self.promotion_status is PromotionStatus.PRODUCTION_APPROVED
            and self.backtest_safety is BacktestSafety.BACKTEST_SAFE
            and self.real_data_validated
            and self.data_cutoff <= as_of <= self.valid_until
        )


@dataclass(frozen=True, slots=True)
class SignalFusionConfig:
    expected_return_scale: float = 0.03
    narrative_weight: float = 0.0
    relationship_weight: float = 0.0
    hypothesis_weight: float = 0.0
    max_narrative_feature_contribution: float = 0.05
    max_relationship_feature_contribution: float = 0.05
    max_hypothesis_feature_contribution: float = 0.05
    max_ai_feature_contribution: float = 0.0
    model_version: str = "validated-intelligence-fusion-v1"

    def __post_init__(self) -> None:
        values = (
            self.narrative_weight,
            self.relationship_weight,
            self.hypothesis_weight,
            self.max_narrative_feature_contribution,
            self.max_relationship_feature_contribution,
            self.max_hypothesis_feature_contribution,
            self.max_ai_feature_contribution,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("fusion weights and limits must be finite fractions")
        if self.max_ai_feature_contribution != 0:
            raise ValueError("AI-derived confidence cannot contribute to quant ranking")
        if self.narrative_weight > self.max_narrative_feature_contribution:
            raise ValueError("narrative contribution exceeds its guardrail")
        if self.relationship_weight > self.max_relationship_feature_contribution:
            raise ValueError("relationship contribution exceeds its guardrail")
        if self.hypothesis_weight > self.max_hypothesis_feature_contribution:
            raise ValueError("hypothesis contribution exceeds its guardrail")
        if self.expected_return_scale <= 0:
            raise ValueError("fusion expected-return scale must be positive")


@dataclass(frozen=True, slots=True)
class SignalFusionResult:
    symbol: str
    narrative_score: float
    relationship_score: float
    hypothesis_score: float
    weighted_contribution: float
    research_context: tuple[str, ...]
    applied_feature_ids: tuple[str, ...]
    unavailable_or_research_only: tuple[str, ...]
    model_version: str


class ValidatedSignalFusion:
    """Adds only explicitly production-approved, PIT-safe research features."""

    def __init__(self, config: SignalFusionConfig | None = None) -> None:
        self.config = config or SignalFusionConfig()

    def fuse(
        self,
        symbol: str,
        features: tuple[ValidatedResearchFeature, ...],
        *,
        as_of: datetime,
    ) -> SignalFusionResult:
        _aware(as_of, "as_of")
        relevant = tuple(item for item in features if item.symbol == symbol)
        applied = tuple(item for item in relevant if item.production_eligible(as_of))
        scores = {
            feature_type: _aggregate_score(
                tuple(item for item in applied if item.feature_type is feature_type),
                self.config.expected_return_scale,
            )
            for feature_type in ResearchFeatureType
        }
        weights = {
            ResearchFeatureType.NARRATIVE: self.config.narrative_weight,
            ResearchFeatureType.RELATIONSHIP: self.config.relationship_weight,
            ResearchFeatureType.HYPOTHESIS: self.config.hypothesis_weight,
        }
        contribution = sum(
            weights[feature_type] * (scores[feature_type] - 50.0)
            for feature_type in ResearchFeatureType
        )
        research_only = tuple(
            f"{item.feature_type.value}:{item.feature_id}:not production eligible"
            for item in relevant
            if item not in applied
        )
        context = tuple(
            f"{item.feature_type.value} expected-return lift "
            f"{item.expected_return_lift:.4%} ({item.promotion_status.value})"
            for item in relevant
        )
        return SignalFusionResult(
            symbol=symbol,
            narrative_score=scores[ResearchFeatureType.NARRATIVE],
            relationship_score=scores[ResearchFeatureType.RELATIONSHIP],
            hypothesis_score=scores[ResearchFeatureType.HYPOTHESIS],
            weighted_contribution=contribution,
            research_context=context,
            applied_feature_ids=tuple(item.feature_id for item in applied),
            unavailable_or_research_only=research_only,
            model_version=self.config.model_version,
        )


def _aggregate_score(
    features: tuple[ValidatedResearchFeature, ...],
    scale: float,
) -> float:
    if not features:
        return 50.0
    denominator = sum(item.confidence for item in features)
    if denominator <= 0:
        return 50.0
    expected = sum(
        item.expected_return_lift * item.confidence for item in features
    ) / denominator
    return 50.0 + 50.0 * tanh(expected / scale)
