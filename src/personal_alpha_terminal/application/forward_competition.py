"""ROUND79 immutable five-policy Forward Shadow competition ledger.

The record store used by :mod:`forward_evidence` is append-only and
content-addressed.  This module adds one aligned, real-forward decision set for
each valid Forward Shadow decision without changing the production target,
optimizer, risk wall, execution path, or promotion authority.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal import __version__
from personal_alpha_terminal.application.agentic_shadow_service import AgenticShadowEvidence
from personal_alpha_terminal.application.quant_daily_service import TodayResult
from personal_alpha_terminal.intelligence.agentic_models import AgenticStrictModel
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models.intelligence import IntelligenceResearchResult
from personal_alpha_terminal.research.portfolio_competition import (
    DecisionFreeze,
    EvidenceClass,
    OutcomeRecord,
    OutcomeStatus,
    PortfolioVariant,
    TournamentDecision,
    build_tournament,
)

FORWARD_COMPETITION_DECISION_TYPE = "FORWARD_COMPETITION_DECISION_SET"
FORWARD_COMPETITION_OUTCOME_TYPE = "FORWARD_COMPETITION_OUTCOME"
FORWARD_COMPETITION_SCHEMA_VERSION = "forward-competition-v1"
SUPPORTED_EVALUATION_HORIZONS = ("1d", "5d", "10d", "20d")


class ForwardVariantState(str):
    SHADOW = "SHADOW"
    DEGRADED_FALLBACK = "DEGRADED_FALLBACK"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ForwardCompetitionDecisionSet(AgenticStrictModel):
    """Five synchronized decision freezes attached to one real forward session."""

    schema_version: str = FORWARD_COMPETITION_SCHEMA_VERSION
    competition_id: str
    tournament: TournamentDecision
    permanent_security_ids: tuple[str, ...]
    symbol_to_security_id: dict[str, str]
    current_weights: dict[str, float]
    universe_hash: str
    data_hash: str
    evaluation_horizons: tuple[str, ...] = SUPPORTED_EVALUATION_HORIZONS
    variant_states: dict[PortfolioVariant, Literal["SHADOW", "DEGRADED_FALLBACK"]]
    variant_reason_codes: dict[PortfolioVariant, tuple[str, ...]]
    evidence_origin: Literal["REAL_FORWARD"]
    created_at: datetime
    decision_set_hash: str = ""

    @field_validator("competition_id", "universe_hash", "data_hash")
    @classmethod
    def required_text(cls, value: str, info: object) -> str:
        return _required(value, str(getattr(info, "field_name", "field")))

    @field_validator("created_at")
    @classmethod
    def created_at_aware(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")

    @model_validator(mode="after")
    def validate_competition(self) -> ForwardCompetitionDecisionSet:
        variants = {item.variant for item in self.tournament.variants}
        if variants != set(PortfolioVariant):
            raise ValueError("forward competition requires every synchronized policy variant")
        if len({item.symbols for item in self.tournament.variants}) != 1:
            raise ValueError("forward competition variants must share frozen symbols")
        if not self.permanent_security_ids or len(set(self.permanent_security_ids)) != len(
            self.permanent_security_ids
        ):
            raise ValueError("permanent_security_ids must be non-empty and unique")
        if any(not item.strip() for item in self.permanent_security_ids):
            raise ValueError("permanent_security_ids cannot contain empty values")
        if set(self.symbol_to_security_id) != set(self.tournament.variants[0].symbols):
            raise ValueError("symbol identity mapping must exactly match frozen symbols")
        if set(self.symbol_to_security_id.values()) - set(self.permanent_security_ids):
            raise ValueError("symbol mapping references an unknown permanent security identity")
        if set(self.current_weights) - set(self.permanent_security_ids):
            raise ValueError("current weights reference an unknown permanent security identity")
        if any(
            not math.isfinite(float(value)) or value < 0
            for value in self.current_weights.values()
        ) or sum(self.current_weights.values()) > 1 + 1e-9:
            raise ValueError("current weights must be finite and long-only")
        if (
            tuple(self.evaluation_horizons) != SUPPORTED_EVALUATION_HORIZONS
            or len(set(self.evaluation_horizons)) != len(self.evaluation_horizons)
        ):
            raise ValueError("forward competition horizons must be the supported immutable set")
        if set(self.variant_states) != variants or set(self.variant_reason_codes) != variants:
            raise ValueError("every variant needs an explicit forward competition state")
        for variant, state in self.variant_states.items():
            if state == ForwardVariantState.DEGRADED_FALLBACK and not self.variant_reason_codes[
                variant
            ]:
                raise ValueError("degraded fallback variants require a reason code")
        expected = _hash(self.model_dump(exclude={"decision_set_hash"}, mode="json"))
        if self.decision_set_hash and self.decision_set_hash != expected:
            raise ValueError("forward competition decision_set_hash is invalid")
        object.__setattr__(self, "decision_set_hash", expected)
        return self


class ForwardCompetitionOutcome(AgenticStrictModel):
    """One immutable outcome for a frozen policy and legal forward horizon."""

    schema_version: str = FORWARD_COMPETITION_SCHEMA_VERSION
    competition_id: str
    decision_set_hash: str
    evaluation_horizon: str
    outcome: OutcomeRecord
    data_snapshot_identity: dict[str, str]
    source_identity: str
    evidence_origin: Literal["REAL_FORWARD"]
    outcome_hash: str = ""

    @field_validator(
        "competition_id", "decision_set_hash", "evaluation_horizon", "source_identity"
    )
    @classmethod
    def outcome_text(cls, value: str, info: object) -> str:
        return _required(value, str(getattr(info, "field_name", "field")))

    @model_validator(mode="after")
    def validate_forward_outcome(self) -> ForwardCompetitionOutcome:
        if self.evaluation_horizon not in SUPPORTED_EVALUATION_HORIZONS:
            raise ValueError("forward competition outcome horizon is unsupported")
        if self.outcome.status is not OutcomeStatus.COMPLETE:
            raise ValueError("forward competition outcomes must be complete realized outcomes")
        if not self.data_snapshot_identity:
            raise ValueError("forward competition outcome requires data snapshot identity")
        expected = _hash(self.model_dump(exclude={"outcome_hash"}, mode="json"))
        if self.outcome_hash and self.outcome_hash != expected:
            raise ValueError("forward competition outcome_hash is invalid")
        object.__setattr__(self, "outcome_hash", expected)
        return self


class ForwardCompetitionLedger:
    """Typed, append-only adapter over the existing immutable result store."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = IntelligenceRepository(session)

    def append_decision_set(self, record: ForwardCompetitionDecisionSet) -> bool:
        return self._append(
            result_id=_identity("forward-competition", record.competition_id),
            result_type=FORWARD_COMPETITION_DECISION_TYPE,
            data_cutoff=record.tournament.information_cutoff,
            status="FORWARD_SHADOW_FROZEN",
            payload=record.model_dump(mode="json"),
        )

    def append_outcome(self, record: ForwardCompetitionOutcome) -> bool:
        decision = self.decision_set(record.competition_id)
        if decision is None:
            raise ValueError("forward competition outcome references unknown decision set")
        if record.decision_set_hash != decision.decision_set_hash:
            raise ValueError("forward competition outcome decision-set hash mismatch")
        frozen = next(
            (
                item
                for item in decision.tournament.variants
                if item.variant is record.outcome.variant
            ),
            None,
        )
        if frozen is None:
            raise ValueError("forward competition outcome variant was not frozen")
        if (
            record.outcome.decision_id != frozen.decision_id
            or record.outcome.outcome_time <= frozen.decision_time
            or record.outcome.evidence_class is not EvidenceClass.FORWARD_SHADOW
        ):
            raise ValueError("forward competition outcome fails immutable decision ordering")
        if record.outcome.outcome_time > datetime.now(UTC):
            raise ValueError("forward competition outcome cannot be in the future")
        return self._append(
            result_id=_identity(
                "forward-competition-outcome",
                record.competition_id,
                record.outcome.variant.value,
                record.evaluation_horizon,
            ),
            result_type=FORWARD_COMPETITION_OUTCOME_TYPE,
            data_cutoff=record.outcome.outcome_time,
            status="REALIZED_FORWARD_OUTCOME",
            payload=record.model_dump(mode="json"),
        )

    def decision_set(self, competition_id: str) -> ForwardCompetitionDecisionSet | None:
        row = self._row(
            FORWARD_COMPETITION_DECISION_TYPE,
            _identity("forward-competition", competition_id),
        )
        return (
            ForwardCompetitionDecisionSet.model_validate(dict(row.payload))
            if row is not None
            else None
        )

    def decision_sets(self) -> tuple[ForwardCompetitionDecisionSet, ...]:
        return tuple(
            ForwardCompetitionDecisionSet.model_validate(dict(row.payload))
            for row in self._rows(FORWARD_COMPETITION_DECISION_TYPE)
        )

    def outcomes(self) -> tuple[ForwardCompetitionOutcome, ...]:
        return tuple(
            ForwardCompetitionOutcome.model_validate(dict(row.payload))
            for row in self._rows(FORWARD_COMPETITION_OUTCOME_TYPE)
        )

    def _append(
        self,
        *,
        result_id: str,
        result_type: str,
        data_cutoff: datetime,
        status: str,
        payload: dict[str, object],
    ) -> bool:
        serialized = _hash(payload)
        existing = self._row(result_type, result_id)
        if existing is not None:
            if existing.result_hash != serialized:
                raise ValueError("forward competition result identity is immutable")
            return False
        self._repository.add_result(
            result_id=result_id,
            result_type=result_type,
            schema_version=FORWARD_COMPETITION_SCHEMA_VERSION,
            model_version=__version__,
            prompt_version="round79-forward-competition-v1",
            data_cutoff=data_cutoff,
            status=status,
            payload=payload,
        )
        self._session.flush()
        return True

    def _row(self, result_type: str, result_id: str) -> IntelligenceResearchResult | None:
        return self._session.scalar(
            select(IntelligenceResearchResult).where(
                IntelligenceResearchResult.result_type == result_type,
                IntelligenceResearchResult.result_id == result_id,
            )
        )

    def _rows(self, result_type: str) -> tuple[IntelligenceResearchResult, ...]:
        return tuple(
            self._session.scalars(
                select(IntelligenceResearchResult)
                .where(IntelligenceResearchResult.result_type == result_type)
                .order_by(
                    IntelligenceResearchResult.data_cutoff,
                    IntelligenceResearchResult.result_id,
                )
            )
        )


