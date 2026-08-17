"""Persistent, immutable forward evidence for Agentic Shadow observations.

The existing ``intelligence_research_results`` table is an append-only,
content-addressed store.  This module gives the Agentic Shadow path typed
logical records on top of that store without weakening its immutability
contract or introducing a second mutable ledger.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from statistics import mean, median
from typing import Any, Literal, cast

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal import __version__
from personal_alpha_terminal.application.agentic_shadow_service import (
    AgenticShadowEvidence,
)
from personal_alpha_terminal.application.quant_daily_service import TodayResult
from personal_alpha_terminal.intelligence.agentic_models import AgenticStrictModel
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models.intelligence import IntelligenceResearchResult

PREDICTION_TYPE = "SEMANTIC_FORWARD_PREDICTION"
OUTCOME_TYPE = "SEMANTIC_FORWARD_OUTCOME"
QUANT_COUNTERFACTUAL_TYPE = "QUANT_COUNTERFACTUAL"
HYBRID_COUNTERFACTUAL_TYPE = "HYBRID_COUNTERFACTUAL"
PROMOTION_EVALUATION_TYPE = "AGENTIC_PROMOTION_EVALUATION"
REAL_FORWARD_ORIGIN = "REAL_FORWARD"
EvidenceOrigin = Literal[
    "REAL_FORWARD",
    "NON_PRODUCTION",
    "TEST",
    "MOCK",
    "SYNTHETIC",
    "BACKTEST",
]


class PromotionReason(StrEnum):
    NO_FORWARD_EVIDENCE = "NO_FORWARD_EVIDENCE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    CALIBRATION_FAILED = "CALIBRATION_FAILED"
    NEGATIVE_INCREMENTAL_ALPHA = "NEGATIVE_INCREMENTAL_ALPHA"
    CI_NOT_POSITIVE = "CI_NOT_POSITIVE"
    COST_FAILURE = "COST_FAILURE"
    DRAWDOWN_FAILURE = "DRAWDOWN_FAILURE"
    TURNOVER_FAILURE = "TURNOVER_FAILURE"
    REGIME_INSTABILITY = "REGIME_INSTABILITY"
    DATA_CONTAMINATION = "DATA_CONTAMINATION"
    MODEL_VERSION_INCONSISTENT = "MODEL_VERSION_INCONSISTENT"
    PROMOTION_EVALUATION_FAILED = "PROMOTION_EVALUATION_FAILED"
    ELIGIBLE_FOR_PROMOTION_REVIEW = "ELIGIBLE_FOR_PROMOTION_REVIEW"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _payload_hash(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


class SemanticForwardPredictionRecord(AgenticStrictModel):
    prediction_id: str
    observation_id: str
    counterfactual_observation_id: str
    decision_timestamp: datetime
    information_cutoff: datetime
    security_id: str
    company_id: str
    symbol: str
    symbol_as_of_time: datetime
    quant_score: float
    quant_probability: float | None = None
    expected_alpha_value: float
    expected_alpha_semantics: str
    event_ids: tuple[str, ...] = ()
    event_provenance: tuple[dict[str, object], ...] = ()
    llm_provider: str
    llm_model: str
    llm_schema_version: str
    prompt_version: str
    structured_thesis: dict[str, object] | None = None
    debate_result: dict[str, object] = Field(default_factory=dict)
    semantic_score: float
    semantic_alpha: float
    shadow_lambda: float
    quant_target_weight: float
    hybrid_target_weight: float
    quant_risk_result: dict[str, object] = Field(default_factory=dict)
    hybrid_risk_result: dict[str, object] = Field(default_factory=dict)
    data_snapshot_identity: dict[str, str]
    code_model_version: str = __version__
    evaluation_horizons: tuple[str, ...] = ("1d", "5d", "10d", "20d")
    evidence_origin: EvidenceOrigin
    status: Literal["SHADOW", "DEGRADED"]
    failure_reason: str | None = None

    @field_validator(
        "prediction_id",
        "observation_id",
        "counterfactual_observation_id",
        "security_id",
        "company_id",
        "symbol",
        "expected_alpha_semantics",
        "llm_provider",
        "llm_model",
        "llm_schema_version",
        "prompt_version",
        "code_model_version",
    )
    @classmethod
    def required_text(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("decision_timestamp", "information_cutoff", "symbol_as_of_time")
    @classmethod
    def aware_time(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "quant_score",
        "quant_probability",
        "expected_alpha_value",
        "semantic_score",
        "semantic_alpha",
        "shadow_lambda",
        "quant_target_weight",
        "hybrid_target_weight",
    )
    @classmethod
    def finite_number(cls, value: float | None, info: Any) -> float | None:
        return _finite(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def validate_prediction_identity(self) -> SemanticForwardPredictionRecord:
        if self.information_cutoff > self.decision_timestamp:
            raise ValueError("information_cutoff cannot follow decision_timestamp")
        if self.symbol_as_of_time > self.information_cutoff:
            raise ValueError("symbol identity is newer than information cutoff")
        if self.quant_probability is not None and not 0 <= self.quant_probability <= 1:
            raise ValueError("quant_probability must be between 0 and 1")
        if not self.data_snapshot_identity:
            raise ValueError("data_snapshot_identity is required")
        return self


class SemanticForwardOutcomeRecord(AgenticStrictModel):
    outcome_id: str
    prediction_id: str
    observation_id: str
    decision_timestamp: datetime
    outcome_timestamp: datetime
    evaluation_horizon: str
    security_id: str
    symbol_as_of_time: datetime
    quant_net_return: float
    hybrid_net_return: float
    benchmark_return: float
    quant_cost: float
    hybrid_cost: float
    quant_turnover: float
    hybrid_turnover: float
    quant_drawdown: float
    hybrid_drawdown: float
    data_snapshot_identity: dict[str, str]
    source_identity: str
    regime: str
    evidence_origin: EvidenceOrigin

    @field_validator(
        "outcome_id",
        "prediction_id",
        "observation_id",
        "evaluation_horizon",
        "security_id",
        "source_identity",
        "regime",
    )
    @classmethod
    def outcome_text(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("decision_timestamp", "outcome_timestamp", "symbol_as_of_time")
    @classmethod
    def outcome_time(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator(
        "quant_net_return",
        "hybrid_net_return",
        "benchmark_return",
        "quant_cost",
        "hybrid_cost",
        "quant_turnover",
        "hybrid_turnover",
        "quant_drawdown",
        "hybrid_drawdown",
    )
    @classmethod
    def outcome_finite(cls, value: float, info: Any) -> float:
        return _finite(value, info.field_name)

    @model_validator(mode="after")
    def validate_outcome_time(self) -> SemanticForwardOutcomeRecord:
        if self.outcome_timestamp <= self.decision_timestamp:
            raise ValueError("outcome must be appended after decision_timestamp")
        return self


class _CounterfactualRecord(AgenticStrictModel):
    counterfactual_id: str
    observation_id: str
    decision_timestamp: datetime
    information_cutoff: datetime
    security_ids: tuple[str, ...]
    universe_identity: str
    evaluation_horizon: str
    execution_assumptions_hash: str
    transaction_cost_model: str
    slippage_model: str
    benchmark_convention: str
    data_version: str
    target_weights: dict[str, float]
    current_weights: dict[str, float]
    risk_result: dict[str, object]
    optimizer_result: dict[str, object]
    outcome_available: bool = False

    @field_validator(
        "counterfactual_id",
        "observation_id",
        "universe_identity",
        "evaluation_horizon",
        "execution_assumptions_hash",
        "transaction_cost_model",
        "slippage_model",
        "benchmark_convention",
        "data_version",
    )
    @classmethod
    def counterfactual_text(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("decision_timestamp", "information_cutoff")
    @classmethod
    def counterfactual_time(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("target_weights", "current_weights")
    @classmethod
    def weights_finite(cls, value: dict[str, float], info: Any) -> dict[str, float]:
        if any(not math.isfinite(float(item)) for item in value.values()):
            raise ValueError(f"{info.field_name} must contain finite values")
        return value

    @model_validator(mode="after")
    def validate_counterfactual_pair(self) -> _CounterfactualRecord:
        if self.information_cutoff > self.decision_timestamp:
            raise ValueError("counterfactual cutoff cannot follow decision")
        if not self.security_ids:
            raise ValueError("counterfactual security_ids cannot be empty")
        if set(self.target_weights) - set(self.security_ids):
            raise ValueError("target weights contain an unpaired security")
        return self


class QuantCounterfactualRecord(_CounterfactualRecord):
    strategy: Literal["QUANT"] = "QUANT"


class HybridCounterfactualRecord(_CounterfactualRecord):
    strategy: Literal["HYBRID"] = "HYBRID"


class PromotionEvaluationRecord(AgenticStrictModel):
    evaluation_id: str
    evaluated_at: datetime
    status: str
    promotion_reason: str
    reason_codes: tuple[str, ...]
    real_forward_n: int
    minimum_required_n: int
    paired_sample_n: int
    incremental_alpha: float | None = None
    median_incremental_alpha: float | None = None
    confidence_interval: tuple[float, float] | None = None
    hit_rate: float | None = None
    calibration_status: str
    regime_coverage: tuple[str, ...] = ()
    cost_delta: float | None = None
    drawdown_delta: float | None = None
    turnover_delta: float | None = None
    contaminated_n: int = 0
    model_versions: tuple[str, ...] = ()
    production_lambda: float = 0.0
    human_approval_required: bool = True

    @field_validator("evaluation_id", "status", "promotion_reason")
    @classmethod
    def evaluation_text(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("evaluated_at")
    @classmethod
    def evaluation_time(cls, value: datetime) -> datetime:
        return _aware(value, "evaluated_at")

    @field_validator("production_lambda")
    @classmethod
    def lambda_zero(cls, value: float) -> float:
        _finite(value, "production_lambda")
        if value != 0.0:
            raise ValueError("production_lambda must remain zero in ROUND56-58")
        return value

    @model_validator(mode="after")
    def promotion_cannot_activate(self) -> PromotionEvaluationRecord:
        if not self.human_approval_required:
            raise ValueError("human approval must remain required")
        return self


class RuntimePromotionPolicy(AgenticStrictModel):
    minimum_required_n: int = Field(default=120, ge=120)
    minimum_incremental_alpha: float = Field(default=0.0, ge=0.0)
    maximum_calibration_error: float = Field(default=0.2, ge=0, le=0.2)
    maximum_turnover_delta: float = Field(default=0.05, ge=0, le=0.05)
    maximum_drawdown_delta: float = Field(default=0.02, ge=0, le=0.02)
    minimum_regimes: int = Field(default=2, ge=2)
    bootstrap_draws: int = Field(default=2_000, ge=1_000)


class AgenticForwardEvidenceLedger:
    """Typed append-only access to persisted Shadow forward evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = IntelligenceRepository(session)

    def append_prediction(self, record: SemanticForwardPredictionRecord) -> bool:
        existing = self._by_observation(PREDICTION_TYPE, record.observation_id)
        if existing:
            candidate = record.model_dump(mode="json")
            if _prediction_semantics(existing) != _prediction_semantics(candidate):
                raise ValueError("prediction observation identity is immutable")
            return False
        return self._append(
            result_id=record.prediction_id,
            result_type=PREDICTION_TYPE,
            model_version=record.code_model_version,
            prompt_version=record.prompt_version,
            data_cutoff=record.information_cutoff,
            status=record.status,
            payload=record.model_dump(mode="json"),
        )

    def append_outcome(self, record: SemanticForwardOutcomeRecord) -> bool:
        prediction = self._find_result(PREDICTION_TYPE, record.prediction_id)
        if prediction is None:
            raise ValueError("outcome references unknown prediction")
        prediction_payload = prediction.payload
        outcome_payload = record.model_dump(mode="json")
        if (
            prediction_payload.get("observation_id") != record.observation_id
            or prediction_payload.get("security_id") != record.security_id
            or prediction_payload.get("decision_timestamp")
            != outcome_payload.get("decision_timestamp")
        ):
            raise ValueError("outcome identity does not match immutable prediction")
        return self._append(
            result_id=record.outcome_id,
            result_type=OUTCOME_TYPE,
            model_version=str(prediction.model_version),
            prompt_version=str(prediction.prompt_version),
            data_cutoff=record.outcome_timestamp,
            status="REALIZED_FORWARD_OUTCOME",
            payload=outcome_payload,
        )

    def append_quant_counterfactual(self, record: QuantCounterfactualRecord) -> bool:
        return self._append_counterfactual(record, QUANT_COUNTERFACTUAL_TYPE)

    def append_hybrid_counterfactual(self, record: HybridCounterfactualRecord) -> bool:
        return self._append_counterfactual(record, HYBRID_COUNTERFACTUAL_TYPE)

    def append_promotion_evaluation(self, record: PromotionEvaluationRecord) -> bool:
        return self._append(
            result_id=record.evaluation_id,
            result_type=PROMOTION_EVALUATION_TYPE,
            model_version=__version__,
            prompt_version="promotion-policy-v1",
            data_cutoff=record.evaluated_at,
            status=record.status,
            payload=record.model_dump(mode="json"),
        )

    def records(self, result_type: str) -> tuple[dict[str, object], ...]:
        rows = self.session.scalars(
            select(IntelligenceResearchResult)
            .where(IntelligenceResearchResult.result_type == result_type)
            .order_by(IntelligenceResearchResult.data_cutoff, IntelligenceResearchResult.result_id)
        )
        return tuple(dict(row.payload) for row in rows)

    def _append_counterfactual(
        self,
        record: QuantCounterfactualRecord | HybridCounterfactualRecord,
        result_type: str,
    ) -> bool:
        return self._append(
            result_id=record.counterfactual_id,
            result_type=result_type,
            model_version=__version__,
            prompt_version="agentic-counterfactual-v1",
            data_cutoff=record.information_cutoff,
            status=record.strategy,
            payload=record.model_dump(mode="json"),
        )

    def _append(
        self,
        *,
        result_id: str,
        result_type: str,
        model_version: str,
        prompt_version: str,
        data_cutoff: datetime,
        status: str,
        payload: dict[str, object],
    ) -> bool:
        existing = self._find_result(result_type, result_id)
        if existing is not None:
            if existing.result_hash != _payload_hash(payload):
                raise ValueError(f"{result_type} identity is immutable")
            return False
        self.repository.add_result(
            result_id=result_id,
            result_type=result_type,
            schema_version="agentic-forward-evidence-v1",
            model_version=model_version,
            prompt_version=prompt_version,
            data_cutoff=_aware(data_cutoff, "data_cutoff"),
            status=status,
            payload=payload,
        )
        self.session.flush()
        return True

    def _find_result(
        self,
        result_type: str,
        result_id: str,
    ) -> IntelligenceResearchResult | None:
        return self.session.scalar(
            select(IntelligenceResearchResult).where(
                IntelligenceResearchResult.result_type == result_type,
                IntelligenceResearchResult.result_id == result_id,
            )
        )

    def _by_observation(
        self,
        result_type: str,
        observation_id: str,
    ) -> dict[str, object] | None:
        row = self.session.scalar(
            select(IntelligenceResearchResult)
            .where(IntelligenceResearchResult.result_type == result_type)
            .order_by(IntelligenceResearchResult.data_cutoff)
        )
        for candidate in self.records(result_type):
            if candidate.get("observation_id") == observation_id:
                return candidate
        del row
        return None


