"""ROUND 9: LLM advisory structured-output contracts.

Every LLM output that could enter the research or advisory layer must conform to
a schema carrying: evidence, classification, confidence, timestamp, source,
model and prompt_version.  Free-form text never enters the strategy directly;
any numeric value is validated before use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvidenceRef(BaseModel):
    evidence_id: str
    source: str
    timestamp: datetime | None = None
    document_id: str | None = None


class AdvisoryEnvelope(BaseModel):
    """Common envelope for every structured advisory output."""

    classification: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    source: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    summary: str = ""

    @field_validator("classification")
    @classmethod
    def _classification_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("classification is required")
        return value


class DataAnomalyReport(AdvisoryEnvelope):
    """Explanation of a data anomaly (provider failure, staleness, collapse)."""

    anomaly_kind: Literal[
        "PROVIDER_FAILURE",
        "STALE_DATA",
        "UNIVERSE_COLLAPSE",
        "CORPORATE_ACTION_ANOMALY",
        "OTHER",
    ] = "OTHER"
    severity: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    affected_symbols: list[str] = Field(default_factory=list)
    suggested_action: str = ""


class PortfolioExplanation(AdvisoryEnvelope):
    """Natural-language explanation of the formal quant result.

    This NEVER changes target weights.  It explains why the system chose a
    position, why it reduced, and what risks remain.
    """

    explanations: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    quant_impact: Literal["NONE", "SHADOW"] = "NONE"


class ResearchCopilotNote(AdvisoryEnvelope):
    """Diagnostics for factor failure, regime breakdown or calibration drift."""

    note_kind: Literal[
        "FACTOR_DIAGNOSTIC",
        "REGIME_BREAKDOWN",
        "PROBABILITY_DRIFT",
        "ATTRIBUTION_ANOMALY",
        "MODEL_DIAGNOSTIC",
    ] = "FACTOR_DIAGNOSTIC"
    quant_impact: Literal["NONE", "SHADOW"] = "NONE"


class ShadowFeatureSuggestion(AdvisoryEnvelope):
    """A proposed LLM shadow feature.

    It is research-only until strict OOS validation; it never enters production
    unilaterally.
    """

    feature_name: str = Field(min_length=1)
    feature_definition: str = Field(min_length=1)
    data_dependencies: list[str] = Field(default_factory=list)
    quant_impact: Literal["NONE", "SHADOW"] = "SHADOW"
    oos_validated: bool = False