def append_daily_forward_competition(
    session: Session,
    *,
    workflow: TodayResult,
    hybrid_document: Mapping[str, object],
    evidence: AgenticShadowEvidence,
    run_id: str,
    decision_id: str,
    evidence_origin: str,
) -> dict[str, object]:
    """Freeze all policy decisions only for a genuine real-forward session."""

    if evidence_origin != "REAL_FORWARD":
        return {
            "decision_sets": 0,
            "variant_decisions": 0,
            "reason": "NON_REAL_FORWARD_EVIDENCE_ORIGIN",
        }
    if workflow.target is None or not workflow.target.target_weights:
        return {
            "decision_sets": 0,
            "variant_decisions": 0,
            "reason": "NO_VALID_PRODUCTION_TARGET",
        }
    mapping = {
        item.security.symbol: item.security.permanent_security_id
        for item in evidence.companies.values()
    }
    try:
        record = build_forward_competition_decision_set(
            workflow=workflow,
            hybrid_document=hybrid_document,
            run_id=run_id,
            decision_id=decision_id,
            symbol_to_security_id=mapping,
        )
    except (TypeError, ValueError):
        return {
            "decision_sets": 0,
            "variant_decisions": 0,
            "reason": "FORWARD_COMPETITION_FREEZE_INVALID",
        }
    added = ForwardCompetitionLedger(session).append_decision_set(record)
    return {
        "decision_sets": int(added),
        "variant_decisions": len(PortfolioVariant) if added else 0,
        "competition_id": record.competition_id,
        "decision_set_hash": record.decision_set_hash,
        "reason": "FROZEN" if added else "IDEMPOTENT_REUSE",
    }