def append_daily_shadow_evidence(
    session: Session,
    *,
    workflow: TodayResult,
    hybrid_document: dict[str, object],
    evidence: AgenticShadowEvidence,
    run_id: str,
    decision_id: str,
    evidence_origin: EvidenceOrigin,
) -> dict[str, int]:
    """Persist one immutable prediction per bound security and one paired portfolio."""

    context = workflow.shadow_context
    if context is None:
        return {"predictions": 0, "counterfactuals": 0}
    status_payload = hybrid_document.get("status")
    status = status_payload if isinstance(status_payload, dict) else {}
    provider = str(status.get("provider", "UNAVAILABLE"))
    model = str(status.get("model", "UNAVAILABLE"))
    inferences = hybrid_document.get("llm_inferences")
    inference_rows = inferences if isinstance(inferences, list) else []
    theses = hybrid_document.get("structured_theses")
    thesis_rows = theses if isinstance(theses, dict) else {}
    debates = hybrid_document.get("debates")
    debate_rows = debates if isinstance(debates, dict) else {}
    rankings = hybrid_document.get("shadow_ranking")
    ranking_rows = rankings if isinstance(rankings, list) else []
    ranking_by_symbol = {
        str(item.get("symbol")): item
        for item in ranking_rows
        if isinstance(item, dict) and item.get("symbol")
    }
    securities = hybrid_document.get("securities")
    security_rows = securities if isinstance(securities, list) else []
    security_by_symbol = {
        str(item.get("symbol")): item
        for item in security_rows
        if isinstance(item, dict) and item.get("symbol")
    }
    actions = hybrid_document.get("actions")
    action_rows = actions if isinstance(actions, list) else []
    action_by_symbol = {
        str(item.get("symbol")): item
        for item in action_rows
        if isinstance(item, dict) and item.get("symbol")
    }
    degradation = hybrid_document.get("degradation")
    degradation_rows = degradation if isinstance(degradation, dict) else {}
    by_symbol = degradation_rows.get("by_symbol")
    failures = by_symbol if isinstance(by_symbol, dict) else {}
    ledger = AgenticForwardEvidenceLedger(session)
    factors_with_identity = tuple(
        evidence.companies[factor.symbol]
        for factor in workflow.factors
        if factor.symbol in evidence.companies
    )
    if not factors_with_identity:
        return {"predictions": 0, "counterfactuals": 0}
    security_ids = tuple(
        company.security.permanent_security_id
        for company in factors_with_identity
    )
    portfolio_observation = _identity(
        "portfolio",
        decision_id,
        workflow.decision_time.isoformat(),
        workflow.universe_snapshot_id,
        "|".join(security_ids),
        "1d|5d|10d|20d",
    )
    prediction_count = 0
    for factor in workflow.factors:
        company = evidence.companies.get(factor.symbol)
        security_row = security_by_symbol.get(factor.symbol)
        if company is None or security_row is None:
            continue
        action = action_by_symbol.get(factor.symbol, {})
        ranking = ranking_by_symbol.get(factor.symbol, {})
        trace = workflow.probability_counterfactual.get(factor.symbol, {})
        failure = failures.get(factor.symbol)
        failure_reason = (
            ",".join(str(item) for item in failure)
            if isinstance(failure, list)
            else None
        )
        observation_id = _identity(
            "security",
            decision_id,
            workflow.decision_time.isoformat(),
            company.security.permanent_security_id,
            "1d|5d|10d|20d",
        )
        prediction_id = _identity("prediction", observation_id, run_id)
        inference = _matching_inference(inference_rows, company.events)
        thesis = thesis_rows.get(factor.symbol)
        debate = debate_rows.get(factor.symbol, {})
        record = SemanticForwardPredictionRecord(
            prediction_id=prediction_id,
            observation_id=observation_id,
            counterfactual_observation_id=portfolio_observation,
            decision_timestamp=workflow.decision_time,
            information_cutoff=workflow.data_cutoff or workflow.decision_time,
            security_id=company.security.permanent_security_id,
            company_id=company.security.company_id,
            symbol=company.security.symbol,
            symbol_as_of_time=company.security.symbol_as_of_time,
            quant_score=float(factor.composite),
            quant_probability=_number(trace.get("conditional_probability")),
            expected_alpha_value=float(factor.expected_alpha),
            expected_alpha_semantics="DETERMINISTIC_QUANT_ENGINE_ESTIMATE",
            event_ids=tuple(event.event_id for event in company.events),
            event_provenance=tuple(
                event.model_dump(mode="json") for event in company.events
            ),
            llm_provider=provider,
            llm_model=model,
            llm_schema_version=str(
                inference.get("schema_version_used", "company-thesis-v1")
            ),
            prompt_version=str(inference.get("prompt_version", "company-thesis-v2")),
            structured_thesis=thesis if isinstance(thesis, dict) else None,
            debate_result=debate if isinstance(debate, dict) else {},
            semantic_score=_number(ranking.get("semantic_score")) or 0.0,
            semantic_alpha=_number(security_row.get("applied_llm_adjustment")) or 0.0,
            shadow_lambda=_number(
                _safe_dict(hybrid_document.get("decision_attribution")).get(
                    "shadow_lambda"
                )
            )
            or 0.0,
            quant_target_weight=_number(action.get("quant_only_target")) or 0.0,
            hybrid_target_weight=_number(action.get("hybrid_target")) or 0.0,
            quant_risk_result=_safe_dict(workflow.risk),
            hybrid_risk_result=_safe_dict(hybrid_document.get("shadow_pipeline")),
            data_snapshot_identity={
                "market_data_hash": workflow.data_hash,
                "model_hash": workflow.model_hash,
                "config_hash": workflow.config_hash,
                "universe_snapshot_id": workflow.universe_snapshot_id,
                "decision_id": decision_id,
            },
            status="DEGRADED" if failure_reason else "SHADOW",
            failure_reason=failure_reason,
            evidence_origin=evidence_origin,
        )
        if ledger.append_prediction(record):
            prediction_count += 1

    shadow_pipeline = hybrid_document.get("shadow_pipeline")
    pipeline = shadow_pipeline if isinstance(shadow_pipeline, dict) else {}
    assumptions = {
        "execution_assumptions_hash": _identity(
            "execution", "manual-only", workflow.config_hash
        ),
        "transaction_cost_model": workflow.config_hash,
        "slippage_model": workflow.config_hash,
        "benchmark_convention": workflow.benchmark_symbol,
        "data_version": workflow.data_hash,
    }
    security_id_by_symbol = {
        company.security.symbol: company.security.permanent_security_id
        for company in factors_with_identity
    }
    quant_targets = (
        {
            security_id_by_symbol[symbol]: float(weight)
            for symbol, weight in workflow.target.target_weights.items()
            if symbol in security_id_by_symbol
        }
        if workflow.target is not None
        else {}
    )
    hybrid_targets = {
        security_id_by_symbol[symbol]: float(weight)
        for symbol, weight in pipeline.get("target_weights", {}).items()
        if symbol in security_id_by_symbol
    }
    common = {
        "observation_id": portfolio_observation,
        "decision_timestamp": workflow.decision_time,
        "information_cutoff": workflow.data_cutoff or workflow.decision_time,
        "security_ids": security_ids,
        "universe_identity": workflow.universe_snapshot_id,
        "evaluation_horizon": "1d|5d|10d|20d",
        **assumptions,
        "current_weights": {
            security_id_by_symbol[symbol]: float(weight)
            for symbol, weight in (workflow.current_weights or {}).items()
            if symbol in security_id_by_symbol
        },
        "risk_result": _safe_dict(pipeline),
        "optimizer_result": {
            "target_weights": quant_targets,
            "shadow_target_weights": hybrid_targets,
            "pipeline_status": pipeline.get("status", "NOT_RUN"),
        },
    }
    quant_record = QuantCounterfactualRecord(
        counterfactual_id=_identity("quant-counterfactual", portfolio_observation),
        target_weights=quant_targets,
        **common,
    )
    hybrid_record = HybridCounterfactualRecord(
        counterfactual_id=_identity("hybrid-counterfactual", portfolio_observation),
        target_weights=hybrid_targets,
        **common,
    )
    quant_added = ledger.append_quant_counterfactual(quant_record)
    hybrid_added = ledger.append_hybrid_counterfactual(hybrid_record)
    return {
        "predictions": prediction_count,
        "counterfactuals": int(quant_added) + int(hybrid_added),
    }


