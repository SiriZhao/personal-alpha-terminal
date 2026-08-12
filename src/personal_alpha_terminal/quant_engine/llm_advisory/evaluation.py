"""ROUND 9: LLM evaluation.

An LLM is not adopted because it "sounds smart".  This module measures factual
grounding, temporal correctness, hallucination rate, consistency, structured
output validity, latency, cost and incremental quant value so any advisory or
shadow-feature decision is evidence-based.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True, slots=True)
class LLMEvaluation:
    provider: str
    model: str
    sample_size: int
    factual_grounding: float  # fraction of claims supported by evidence
    temporal_correctness: float  # fraction of outputs that respect the PIT cutoff
    hallucination_rate: float  # 1 - factual_grounding
    consistency: float  # fraction of repeated runs agreeing
    structured_output_validity: float  # fraction passing schema validation
    mean_latency_ms: float
    total_cost_usd: float
    incremental_quant_value: float | None  # None when no OOS comparison exists
    pass_thresholds: bool

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "sample_size": self.sample_size,
            "factual_grounding": self.factual_grounding,
            "temporal_correctness": self.temporal_correctness,
            "hallucination_rate": self.hallucination_rate,
            "consistency": self.consistency,
            "structured_output_validity": self.structured_output_validity,
            "mean_latency_ms": self.mean_latency_ms,
            "total_cost_usd": self.total_cost_usd,
            "incremental_quant_value": self.incremental_quant_value,
            "pass_thresholds": self.pass_thresholds,
        }


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    min_factual_grounding: float = 0.90
    min_temporal_correctness: float = 0.95
    max_hallucination_rate: float = 0.10
    min_consistency: float = 0.80
    min_structured_output_validity: float = 0.95
    max_mean_latency_ms: float = 8000.0
    max_total_cost_usd: float = 10.0


def evaluate_llm(
    *,
    provider: str,
    model: str,
    grounded: int,
    temporally_correct: int,
    consistent: int,
    schema_valid: int,
    total: int,
    repeated: int,
    latencies_ms: Sequence[float],
    total_cost_usd: float,
    incremental_quant_value: float | None = None,
    thresholds: EvaluationThresholds | None = None,
) -> LLMEvaluation:
    """Compute LLM evaluation metrics and the fixed pass/fail verdict."""
    if total <= 0:
        raise ValueError("LLM evaluation requires a positive sample")
    if repeated <= 0:
        repeated = total
    configured = thresholds or EvaluationThresholds()
    factual = grounded / total
    temporal = temporally_correct / total
    consistency = consistent / repeated
    schema = schema_valid / total
    latency = float(fmean(latencies_ms)) if latencies_ms else 0.0
    pass_thresholds = bool(
        factual >= configured.min_factual_grounding
        and temporal >= configured.min_temporal_correctness
        and (1 - factual) <= configured.max_hallucination_rate
        and consistency >= configured.min_consistency
        and schema >= configured.min_structured_output_validity
        and latency <= configured.max_mean_latency_ms
        and total_cost_usd <= configured.max_total_cost_usd
    )
    return LLMEvaluation(
        provider=provider,
        model=model,
        sample_size=total,
        factual_grounding=factual,
        temporal_correctness=temporal,
        hallucination_rate=1 - factual,
        consistency=consistency,
        structured_output_validity=schema,
        mean_latency_ms=latency,
        total_cost_usd=total_cost_usd,
        incremental_quant_value=incremental_quant_value,
        pass_thresholds=pass_thresholds,
    )