def build_forward_competition_decision_set(
    *,
    workflow: TodayResult,
    hybrid_document: Mapping[str, object],
    run_id: str,
    decision_id: str,
    symbol_to_security_id: Mapping[str, str],
) -> ForwardCompetitionDecisionSet:
    """Create five aligned DecisionFreeze records without changing a target."""

    if workflow.target is None:
        raise ValueError("a valid production target is required")
    decision_time = _aware(workflow.decision_time, "decision_time")
    information_cutoff = _aware(
        workflow.data_cutoff or workflow.decision_time, "information_cutoff"
    )
    production_weights = _weight_document(workflow.target.target_weights)
    quant_weights, quant_available = _probability_weights(
        workflow.probability_counterfactual,
        "target_without_probability",
        fallback=production_weights,
    )
    probability_weights, probability_available = _probability_weights(
        workflow.probability_counterfactual,
        "target_with_probability",
        fallback=quant_weights,
    )
    llm_weights, llm_available = _llm_weights(hybrid_document, fallback=quant_weights)
    # No daily path computes a separately governed Probability+LLM or
    # Adaptive Exposure target. Recording the Quant fallback as degraded is
    # deliberately not a substitute for that unavailable counterfactual.
    combined_weights = quant_weights
    full_weights = quant_weights
    symbols = tuple(
        sorted(
            set(workflow.current_weights or {})
            | set(production_weights)
            | set(quant_weights)
            | set(probability_weights)
            | set(llm_weights)
        )
    )
    if not symbols:
        raise ValueError("forward competition requires a non-empty frozen target universe")
    if set(symbols) - set(symbol_to_security_id):
        raise ValueError("every frozen target symbol requires a permanent security identity")
    statuses: dict[PortfolioVariant, Literal["SHADOW", "DEGRADED_FALLBACK"]] = {
        PortfolioVariant.PURE_QUANT: "SHADOW",
        PortfolioVariant.QUANT_PLUS_PROBABILITY: (
            "SHADOW"
            if quant_available and probability_available
            else "DEGRADED_FALLBACK"
        ),
        PortfolioVariant.QUANT_PLUS_LLM: (
            "SHADOW"
            if llm_available
            else "DEGRADED_FALLBACK"
        ),
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM: "DEGRADED_FALLBACK",
        PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE: "DEGRADED_FALLBACK",
    }
    reasons: dict[PortfolioVariant, tuple[str, ...]] = {
        PortfolioVariant.PURE_QUANT: ("PRODUCTION_QUANT_COUNTERFACTUAL",),
        PortfolioVariant.QUANT_PLUS_PROBABILITY: (
            ("PROBABILITY_COUNTERFACTUAL_TARGET_UNAVAILABLE",)
            if statuses[PortfolioVariant.QUANT_PLUS_PROBABILITY]
            == ForwardVariantState.DEGRADED_FALLBACK
            else ("PROBABILITY_SHADOW_TARGET_FROZEN",)
        ),
        PortfolioVariant.QUANT_PLUS_LLM: (
            ("LLM_FAIL_SOFT_QUANT_FALLBACK",)
            if statuses[PortfolioVariant.QUANT_PLUS_LLM] == ForwardVariantState.DEGRADED_FALLBACK
            else ("LLM_SHADOW_TARGET_FROZEN",)
        ),
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM: (
            "COMBINED_COUNTERFACTUAL_NOT_SEPARATELY_COMPUTED",
        ),
        PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE: (
            "ADAPTIVE_EXPOSURE_SHADOW_TARGET_UNAVAILABLE",
        ),
    }
    weights_by_variant = {
        PortfolioVariant.PURE_QUANT: quant_weights,
        PortfolioVariant.QUANT_PLUS_PROBABILITY: probability_weights,
        PortfolioVariant.QUANT_PLUS_LLM: llm_weights,
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM: combined_weights,
        PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE: full_weights,
    }
    risk = _mapping(workflow.risk)
    shadow_pipeline = _mapping(hybrid_document.get("shadow_pipeline"))
    freezes = tuple(
        DecisionFreeze(
            decision_id=decision_id,
            decision_time=decision_time,
            information_cutoff=information_cutoff,
            variant=variant,
            universe_identity=workflow.universe_snapshot_id,
            symbols=symbols,
            target_weights=weights_by_variant[variant],
            target_exposure=sum(weights_by_variant[variant].values()),
            benchmark=workflow.benchmark_symbol,
            execution_assumptions_hash=_hash(
                {"manual_confirmation": True, "config_hash": workflow.config_hash}
            ),
            transaction_cost_model=workflow.config_hash,
            accounting_rules="FORWARD_SHADOW_MANUAL_EXECUTION_ACCOUNTING_V1",
            input_hash=_hash(
                {
                    "run_id": run_id,
                    "data_hash": workflow.data_hash,
                    "model_hash": workflow.model_hash,
                    "universe": workflow.universe_snapshot_id,
                }
            ),
            raw_model_output_hash=_hash(
                {
                    "variant": variant.value,
                    "targets": weights_by_variant[variant],
                    "state": statuses[variant],
                }
            ),
            portfolio_recommendation_hash=_hash(weights_by_variant[variant]),
            risk_adjustments_hash=_hash(
                risk if variant is PortfolioVariant.PURE_QUANT else shadow_pipeline
            ),
            model_versions={
                "production_quant": workflow.model_hash,
                variant.value: workflow.strategy_version,
            },
            config_hashes={"runtime": workflow.config_hash},
            reason_codes=reasons[variant],
            evidence_class=EvidenceClass.FORWARD_SHADOW,
            frozen_at=decision_time,
        )
        for variant in PortfolioVariant
    )
    tournament = build_tournament(*freezes)
    permanent_ids = tuple(sorted({symbol_to_security_id[symbol] for symbol in symbols}))
    current_weights = {
        symbol_to_security_id[symbol]: float(weight)
        for symbol, weight in (workflow.current_weights or {}).items()
        if symbol in symbol_to_security_id
    }
    competition_id = _identity(
        "forward-competition",
        decision_id,
        workflow.universe_snapshot_id,
        decision_time.isoformat(),
    )
    return ForwardCompetitionDecisionSet(
        competition_id=competition_id,
        tournament=tournament,
        permanent_security_ids=permanent_ids,
        symbol_to_security_id={symbol: symbol_to_security_id[symbol] for symbol in symbols},
        current_weights=current_weights,
        universe_hash=_hash(
            {
                "universe_identity": workflow.universe_snapshot_id,
                "universe_count": workflow.universe_count,
                "data_hash": workflow.data_hash,
            }
        ),
        data_hash=workflow.data_hash,
        variant_states=statuses,
        variant_reason_codes=reasons,
        evidence_origin="REAL_FORWARD",
        created_at=decision_time,
    )


