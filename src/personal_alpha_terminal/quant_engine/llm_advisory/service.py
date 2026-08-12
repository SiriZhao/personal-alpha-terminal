"""ROUND 9: advisory intelligence service.

The advisory layer consumes deterministic quant output and structured documents
and produces explanations/annotations.  It never changes a target weight, never
selects a stock, and never bypasses a formal gate.  All numeric inputs are
validated by the contract schemas before use.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from personal_alpha_terminal.quant_engine.llm_advisory.contracts import (
    AdvisoryEnvelope,
    DataAnomalyReport,
    PortfolioExplanation,
    ResearchCopilotNote,
    ShadowFeatureSuggestion,
)


@dataclass(frozen=True, slots=True)
class AdvisorySnapshot:
    status: str  # SHADOW / ADVISORY / UNAVAILABLE
    model: str
    pit_documents: int
    anomalies: tuple[DataAnomalyReport, ...]
    explanations: tuple[PortfolioExplanation, ...]
    copilot_notes: tuple[ResearchCopilotNote, ...]
    shadow_features: tuple[ShadowFeatureSuggestion, ...]
    quant_impact: str  # NONE / SHADOW
    fallback: str  # CLASSICAL_CHAMPION
    as_of: datetime

    def document(self) -> dict[str, object]:
        import json as _json

        payload = {
            "status": self.status,
            "model": self.model,
            "pit_documents": self.pit_documents,
            "anomalies": [item.model_dump() for item in self.anomalies],
            "explanations": [item.model_dump() for item in self.explanations],
            "copilot_notes": [item.model_dump() for item in self.copilot_notes],
            "shadow_features": [item.model_dump() for item in self.shadow_features],
            "quant_impact": self.quant_impact,
            "fallback": self.fallback,
            "as_of": self.as_of.isoformat(),
        }
        rendered = _json.loads(_json.dumps(payload, default=str, sort_keys=True))
        return cast(dict[str, object], rendered)


class AdvisoryIntelligenceService:
    """Deterministic advisory assembly; LLM calls are isolated by the guard.

    The service itself never calls a provider.  Callers inject validated
    contract outputs; the guard ensures any upstream failure degrades only the
    advisory layer.
    """

    def __init__(self) -> None:
        self._envelopes: list[AdvisoryEnvelope] = []

    def record(self, envelope: AdvisoryEnvelope) -> None:
        self._envelopes.append(envelope)

    def snapshot(
        self,
        *,
        model: str,
        pit_documents: int,
        quant_impact: str = "NONE",
        fallback: str = "CLASSICAL_CHAMPION",
        as_of: datetime | None = None,
    ) -> AdvisorySnapshot:
        if quant_impact not in {"NONE", "SHADOW"}:
            raise ValueError("quant_impact must be NONE or SHADOW")
        anomalies = tuple(item for item in self._envelopes if isinstance(item, DataAnomalyReport))
        explanations = tuple(
            item for item in self._envelopes if isinstance(item, PortfolioExplanation)
        )
        notes = tuple(item for item in self._envelopes if isinstance(item, ResearchCopilotNote))
        features = tuple(
            item for item in self._envelopes if isinstance(item, ShadowFeatureSuggestion)
        )
        status = "ADVISORY" if (anomalies or explanations or notes) else "SHADOW"
        return AdvisorySnapshot(
            status=status,
            model=model,
            pit_documents=pit_documents,
            anomalies=anomalies,
            explanations=explanations,
            copilot_notes=notes,
            shadow_features=features,
            quant_impact=quant_impact,
            fallback=fallback,
            as_of=as_of or datetime.now(UTC),
        )
