"""ROUND78 controlled intelligence-promotion tournament.

This module is a governance layer over the ROUND71 synchronized portfolio
competition ledger.  It does not change the production quant, optimizer, risk,
execution, or data-refresh paths.  It only evaluates explicitly frozen,
paired evidence and fails closed when the certified data/OOS prerequisites are
absent.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_alpha_terminal.research.portfolio_competition import (
    DecisionFreeze,
    PortfolioVariant,
    TournamentDecision,
    build_tournament,
)


class TournamentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LLMInfluenceLevel(StrEnum):
    L0_COMMENTARY = "L0_COMMENTARY"
    L1_SHADOW_SCORING = "L1_SHADOW_SCORING"
    L2_RANKING = "L2_RANKING"
    L3_BOUNDED_FORMAL = "L3_BOUNDED_FORMAL"
    L4_ADAPTIVE_EVIDENCE = "L4_ADAPTIVE_EVIDENCE"


class TournamentEvidenceClass(StrEnum):
    CERTIFIED_LOCKED_OOS = "CERTIFIED_LOCKED_OOS"
    FORWARD_SHADOW = "FORWARD_SHADOW"
    ENGINEERING_ONLY = "ENGINEERING_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class TournamentVerdict(StrEnum):
    PROMOTE = "PROMOTE"
    RETAIN_SHADOW = "RETAIN_SHADOW"
    RETAIN_QUANT_CHAMPION = "RETAIN_QUANT_CHAMPION"
    DEMOTE_TO_SHADOW = "DEMOTE_TO_SHADOW"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"


class EvidenceDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    FAIL_SOFT = "FAIL_SOFT"


class EvidenceProvenance(TournamentModel):
    """Decision-time provenance for structured LLM research evidence."""

    evidence_id: str
    source: str
    observed_at: datetime
    available_at: datetime
    freshness_seconds: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    content_hash: str

    @field_validator("evidence_id", "source", "content_hash")
    @classmethod
    def required_text(cls, value: str, info: Any) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{info.field_name} cannot be empty")
        return normalized

    @field_validator("observed_at", "available_at")
    @classmethod
    def aware_timestamp(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_order(self) -> EvidenceProvenance:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self


class LLMResearchEvidence(TournamentModel):
    """Structured market/company/portfolio reasoning with auditable lineage."""

    market: dict[str, str] = {}
    company: dict[str, str] = {}
    portfolio: dict[str, str] = {}
    provenance: tuple[EvidenceProvenance, ...] = ()
    conflicts: tuple[str, ...] = ()


class LLMEvidenceAssessment(TournamentModel):
    disposition: EvidenceDisposition
    usable: bool
    accepted_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    quant_fallback: bool = True


def assess_llm_evidence(
    evidence: LLMResearchEvidence | Mapping[str, object] | None,
    *,
    information_cutoff: datetime,
    max_age_seconds: int = 86_400,
) -> LLMEvidenceAssessment:
    """Validate LLM evidence and fail soft to the deterministic Quant path."""

    if information_cutoff.tzinfo is None or information_cutoff.utcoffset() is None:
        raise ValueError("information_cutoff must be timezone-aware")
    cutoff = information_cutoff.astimezone(UTC)
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    if evidence is None:
        return LLMEvidenceAssessment(
            disposition=EvidenceDisposition.FAIL_SOFT,
            usable=False,
            reason_codes=("NO_LLM_EVIDENCE",),
        )
    try:
        parsed = (
            evidence
            if isinstance(evidence, LLMResearchEvidence)
            else LLMResearchEvidence.model_validate(evidence)
        )
    except Exception:  # noqa: BLE001 - malformed external evidence must fail soft
        return LLMEvidenceAssessment(
            disposition=EvidenceDisposition.FAIL_SOFT,
            usable=False,
            reason_codes=("LLM_MALFORMED_EVIDENCE",),
        )
    reasons: list[str] = []
    ids: list[str] = []
    if parsed.conflicts:
        reasons.append("LLM_CONFLICTING_EVIDENCE")
    for item in parsed.provenance:
        if item.evidence_id in ids:
            reasons.append("LLM_DUPLICATE_EVIDENCE_ID")
        ids.append(item.evidence_id)
        if item.available_at > cutoff:
            reasons.append("LLM_FUTURE_EVIDENCE")
        age = (cutoff - item.available_at).total_seconds()
        if age > max_age_seconds or age > item.freshness_seconds:
            reasons.append("LLM_STALE_EVIDENCE")
    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons or not ids:
        return LLMEvidenceAssessment(
            disposition=EvidenceDisposition.FAIL_SOFT,
            usable=False,
            accepted_evidence_ids=(),
            reason_codes=unique_reasons or ("NO_LLM_PROVENANCE",),
        )
    return LLMEvidenceAssessment(
        disposition=EvidenceDisposition.ACCEPTED,
        usable=True,
        accepted_evidence_ids=tuple(ids),
        reason_codes=("LLM_EVIDENCE_ACCEPTED",),
        quant_fallback=False,
    )


class SynchronizedMetricSet(TournamentModel):
    """After-cost paired metrics for one policy on the shared sample."""

    sample_count: int = Field(ge=0)
    unique_sessions: int = Field(ge=0)
    after_cost_return: float | None = None
    spy_excess_return: float | None = None
    qqq_excess_return: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    volatility: float | None = None
    upside_capture: float | None = None
    downside_capture: float | None = None
    beta: float | None = None
    tracking_error: float | None = None
    turnover: float | None = None
    cost: float | None = None
    concentration: float | None = None
    average_exposure: float | None = None
    recovery_participation: float | None = None
    regime_stable: bool | None = None
    paired_return_ci: tuple[float, float] | None = None

    @field_validator(
        "after_cost_return",
        "spy_excess_return",
        "qqq_excess_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "volatility",
        "upside_capture",
        "downside_capture",
        "beta",
        "tracking_error",
        "turnover",
        "cost",
        "concentration",
        "average_exposure",
        "recovery_participation",
    )
    @classmethod
    def finite_metric(cls, value: float | None, info: Any) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> SynchronizedMetricSet:
        if self.paired_return_ci is not None:
            low, high = self.paired_return_ci
            if not math.isfinite(low) or not math.isfinite(high) or low > high:
                raise ValueError("paired_return_ci is invalid")
        if self.sample_count == 0 and any(
            value is not None
            for value in (
                self.after_cost_return,
                self.spy_excess_return,
                self.qqq_excess_return,
                self.sharpe,
                self.sortino,
            )
        ):
            raise ValueError("metrics cannot be populated when sample_count is zero")
        return self


class VariantMeasurement(TournamentModel):
    policy: PortfolioVariant
    evidence_class: TournamentEvidenceClass
    metrics: SynchronizedMetricSet
    reason_codes: tuple[str, ...] = ()


class AlphaEngine3Measurement(TournamentModel):
    """Separate fixed-selection challenger measurement for Alpha Engine 3."""

    evidence_class: TournamentEvidenceClass
    metrics: SynchronizedMetricSet
    reason_codes: tuple[str, ...] = ()


class TournamentEvidenceState(TournamentModel):
    data_certification_status: str
    locked_oos_status: str
    locked_oos_manifest_hash: str | None = None
    certified_replay: bool = False
    minimum_complete_samples: int = Field(default=120, ge=1)
    minimum_unique_sessions: int = Field(default=40, ge=1)
    probability_forward_samples: int = Field(default=0, ge=0)
    llm_forward_samples: int = Field(default=0, ge=0)
    adaptive_exposure_validated: bool = False
    risk_constraints_authoritative: bool = True
    manual_confirmation_enabled: bool = True
    auto_execution_disabled: bool = True
    explicit_blockers: tuple[str, ...] = ()

    @property
    def data_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.data_certification_status != "PASS":
            blockers.append("CERTIFIED_DATA_FOUNDATION_REQUIRED")
        if self.locked_oos_status != "PASS":
            blockers.append("LOCKED_OOS_PROTOCOL_REQUIRED")
        if not self.locked_oos_manifest_hash:
            blockers.append("LOCKED_OOS_MANIFEST_MISSING")
        if not self.certified_replay:
            blockers.append("CERTIFIED_REPLAY_REQUIRED")
        return tuple(dict.fromkeys((*blockers, *self.explicit_blockers)))

    @property
    def evidence_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.probability_forward_samples < self.minimum_unique_sessions:
            blockers.append("PROBABILITY_FORWARD_EVIDENCE_INSUFFICIENT")
        if self.llm_forward_samples < self.minimum_unique_sessions:
            blockers.append("LLM_FORWARD_EVIDENCE_INSUFFICIENT")
        if not self.adaptive_exposure_validated:
            blockers.append("ADAPTIVE_EXPOSURE_EVIDENCE_INSUFFICIENT")
        return tuple(blockers)

    @property
    def safety_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.risk_constraints_authoritative:
            blockers.append("HARD_RISK_CONSTRAINTS_REQUIRED")
        if not self.manual_confirmation_enabled:
            blockers.append("MANUAL_CONFIRMATION_REQUIRED")
        if not self.auto_execution_disabled:
            blockers.append("AUTO_EXECUTION_MUST_REMAIN_DISABLED")
        return tuple(blockers)


class VariantTournamentResult(TournamentModel):
    policy: PortfolioVariant
    sample_count: int
    return_delta: float | None = None
    excess_return_delta: float | None = None
    sharpe_delta: float | None = None
    max_drawdown_delta: float | None = None
    upside_capture_delta: float | None = None
    downside_capture_delta: float | None = None
    turnover_delta: float | None = None
    cost_delta: float | None = None
    exposure_delta: float | None = None
    recovery_participation_delta: float | None = None
    confidence_interval: tuple[float, float] | None = None
    verdict: TournamentVerdict
    reason_codes: tuple[str, ...]


class AlphaEngine3Attribution(TournamentModel):
    sample_count: int = Field(ge=0)
    evidence_class: TournamentEvidenceClass
    selection_return_delta: float | None = None
    selection_excess_return_delta: float | None = None
    sharpe_delta: float | None = None
    turnover_delta: float | None = None
    cost_delta: float | None = None
    confidence_interval: tuple[float, float] | None = None
    verdict: TournamentVerdict
    reason_codes: tuple[str, ...]


class ControlledTournamentEvaluation(TournamentModel):
    protocol: str = "ROUND78-CONTROLLED-INTELLIGENCE-TOURNAMENT-v1"
    evaluated_at: datetime
    tournament_hash: str | None
    production_policy: PortfolioVariant = PortfolioVariant.PURE_QUANT
    alpha_engine3: TournamentVerdict = TournamentVerdict.RETAIN_SHADOW
    alpha_engine3_attribution: AlphaEngine3Attribution
    probability: TournamentVerdict = TournamentVerdict.RETAIN_SHADOW
    llm_level: LLMInfluenceLevel = LLMInfluenceLevel.L1_SHADOW_SCORING
    llm_formal_influence: float = Field(ge=0, le=1)
    probability_formal_influence: float = Field(ge=0, le=1)
    adaptive_exposure: TournamentVerdict = TournamentVerdict.RETAIN_SHADOW
    strongest_challenger: PortfolioVariant | None = None
    variant_results: tuple[VariantTournamentResult, ...]
    blockers: tuple[str, ...] = ()
    synchronized: bool = True
    economic_claims_allowed: bool = False

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def enforce_production_boundary(self) -> ControlledTournamentEvaluation:
        if (
            self.production_policy is not PortfolioVariant.PURE_QUANT
            and not self.economic_claims_allowed
        ):
            raise ValueError("production quant remains champion until promotion evidence passes")
        if not self.economic_claims_allowed and (
            self.llm_formal_influence != 0 or self.probability_formal_influence != 0
        ):
            raise ValueError("formal LLM/Probability influence must remain zero while blocked")
        return self

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.model_dump_json()))


REQUIRED_POLICIES = frozenset(PortfolioVariant)
LLM_POLICIES = frozenset(
    {
        PortfolioVariant.QUANT_PLUS_LLM,
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM,
        PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE,
    }
)
PROBABILITY_POLICIES = frozenset(
    {
        PortfolioVariant.QUANT_PLUS_PROBABILITY,
        PortfolioVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM,
    }
)


def build_controlled_tournament(*freezes: DecisionFreeze) -> TournamentDecision:
    """Build exactly one synchronized freeze for each ROUND78 policy."""

    policies = {item.variant for item in freezes}
    if len(freezes) != len(REQUIRED_POLICIES) or policies != REQUIRED_POLICIES:
        raise ValueError("ROUND78 requires exactly the five synchronized policy variants")
    return build_tournament(*freezes)


def evaluate_controlled_tournament(
    tournament: TournamentDecision | None,
    *,
    evidence: TournamentEvidenceState,
    measurements: Mapping[PortfolioVariant, VariantMeasurement] | None = None,
    evaluated_at: datetime | None = None,
    requested_llm_level: LLMInfluenceLevel = LLMInfluenceLevel.L1_SHADOW_SCORING,
    requested_llm_influence: float = 0.0,
    requested_probability_influence: float = 0.0,
    active_challenger: PortfolioVariant | None = None,
    alpha_engine3_measurement: AlphaEngine3Measurement | None = None,
    allow_production_promotion: bool = False,
    llm_evidence: LLMResearchEvidence | Mapping[str, object] | None = None,
) -> ControlledTournamentEvaluation:
    """Evaluate a frozen tournament without changing production by default."""

    when = (evaluated_at or datetime.now(UTC)).astimezone(UTC)
    if requested_llm_influence < 0 or requested_llm_influence > 1:
        raise ValueError("requested_llm_influence must be in [0, 1]")
    if requested_probability_influence < 0 or requested_probability_influence > 1:
        raise ValueError("requested_probability_influence must be in [0, 1]")
    rows = dict(measurements or {})
    unknown = set(rows) - REQUIRED_POLICIES
    if unknown:
        raise ValueError(
            f"unknown ROUND78 policy variants: {sorted(item.value for item in unknown)}"
        )
    if any(row.policy is not policy for policy, row in rows.items()):
        raise ValueError("measurement policy identity mismatch")
    blockers = list(evidence.data_blockers)
    if not blockers:
        blockers.extend(evidence.evidence_blockers)
    blockers.extend(evidence.safety_blockers)
    llm_assessment = assess_llm_evidence(
        llm_evidence,
        information_cutoff=(
            tournament.information_cutoff
            if tournament is not None
            else when
        ),
    )
    if not llm_assessment.usable:
        blockers.extend(
            reason
            for reason in llm_assessment.reason_codes
            if reason not in {"NO_LLM_EVIDENCE", "NO_LLM_PROVENANCE"}
        )
    baseline = rows.get(PortfolioVariant.PURE_QUANT)
    all_certified = all(
        item.evidence_class is TournamentEvidenceClass.CERTIFIED_LOCKED_OOS
        for item in rows.values()
    ) and len(rows) == len(REQUIRED_POLICIES)
    if rows and not all_certified:
        blockers.append("CERTIFIED_LOCKED_OOS_EVIDENCE_REQUIRED")
    if baseline is None:
        blockers.append("PURE_QUANT_BASELINE_REQUIRED")
    unique_blockers = tuple(dict.fromkeys(blockers))
    hard_data_blocked = bool(evidence.data_blockers)
    if hard_data_blocked:
        overall_verdict = TournamentVerdict.BLOCKED_DATA_QUALITY
    elif unique_blockers:
        overall_verdict = TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
    else:
        overall_verdict = None
    results: list[VariantTournamentResult] = []
    strongest: tuple[PortfolioVariant, float] | None = None
    if baseline is None:
        results.append(
            VariantTournamentResult(
                policy=PortfolioVariant.PURE_QUANT,
                sample_count=0,
                verdict=overall_verdict or TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE,
                reason_codes=("PURE_QUANT_BASELINE_REQUIRED",),
            )
        )
    else:
        results.append(
            VariantTournamentResult(
                policy=PortfolioVariant.PURE_QUANT,
                sample_count=baseline.metrics.sample_count,
                return_delta=0.0,
                excess_return_delta=0.0,
                sharpe_delta=0.0,
                max_drawdown_delta=0.0,
                upside_capture_delta=0.0,
                downside_capture_delta=0.0,
                turnover_delta=0.0,
                cost_delta=0.0,
                exposure_delta=0.0,
                recovery_participation_delta=0.0,
                confidence_interval=baseline.metrics.paired_return_ci,
                verdict=(
                    overall_verdict
                    if overall_verdict is not None
                    else TournamentVerdict.RETAIN_QUANT_CHAMPION
                ),
                reason_codes=(
                    tuple(unique_blockers)
                    if unique_blockers
                    else ("PRODUCTION_QUANT_CHAMPION",)
                ),
            )
        )
    for policy in PortfolioVariant:
        if policy is PortfolioVariant.PURE_QUANT:
            continue
        measurement = rows.get(policy)
        if measurement is None or baseline is None:
            result = VariantTournamentResult(
                policy=policy,
                sample_count=measurement.metrics.sample_count if measurement else 0,
                verdict=overall_verdict or TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE,
                reason_codes=("MISSING_PAIRED_MEASUREMENT",),
            )
            results.append(result)
            continue
        deltas = _deltas(measurement.metrics, baseline.metrics)
        reasons = list(unique_blockers)
        if measurement.metrics.sample_count < evidence.minimum_complete_samples:
            reasons.append("INSUFFICIENT_COMPLETE_SAMPLES")
        if measurement.metrics.unique_sessions < evidence.minimum_unique_sessions:
            reasons.append("INSUFFICIENT_UNIQUE_SESSIONS")
        reasons.extend(_component_blockers(policy, deltas, measurement.metrics))
        if policy in LLM_POLICIES and not llm_assessment.usable:
            reasons.append("LLM_FAIL_SOFT_QUANT_FALLBACK")
        if reasons:
            verdict = (
                TournamentVerdict.BLOCKED_DATA_QUALITY
                if hard_data_blocked
                else (
                    TournamentVerdict.DEMOTE_TO_SHADOW
                    if active_challenger is policy
                    else TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
                )
            )
        else:
            verdict = (
                TournamentVerdict.PROMOTE
                if allow_production_promotion
                else TournamentVerdict.RETAIN_QUANT_CHAMPION
            )
        score = deltas["return_delta"]
        if score is not None and (strongest is None or score > strongest[1]):
            strongest = (policy, score)
        results.append(
            VariantTournamentResult(
                policy=policy,
                sample_count=measurement.metrics.sample_count,
                return_delta=deltas["return_delta"],
                excess_return_delta=deltas["excess_return_delta"],
                sharpe_delta=deltas["sharpe_delta"],
                max_drawdown_delta=deltas["max_drawdown_delta"],
                upside_capture_delta=deltas["upside_capture_delta"],
                downside_capture_delta=deltas["downside_capture_delta"],
                turnover_delta=deltas["turnover_delta"],
                cost_delta=deltas["cost_delta"],
                exposure_delta=deltas["exposure_delta"],
                recovery_participation_delta=deltas["recovery_participation_delta"],
                confidence_interval=measurement.metrics.paired_return_ci,
                verdict=verdict,
                reason_codes=tuple(dict.fromkeys(reasons)) or ("PROMOTION_GATES_PASS",),
            )
        )
    selected = next((item for item in results if item.verdict is TournamentVerdict.PROMOTE), None)
    production = selected.policy if selected is not None else PortfolioVariant.PURE_QUANT
    economic_allowed = selected is not None and allow_production_promotion and not unique_blockers
    selected_uses_llm = selected is not None and selected.policy in LLM_POLICIES
    selected_uses_probability = (
        selected is not None and selected.policy in PROBABILITY_POLICIES
    )
    llm_influence = (
        requested_llm_influence
        if (
            economic_allowed
            and selected_uses_llm
            and requested_llm_level
            in {LLMInfluenceLevel.L3_BOUNDED_FORMAL, LLMInfluenceLevel.L4_ADAPTIVE_EVIDENCE}
        )
        else 0.0
    )
    probability_influence = (
        requested_probability_influence
        if economic_allowed and selected_uses_probability
        else 0.0
    )
    if not economic_allowed:
        production = PortfolioVariant.PURE_QUANT
    alpha_engine3_attribution = _alpha_engine3_attribution(
        alpha_engine3_measurement,
        baseline.metrics if baseline is not None else None,
        evidence=evidence,
        global_blockers=unique_blockers,
        allow_promotion=allow_production_promotion,
    )
    return ControlledTournamentEvaluation(
        evaluated_at=when,
        tournament_hash=tournament.tournament_hash if tournament else None,
        production_policy=production,
        alpha_engine3=(
            TournamentVerdict.PROMOTE
            if alpha_engine3_attribution.verdict is TournamentVerdict.PROMOTE
            else TournamentVerdict.RETAIN_SHADOW
        ),
        alpha_engine3_attribution=alpha_engine3_attribution,
        probability=(
            TournamentVerdict.PROMOTE
            if probability_influence > 0
            else TournamentVerdict.RETAIN_SHADOW
        ),
        llm_level=(
            requested_llm_level
            if economic_allowed and selected_uses_llm
            else LLMInfluenceLevel.L1_SHADOW_SCORING
        ),
        llm_formal_influence=llm_influence,
        probability_formal_influence=probability_influence,
        adaptive_exposure=(
            TournamentVerdict.PROMOTE
            if (
                selected is not None
                and selected.policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE
                and economic_allowed
            )
            else TournamentVerdict.RETAIN_SHADOW
        ),
        strongest_challenger=strongest[0] if strongest else None,
        variant_results=tuple(results),
        blockers=unique_blockers,
        synchronized=tournament is None or _synchronized(tournament),
        economic_claims_allowed=economic_allowed,
    )


def current_tournament_status(
    *,
    data_certification_status: str,
    locked_oos_status: str,
    locked_oos_manifest_hash: str | None = None,
    evaluated_at: datetime | None = None,
) -> ControlledTournamentEvaluation:
    """Render current repository status without making a remote call."""

    evidence = TournamentEvidenceState(
        data_certification_status=data_certification_status,
        locked_oos_status=locked_oos_status,
        locked_oos_manifest_hash=locked_oos_manifest_hash,
    )
    return evaluate_controlled_tournament(None, evidence=evidence, evaluated_at=evaluated_at)


def _synchronized(tournament: TournamentDecision) -> bool:
    return (
        len(tournament.variants) == len(REQUIRED_POLICIES)
        and {item.variant for item in tournament.variants} == REQUIRED_POLICIES
        and len({item.decision_time for item in tournament.variants}) == 1
        and len({item.information_cutoff for item in tournament.variants}) == 1
        and len({item.universe_identity for item in tournament.variants}) == 1
        and len({item.benchmark for item in tournament.variants}) == 1
        and len({item.execution_assumptions_hash for item in tournament.variants}) == 1
        and len({item.transaction_cost_model for item in tournament.variants}) == 1
        and len({item.accounting_rules for item in tournament.variants}) == 1
    )


def _deltas(
    candidate: SynchronizedMetricSet,
    baseline: SynchronizedMetricSet,
) -> dict[str, float | None]:
    names = {
        "return_delta": "after_cost_return",
        "excess_return_delta": "spy_excess_return",
        "sharpe_delta": "sharpe",
        "max_drawdown_delta": "max_drawdown",
        "upside_capture_delta": "upside_capture",
        "downside_capture_delta": "downside_capture",
        "turnover_delta": "turnover",
        "cost_delta": "cost",
        "exposure_delta": "average_exposure",
        "recovery_participation_delta": "recovery_participation",
    }
    return {
        target: _delta(getattr(candidate, field), getattr(baseline, field))
        for target, field in names.items()
    }


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _component_blockers(
    policy: PortfolioVariant,
    deltas: Mapping[str, float | None],
    metrics: SynchronizedMetricSet,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if deltas["return_delta"] is None or deltas["return_delta"] < 0:
        reasons.append("AFTER_COST_RETURN_NOT_INCREMENTAL")
    if deltas["excess_return_delta"] is None or deltas["excess_return_delta"] < 0:
        reasons.append("BENCHMARK_EXCESS_NOT_INCREMENTAL")
    if deltas["max_drawdown_delta"] is not None and deltas["max_drawdown_delta"] > 0.02:
        reasons.append("MAX_DRAWDOWN_REGRESSION")
    if deltas["turnover_delta"] is not None and deltas["turnover_delta"] > 0.05:
        reasons.append("TURNOVER_REGRESSION")
    if deltas["cost_delta"] is not None and deltas["cost_delta"] > 0.005:
        reasons.append("COST_REGRESSION")
    if metrics.regime_stable is not True:
        reasons.append("REGIME_STABILITY_NOT_ESTABLISHED")
    if metrics.paired_return_ci is None:
        reasons.append("PAIRED_CONFIDENCE_INTERVAL_REQUIRED")
    elif metrics.paired_return_ci[0] < 0:
        reasons.append("PAIRED_CONFIDENCE_INTERVAL_CROSSES_ZERO")
    if policy is PortfolioVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE:
        upside_delta = deltas["upside_capture_delta"]
        downside_delta = deltas["downside_capture_delta"]
        recovery_delta = deltas["recovery_participation_delta"]
        if upside_delta is None or upside_delta < 0:
            reasons.append("BULL_PARTICIPATION_NOT_INCREMENTAL")
        if downside_delta is None or downside_delta > 0.05:
            reasons.append("DOWNSIDE_CAPTURE_REGRESSION")
        if recovery_delta is None or recovery_delta < 0:
            reasons.append("RECOVERY_PARTICIPATION_NOT_INCREMENTAL")
    return tuple(reasons)


def _alpha_engine3_attribution(
    measurement: AlphaEngine3Measurement | None,
    baseline: SynchronizedMetricSet | None,
    *,
    evidence: TournamentEvidenceState,
    global_blockers: tuple[str, ...],
    allow_promotion: bool,
) -> AlphaEngine3Attribution:
    if measurement is None or baseline is None:
        return AlphaEngine3Attribution(
            sample_count=0,
            evidence_class=TournamentEvidenceClass.UNAVAILABLE,
            verdict=(
                TournamentVerdict.BLOCKED_DATA_QUALITY
                if evidence.data_blockers
                else TournamentVerdict.BLOCKED_INSUFFICIENT_EVIDENCE
            ),
            reason_codes=("ALPHA_ENGINE3_PAIRED_MEASUREMENT_REQUIRED",),
        )
    deltas = _deltas(measurement.metrics, baseline)
    reasons = list(global_blockers)
    if measurement.evidence_class is not TournamentEvidenceClass.CERTIFIED_LOCKED_OOS:
        reasons.append("ALPHA_ENGINE3_CERTIFIED_LOCKED_OOS_REQUIRED")
    if measurement.metrics.sample_count < evidence.minimum_complete_samples:
        reasons.append("ALPHA_ENGINE3_INSUFFICIENT_COMPLETE_SAMPLES")
    if measurement.metrics.unique_sessions < evidence.minimum_unique_sessions:
        reasons.append("ALPHA_ENGINE3_INSUFFICIENT_UNIQUE_SESSIONS")
    reasons.extend(
        _component_blockers(
            PortfolioVariant.QUANT_PLUS_LLM,
            deltas,
            measurement.metrics,
        )
    )
    unique_reasons = tuple(dict.fromkeys(reasons))
    return AlphaEngine3Attribution(
        sample_count=measurement.metrics.sample_count,
        evidence_class=measurement.evidence_class,
        selection_return_delta=deltas["return_delta"],
        selection_excess_return_delta=deltas["excess_return_delta"],
        sharpe_delta=deltas["sharpe_delta"],
        turnover_delta=deltas["turnover_delta"],
        cost_delta=deltas["cost_delta"],
        confidence_interval=measurement.metrics.paired_return_ci,
        verdict=(
            TournamentVerdict.PROMOTE
            if allow_promotion and not unique_reasons
            else (
                TournamentVerdict.BLOCKED_DATA_QUALITY
                if evidence.data_blockers
                else TournamentVerdict.RETAIN_SHADOW
            )
        ),
        reason_codes=unique_reasons or ("ALPHA_ENGINE3_PROMOTION_GATES_PASS",),
    )


def render_tournament_report(evaluation: ControlledTournamentEvaluation) -> str:
    """Render a concise operator-facing report, including the paired table."""

    lines = [
        "# ROUND78 — Controlled Intelligence Promotion Tournament",
        "",
        "Verdict: **{}**".format(
            "BLOCKED_DATA_QUALITY"
            if "CERTIFIED_DATA_FOUNDATION_REQUIRED" in evaluation.blockers
            else "BLOCKED_INSUFFICIENT_EVIDENCE"
            if evaluation.blockers
            else "ENGINEERING_ONLY"
        ),
        "",
        "| Policy | Sample | Return Δ | Excess Δ | Sharpe Δ | Max DD Δ | "
        "Upside Δ | Downside Δ | Turnover Δ | Cost Δ | Exposure Δ | Recovery Δ | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in evaluation.variant_results:
        values = [
            row.policy.value,
            str(row.sample_count),
            _fmt(row.return_delta),
            _fmt(row.excess_return_delta),
            _fmt(row.sharpe_delta),
            _fmt(row.max_drawdown_delta),
            _fmt(row.upside_capture_delta),
            _fmt(row.downside_capture_delta),
            _fmt(row.turnover_delta),
            _fmt(row.cost_delta),
            _fmt(row.exposure_delta),
            _fmt(row.recovery_participation_delta),
            row.verdict.value,
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            f"PRODUCTION POLICY: {evaluation.production_policy.value}",
            f"ALPHA ENGINE 3: {evaluation.alpha_engine3.value}",
            "ALPHA ENGINE 3 PAIRED ATTRIBUTION: "
            f"sample={evaluation.alpha_engine3_attribution.sample_count}; "
            "selection return Δ="
            f"{_fmt(evaluation.alpha_engine3_attribution.selection_return_delta)}; "
            "selection excess Δ="
            f"{_fmt(evaluation.alpha_engine3_attribution.selection_excess_return_delta)}; "
            f"verdict={evaluation.alpha_engine3_attribution.verdict.value}",
            f"PROBABILITY: {evaluation.probability.value}",
            f"LLM LEVEL: {evaluation.llm_level.value}",
            f"LLM FORMAL INFLUENCE: {evaluation.llm_formal_influence:.4f}",
            f"ADAPTIVE EXPOSURE: {evaluation.adaptive_exposure.value}",
            "STRONGEST CHALLENGER: "
            + (
                evaluation.strongest_challenger.value
                if evaluation.strongest_challenger
                else "N/A"
            ),
            "",
            "Blockers: " + ("; ".join(evaluation.blockers) if evaluation.blockers else "none"),
            "",
            "Economic claims require certified PIT/survivorship/tradability/benchmark "
            "and locked-OOS evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.6f}"