def competition_dashboard(ledger: ForwardCompetitionLedger) -> dict[str, object]:
    decisions = ledger.decision_sets()
    outcomes = ledger.outcomes()
    expected = len(decisions) * len(PortfolioVariant) * len(SUPPORTED_EVALUATION_HORIZONS)
    by_set: dict[tuple[str, str], set[PortfolioVariant]] = {}
    for row in outcomes:
        by_set.setdefault((row.competition_id, row.evaluation_horizon), set()).add(
            row.outcome.variant
        )
    paired_sets = [
        key for key, variants in by_set.items() if variants == set(PortfolioVariant)
    ]
    decision_by_id = {row.competition_id: row for row in decisions}
    session_by_id = {
        row.competition_id: row.tournament.decision_time.date().isoformat()
        for row in decisions
    }
    promotable_paired_sets = [
        key
        for key in paired_sets
        if all(
            state == ForwardVariantState.SHADOW
            for state in decision_by_id[key[0]].variant_states.values()
        )
    ]
    nonfallback = sum(
        1
        for decision in decisions
        for state in decision.variant_states.values()
        if state == ForwardVariantState.SHADOW
    )
    return {
        "decision_sets": len(decisions),
        "frozen_variant_decisions": len(decisions) * len(PortfolioVariant),
        "realized_variant_outcomes": len(outcomes),
        "pending_variant_outcomes": max(0, expected - len(outcomes)),
        "complete_paired_sets": len(paired_sets),
        "independent_sessions": len({session_by_id[key[0]] for key in paired_sets}),
        "promotion_eligible_paired_sets": len(promotable_paired_sets),
        "promotion_eligible_independent_sessions": len(
            {session_by_id[key[0]] for key in promotable_paired_sets}
        ),
        "shadow_variant_decisions": nonfallback,
        "degraded_fallback_variant_decisions": len(decisions) * len(PortfolioVariant) - nonfallback,
        "promotion_eligible": False,
    }