def evaluate_runtime_promotion(
    ledger: AgenticForwardEvidenceLedger,
    *,
    evaluated_at: datetime,
    evaluation_id: str,
    policy: RuntimePromotionPolicy | None = None,
) -> PromotionEvaluationRecord:
    """Evaluate only real, paired, immutable forward outcomes and stay fail-closed."""

    active_policy = policy or RuntimePromotionPolicy()
    evaluation_time = _aware(evaluated_at, "evaluated_at")
    prediction_rows = ledger.records(PREDICTION_TYPE)
    outcome_rows = ledger.records(OUTCOME_TYPE)
    quant_rows = ledger.records(QUANT_COUNTERFACTUAL_TYPE)
    hybrid_rows = ledger.records(HYBRID_COUNTERFACTUAL_TYPE)
    predictions: dict[str, SemanticForwardPredictionRecord] = {}
    outcomes: list[SemanticForwardOutcomeRecord] = []
    contaminated = 0
    for row in prediction_rows:
        try:
            prediction = SemanticForwardPredictionRecord.model_validate(row)
        except ValueError:
            contaminated += 1
            continue
        if prediction.evidence_origin != REAL_FORWARD_ORIGIN:
            contaminated += 1
            continue
        if prediction.decision_timestamp > evaluation_time:
            contaminated += 1
            continue
        if prediction.status != "SHADOW" or prediction.structured_thesis is None:
            continue
        predictions[prediction.prediction_id] = prediction
    for row in outcome_rows:
        try:
            outcome = SemanticForwardOutcomeRecord.model_validate(row)
        except ValueError:
            contaminated += 1
            continue
        if outcome.evidence_origin != REAL_FORWARD_ORIGIN:
            contaminated += 1
            continue
        if outcome.outcome_timestamp > evaluation_time:
            contaminated += 1
            continue
        outcomes.append(outcome)
    quant_pairs = _counterfactuals_by_observation(quant_rows, "QUANT")
    hybrid_pairs = _counterfactuals_by_observation(hybrid_rows, "HYBRID")
    real_matches: list[
        tuple[SemanticForwardPredictionRecord, SemanticForwardOutcomeRecord]
    ] = []
    paired: list[
        tuple[SemanticForwardPredictionRecord, SemanticForwardOutcomeRecord]
    ] = []
    for outcome in outcomes:
        matched_prediction = predictions.get(outcome.prediction_id)
        if matched_prediction is None:
            contaminated += 1
            continue
        real_matches.append((matched_prediction, outcome))
        quant = quant_pairs.get(matched_prediction.counterfactual_observation_id)
        hybrid = hybrid_pairs.get(matched_prediction.counterfactual_observation_id)
        if quant is None or hybrid is None or not _counterfactuals_match(quant, hybrid):
            continue
        paired.append((matched_prediction, outcome))

    real_forward_n = len(real_matches)
    paired_sample_n = len(paired)
    model_versions = tuple(
        sorted(
            {
                "|".join(
                    (
                        prediction.llm_provider,
                        prediction.llm_model,
                        prediction.prompt_version,
                        prediction.code_model_version,
                    )
                )
                for prediction, _ in paired
            }
        )
    )
    increments = [
        outcome.hybrid_net_return - outcome.quant_net_return
        for _, outcome in paired
    ]
    cost_deltas = [
        outcome.hybrid_cost - outcome.quant_cost for _, outcome in paired
    ]
    turnover_deltas = [
        outcome.hybrid_turnover - outcome.quant_turnover for _, outcome in paired
    ]
    drawdown_deltas = [
        outcome.hybrid_drawdown - outcome.quant_drawdown for _, outcome in paired
    ]
    regime_coverage = tuple(sorted({outcome.regime for _, outcome in paired}))
    incremental_alpha = mean(increments) if increments else None
    median_incremental = median(increments) if increments else None
    hit_rate = (
        sum(value > 0 for value in increments) / len(increments)
        if increments
        else None
    )
    cost_delta = mean(cost_deltas) if cost_deltas else None
    turnover_delta = mean(turnover_deltas) if turnover_deltas else None
    drawdown_delta = mean(drawdown_deltas) if drawdown_deltas else None
    confidence_interval = (
        _cluster_bootstrap_interval(paired, active_policy.bootstrap_draws)
        if increments
        else None
    )
    calibration_error = (
        mean(
            abs(
                max(0.0, min(1.0, (prediction.semantic_score + 1.0) / 2.0))
                - float(outcome.hybrid_net_return > outcome.quant_net_return)
            )
            for prediction, outcome in paired
        )
        if paired
        else None
    )
    calibration_status = (
        "PASS"
        if calibration_error is not None
        and calibration_error <= active_policy.maximum_calibration_error
        else "FAILED"
        if calibration_error is not None
        else "INSUFFICIENT_EVIDENCE"
    )
    reason = _promotion_reason(
        real_forward_n=real_forward_n,
        paired_sample_n=paired_sample_n,
        contaminated=contaminated,
        model_versions=model_versions,
        increments=increments,
        cost_deltas=cost_deltas,
        incremental_alpha=incremental_alpha,
        confidence_interval=confidence_interval,
        calibration_status=calibration_status,
        turnover_delta=turnover_delta,
        drawdown_delta=drawdown_delta,
        regime_coverage=regime_coverage,
        paired=paired,
        policy=active_policy,
    )
    status = (
        "ELIGIBLE_FOR_PROMOTION_REVIEW"
        if reason is PromotionReason.ELIGIBLE_FOR_PROMOTION_REVIEW
        else "NO_FORWARD_EVIDENCE"
        if reason is PromotionReason.NO_FORWARD_EVIDENCE
        else "INSUFFICIENT_EVIDENCE"
        if reason is PromotionReason.INSUFFICIENT_SAMPLE
        else "BLOCKED"
    )
    return PromotionEvaluationRecord(
        evaluation_id=evaluation_id,
        evaluated_at=evaluation_time,
        status=status,
        promotion_reason=reason.value,
        reason_codes=(reason.value,),
        real_forward_n=real_forward_n,
        minimum_required_n=active_policy.minimum_required_n,
        paired_sample_n=paired_sample_n,
        incremental_alpha=incremental_alpha,
        median_incremental_alpha=median_incremental,
        confidence_interval=confidence_interval,
        hit_rate=hit_rate,
        calibration_status=calibration_status,
        regime_coverage=regime_coverage,
        cost_delta=cost_delta,
        drawdown_delta=drawdown_delta,
        turnover_delta=turnover_delta,
        contaminated_n=contaminated,
        model_versions=model_versions,
        production_lambda=0.0,
        human_approval_required=True,
    )


