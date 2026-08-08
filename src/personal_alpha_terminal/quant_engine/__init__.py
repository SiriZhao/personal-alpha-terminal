"""Deterministic quant research facade for the personal investment terminal."""

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
    ResearchRunManifest,
    UnifiedAlphaEngine,
)
from personal_alpha_terminal.quant_engine.data.data_pipeline import (
    DataPipeline,
    DataProvider,
    LocalResearchCache,
)
from personal_alpha_terminal.quant_engine.event_validation import (
    EventEffectValidation,
    validate_event_effects,
)
from personal_alpha_terminal.quant_engine.pit import (
    PITSelection,
    PITStatus,
    select_fundamental_vintages,
    select_universe_snapshot,
)
from personal_alpha_terminal.quant_engine.relationship_validation import (
    RelationshipEvidence,
    RelationshipUse,
    RelationshipValidation,
    validate_relationship_for_alpha,
)

__all__ = [
    "AlphaDataQuality",
    "AlphaSignal",
    "AlphaValidationStatus",
    "DataPipeline",
    "DataProvider",
    "EventEffectValidation",
    "LocalResearchCache",
    "PITSelection",
    "PITStatus",
    "ResearchRunManifest",
    "RelationshipEvidence",
    "RelationshipUse",
    "RelationshipValidation",
    "UnifiedAlphaEngine",
    "select_fundamental_vintages",
    "select_universe_snapshot",
    "validate_event_effects",
    "validate_relationship_for_alpha",
]