def _probability_weights(
    traces: Mapping[str, Mapping[str, object]],
    field: str,
    *,
    fallback: Mapping[str, float],
) -> tuple[dict[str, float], bool]:
    values: dict[str, float] = {}
    relevant = set(fallback)
    for symbol, trace in traces.items():
        value = trace.get(field)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            if abs(float(value)) > 1e-12:
                relevant.add(symbol)
    for symbol in relevant:
        trace = traces.get(symbol, {})
        value = trace.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return _weight_document(fallback), False
        values[symbol] = float(value)
    return (values, True) if _long_only(values) else (_weight_document(fallback), False)


def _llm_weights(
    hybrid_document: Mapping[str, object],
    *,
    fallback: Mapping[str, float],
) -> tuple[dict[str, float], bool]:
    actions = hybrid_document.get("actions")
    rows = actions if isinstance(actions, list) else []
    values = {
        str(row.get("symbol")): float(row["hybrid_target"])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("symbol"), str)
        and isinstance(row.get("hybrid_target"), (int, float))
        and math.isfinite(float(row["hybrid_target"]))
    }
    relevant = set(fallback) | set(values)
    if not relevant or any(symbol not in values for symbol in relevant) or not _long_only(values):
        return _weight_document(fallback), False
    return values, True


def _long_only(weights: Mapping[str, float]) -> bool:
    return (
        bool(weights)
        and all(value >= 0 for value in weights.values())
        and sum(weights.values()) <= 1 + 1e-9
    )


def _weight_document(weights: Mapping[str, float]) -> dict[str, float]:
    values: dict[str, float] = {}
    for symbol, raw_weight in weights.items():
        if not isinstance(raw_weight, (int, float)) or not math.isfinite(float(raw_weight)):
            raise ValueError("frozen target weights must be finite")
        value = float(raw_weight)
        if value < 0:
            raise ValueError("frozen target weights must be long-only")
        if abs(value) > 1e-12:
            values[str(symbol)] = value
    if sum(values.values()) > 1 + 1e-9:
        raise ValueError("frozen target weights exceed long-only gross exposure")
    return values


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _identity(prefix: str, *parts: str) -> str:
    return sha256("|".join((prefix, *parts)).encode("utf-8")).hexdigest()