def _promotion_reason(
    *,
    real_forward_n: int,
    paired_sample_n: int,
    contaminated: int,
    model_versions: tuple[str, ...],
    increments: list[float],
    cost_deltas: list[float],
    incremental_alpha: float | None,
    confidence_interval: tuple[float, float] | None,
    calibration_status: str,
    turnover_delta: float | None,
    drawdown_delta: float | None,
    regime_coverage: tuple[str, ...],
    paired: list[tuple[SemanticForwardPredictionRecord, SemanticForwardOutcomeRecord]],
    policy: RuntimePromotionPolicy,
) -> PromotionReason:
    if not real_forward_n and not contaminated:
        return PromotionReason.NO_FORWARD_EVIDENCE
    if contaminated:
        return PromotionReason.DATA_CONTAMINATION
    if paired_sample_n < policy.minimum_required_n:
        return PromotionReason.INSUFFICIENT_SAMPLE
    if len(model_versions) != 1:
        return PromotionReason.MODEL_VERSION_INCONSISTENT
    if calibration_status != "PASS":
        return PromotionReason.CALIBRATION_FAILED
    if incremental_alpha is None:
        return PromotionReason.INSUFFICIENT_SAMPLE
    gross_increment = mean(
        increment + cost_delta
        for increment, cost_delta in zip(increments, cost_deltas, strict=True)
    )
    if incremental_alpha <= policy.minimum_incremental_alpha:
        if gross_increment > policy.minimum_incremental_alpha:
            return PromotionReason.COST_FAILURE
        return PromotionReason.NEGATIVE_INCREMENTAL_ALPHA
    if confidence_interval is None or confidence_interval[0] <= 0:
        return PromotionReason.CI_NOT_POSITIVE
    if drawdown_delta is None or drawdown_delta > policy.maximum_drawdown_delta:
        return PromotionReason.DRAWDOWN_FAILURE
    if turnover_delta is None or turnover_delta > policy.maximum_turnover_delta:
        return PromotionReason.TURNOVER_FAILURE
    regime_means = {
        regime: mean(
            outcome.hybrid_net_return - outcome.quant_net_return
            for _, outcome in paired
            if outcome.regime == regime
        )
        for regime in regime_coverage
    }
    if (
        len(regime_coverage) < policy.minimum_regimes
        or any(value <= 0 for value in regime_means.values())
    ):
        return PromotionReason.REGIME_INSTABILITY
    return PromotionReason.ELIGIBLE_FOR_PROMOTION_REVIEW


def _counterfactuals_by_observation(
    rows: tuple[dict[str, object], ...],
    strategy: Literal["QUANT", "HYBRID"],
) -> dict[str, QuantCounterfactualRecord | HybridCounterfactualRecord]:
    result: dict[str, QuantCounterfactualRecord | HybridCounterfactualRecord] = {}
    model = QuantCounterfactualRecord if strategy == "QUANT" else HybridCounterfactualRecord
    for row in rows:
        try:
            record = model.model_validate(row)
        except ValueError:
            continue
        result.setdefault(record.observation_id, record)
    return result


def _counterfactuals_match(
    quant: QuantCounterfactualRecord | HybridCounterfactualRecord,
    hybrid: QuantCounterfactualRecord | HybridCounterfactualRecord,
) -> bool:
    fields = (
        "observation_id",
        "decision_timestamp",
        "information_cutoff",
        "security_ids",
        "universe_identity",
        "evaluation_horizon",
        "execution_assumptions_hash",
        "transaction_cost_model",
        "slippage_model",
        "benchmark_convention",
        "data_version",
    )
    return all(getattr(quant, field) == getattr(hybrid, field) for field in fields)


def _cluster_bootstrap_interval(
    paired: list[tuple[SemanticForwardPredictionRecord, SemanticForwardOutcomeRecord]],
    draws: int,
) -> tuple[float, float]:
    by_session: dict[str, list[float]] = {}
    for prediction, outcome in paired:
        key = prediction.decision_timestamp.date().isoformat()
        by_session.setdefault(key, []).append(
            outcome.hybrid_net_return - outcome.quant_net_return
        )
    cluster_means = [mean(values) for values in by_session.values()]
    if not cluster_means:
        raise ValueError("bootstrap requires paired observations")
    rng = random.Random(42)
    samples = sorted(
        mean(rng.choice(cluster_means) for _ in cluster_means)
        for _ in range(draws)
    )
    low = samples[int(0.025 * (len(samples) - 1))]
    high = samples[int(0.975 * (len(samples) - 1))]
    return low, high


def _identity(prefix: str, *parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return f"{prefix}-{sha256(payload).hexdigest()[:24]}"


def _prediction_semantics(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "prediction_id"}


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if hasattr(value, "__dataclass_fields__"):
        dumped = asdict(cast(Any, value))
        normalized = json.loads(json.dumps(dumped, default=str))
        return dict(normalized) if isinstance(normalized, dict) else {}
    return {"value": str(value)}


def _matching_inference(
    inferences: list[object],
    events: tuple[object, ...],
) -> dict[str, object]:
    event_ids = {getattr(event, "event_id", "") for event in events}
    for item in inferences:
        if not isinstance(item, dict):
            continue
        if event_ids.intersection(str(value) for value in item.get("event_ids", [])):
            return item
    return {}
