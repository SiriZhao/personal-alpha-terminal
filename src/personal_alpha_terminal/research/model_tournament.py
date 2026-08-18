"""ROUND65 locked model-tournament governance.

The module freezes contender identities and evidence requirements before an
evaluation. Synthetic diagnostics may be recorded, but cannot promote a model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
from math import isfinite


class TournamentVerdict(StrEnum):
    PROMOTE_NEW_CHAMPION = "PROMOTE_NEW_CHAMPION"
    KEEP_EXISTING_CHAMPION = "KEEP_EXISTING_CHAMPION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"


class TournamentContender(StrEnum):
    OLD_PRODUCTION_BASELINE = "OLD_PRODUCTION_BASELINE"
    ALPHA_ENGINE3_QUANT_ONLY = "ALPHA_ENGINE3_QUANT_ONLY"
    QUANT_PLUS_PROBABILITY = "QUANT_PLUS_PROBABILITY"
    QUANT_PLUS_LLM_ALPHA_OVERLAY = "QUANT_PLUS_LLM_ALPHA_OVERLAY"
    QUANT_PLUS_LLM_REGIME_CONTROLLER = "QUANT_PLUS_LLM_REGIME_CONTROLLER"
    QUANT_PLUS_PROBABILITY_PLUS_LLM = "QUANT_PLUS_PROBABILITY_PLUS_LLM"
    FULL_AGENTIC_CHALLENGER = "FULL_AGENTIC_CHALLENGER"
    BEST_ADAPTIVE_PARTICIPATION = "BEST_ADAPTIVE_PARTICIPATION"
    CORE_PLUS_ACTIVE_ALPHA = "CORE_PLUS_ACTIVE_ALPHA"


class TournamentEvidenceClass(StrEnum):
    LOCKED_OOS = "LOCKED_OOS"
    SYNTHETIC_DIAGNOSTIC = "SYNTHETIC_DIAGNOSTIC"
    ENGINEERING_ONLY = "ENGINEERING_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


REQUIRED_ABLATION_COMPONENTS = (
    "momentum",
    "trend",
    "low_volatility",
    "fundamentals",
    "probability",
    "llm_event_alpha",
    "llm_regime_controller",
    "adaptive_participation",
    "optimizer",
)


@dataclass(frozen=True, slots=True)
class FrozenTournamentConfiguration:
    universe_id: str
    feature_set_hash: str
    preprocessing_version: str
    label_horizons: tuple[int, ...]
    model_hyperparameters_hash: str
    llm_provider: str
    llm_model: str
    llm_prompt_hash: str
    probability_model_version: str
    portfolio_constraints_hash: str
    cost_model_version: str
    benchmark_ids: tuple[str, ...]
    rebalance_cadence: str
    exposure_policy: str
    evaluation_windows: tuple[str, ...]
    random_seed: int

    def __post_init__(self) -> None:
        text_values = (
            self.universe_id,
            self.feature_set_hash,
            self.preprocessing_version,
            self.model_hyperparameters_hash,
            self.llm_provider,
            self.llm_model,
            self.llm_prompt_hash,
            self.probability_model_version,
            self.portfolio_constraints_hash,
            self.cost_model_version,
            self.rebalance_cadence,
            self.exposure_policy,
        )
        if any(not item.strip() for item in text_values):
            raise ValueError("tournament freeze fields must be non-empty")
        if not self.label_horizons or any(item <= 0 for item in self.label_horizons):
            raise ValueError("tournament label horizons must be positive")
        if not self.benchmark_ids or not self.evaluation_windows or self.random_seed < 0:
            raise ValueError("tournament freeze collections and seed are invalid")

    @property
    def configuration_hash(self) -> str:
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class TournamentMetricSet:
    total_return: float | None = None
    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    maximum_drawdown: float | None = None
    calmar: float | None = None
    beta: float | None = None
    alpha: float | None = None
    excess_vs_spy: float | None = None
    excess_vs_qqq: float | None = None
    information_ratio: float | None = None
    upside_capture: float | None = None
    downside_capture: float | None = None
    turnover: float | None = None
    transaction_cost: float | None = None
    slippage: float | None = None
    average_gross: float | None = None
    average_cash: float | None = None
    tail_loss: float | None = None
    regime_performance: tuple[tuple[str, float], ...] = ()
    confidence_interval: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        scalar_values = (
            self.total_return,
            self.cagr,
            self.volatility,
            self.sharpe,
            self.sortino,
            self.maximum_drawdown,
            self.calmar,
            self.beta,
            self.alpha,
            self.excess_vs_spy,
            self.excess_vs_qqq,
            self.information_ratio,
            self.upside_capture,
            self.downside_capture,
            self.turnover,
            self.transaction_cost,
            self.slippage,
            self.average_gross,
            self.average_cash,
            self.tail_loss,
        )
        if any(value is not None and not isfinite(value) for value in scalar_values):
            raise ValueError("tournament metrics must be finite when present")
        if any(not name or not isfinite(value) for name, value in self.regime_performance):
            raise ValueError("tournament regime metrics are invalid")
        if self.confidence_interval is not None:
            lower, upper = self.confidence_interval
            if not isfinite(lower) or not isfinite(upper) or lower > upper:
                raise ValueError("tournament confidence interval is invalid")


@dataclass(frozen=True, slots=True)
class TournamentEvidenceState:
    certified_pit_dataset: bool
    historical_membership_coverage: float
    locked_oos_status: str
    locked_oos_independent_sessions: int
    probability_forward_observations: int
    llm_forward_observations: int
    probability_promotion_approved: bool
    llm_promotion_approved: bool
    adaptive_participation_oos_validated: bool
    minimum_independent_sessions: int = 40

    def __post_init__(self) -> None:
        if not 0 <= self.historical_membership_coverage <= 1:
            raise ValueError("historical membership coverage must be in [0, 1]")
        counts = (
            self.locked_oos_independent_sessions,
            self.probability_forward_observations,
            self.llm_forward_observations,
            self.minimum_independent_sessions,
        )
        if any(item < 0 for item in counts) or self.minimum_independent_sessions == 0:
            raise ValueError("tournament evidence counts are invalid")
        if not self.locked_oos_status.strip():
            raise ValueError("locked OOS status must be explicit")

    @property
    def data_quality_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.certified_pit_dataset:
            blockers.append("CERTIFIED_PIT_DATASET_REQUIRED")
        if self.historical_membership_coverage < 1.0:
            blockers.append("HISTORICAL_MEMBERSHIP_INCOMPLETE")
        if self.locked_oos_status != "CERTIFIED":
            blockers.append("LOCKED_OOS_NOT_CERTIFIABLE")
        return tuple(blockers)

    @property
    def evidence_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.locked_oos_independent_sessions < self.minimum_independent_sessions:
            blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
        if self.probability_forward_observations < self.minimum_independent_sessions:
            blockers.append("PROBABILITY_FORWARD_EVIDENCE_INSUFFICIENT")
        if self.llm_forward_observations < self.minimum_independent_sessions:
            blockers.append("LLM_FORWARD_EVIDENCE_INSUFFICIENT")
        if not self.adaptive_participation_oos_validated:
            blockers.append("ADAPTIVE_PARTICIPATION_OOS_NOT_VALIDATED")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class TournamentDiagnostic:
    contender: TournamentContender
    evidence_class: TournamentEvidenceClass
    metrics: TournamentMetricSet | None
    eligible_for_promotion: bool
    formal_quant_influence: float
    formal_probability_influence: float
    formal_llm_influence: float
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        influences = (
            self.formal_quant_influence,
            self.formal_probability_influence,
            self.formal_llm_influence,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in influences):
            raise ValueError("tournament formal influences must be in [0, 1]")
        if (
            self.eligible_for_promotion
            and self.evidence_class is not TournamentEvidenceClass.LOCKED_OOS
        ):
            raise ValueError("only locked-OOS evidence may be eligible for promotion")
        if self.metrics is None and not self.blockers:
            raise ValueError("missing tournament metrics require an explicit blocker")


@dataclass(frozen=True, slots=True)
class ComponentAblation:
    component: str
    evidence_class: TournamentEvidenceClass
    marginal_net_return: float | None
    marginal_information_ratio: float | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (self.marginal_net_return, self.marginal_information_ratio)
        if any(value is not None and not isfinite(value) for value in values):
            raise ValueError("ablation values must be finite when present")
        if all(value is None for value in values) and not self.blockers:
            raise ValueError("unmeasured ablation requires an explicit blocker")


@dataclass(frozen=True, slots=True)
class LockedModelTournamentResult:
    configuration_hash: str
    verdict: TournamentVerdict
    champion: TournamentContender
    locked_oos_executed: bool
    diagnostics: tuple[TournamentDiagnostic, ...]
    ablations: tuple[ComponentAblation, ...]
    blockers: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return asdict(self)


def complete_ablation_ledger(
    observed: Mapping[str, ComponentAblation],
) -> tuple[ComponentAblation, ...]:
    unknown = set(observed) - set(REQUIRED_ABLATION_COMPONENTS)
    if unknown:
        raise ValueError(f"unknown tournament ablation components: {sorted(unknown)}")
    return tuple(
        observed.get(
            component,
            ComponentAblation(
                component=component,
                evidence_class=TournamentEvidenceClass.UNAVAILABLE,
                marginal_net_return=None,
                marginal_information_ratio=None,
                blockers=("NO_COMPARABLE_LOCKED_OOS_ABLATION",),
            ),
        )
        for component in REQUIRED_ABLATION_COMPONENTS
    )


def run_locked_model_tournament(
    configuration: FrozenTournamentConfiguration,
    evidence: TournamentEvidenceState,
    *,
    diagnostics: Mapping[TournamentContender, TournamentDiagnostic] | None = None,
    ablations: Mapping[str, ComponentAblation] | None = None,
    approved_candidate: TournamentContender | None = None,
) -> LockedModelTournamentResult:
    """Run the evidence gate after the immutable configuration is hashed."""

    supplied = diagnostics or {}
    data_blockers = evidence.data_quality_blockers
    evidence_blockers = evidence.evidence_blockers
    locked_ready = not data_blockers and not evidence_blockers
    normalized = tuple(
        _diagnostic_for(
            contender,
            supplied.get(contender),
            evidence=evidence,
            global_blockers=data_blockers + evidence_blockers,
            locked_ready=locked_ready,
        )
        for contender in TournamentContender
    )
    if data_blockers:
        verdict = TournamentVerdict.BLOCKED_DATA_QUALITY
    elif evidence_blockers:
        verdict = TournamentVerdict.INSUFFICIENT_EVIDENCE
    elif approved_candidate is None:
        verdict = TournamentVerdict.KEEP_EXISTING_CHAMPION
    else:
        candidate = next(item for item in normalized if item.contender is approved_candidate)
        verdict = (
            TournamentVerdict.PROMOTE_NEW_CHAMPION
            if candidate.eligible_for_promotion
            else TournamentVerdict.KEEP_EXISTING_CHAMPION
        )
    if verdict is TournamentVerdict.PROMOTE_NEW_CHAMPION:
        assert approved_candidate is not None
        champion = approved_candidate
    else:
        champion = TournamentContender.OLD_PRODUCTION_BASELINE
    return LockedModelTournamentResult(
        configuration_hash=configuration.configuration_hash,
        verdict=verdict,
        champion=champion,
        locked_oos_executed=locked_ready,
        diagnostics=normalized,
        ablations=complete_ablation_ledger(ablations or {}),
        blockers=data_blockers + evidence_blockers,
    )


def _diagnostic_for(
    contender: TournamentContender,
    supplied: TournamentDiagnostic | None,
    *,
    evidence: TournamentEvidenceState,
    global_blockers: tuple[str, ...],
    locked_ready: bool,
) -> TournamentDiagnostic:
    if supplied is not None and supplied.contender is not contender:
        raise ValueError("tournament diagnostic contender identity mismatch")
    local_blockers = list(global_blockers)
    if supplied is not None:
        local_blockers.extend(supplied.blockers)
    if _uses_probability(contender) and not evidence.probability_promotion_approved:
        local_blockers.append("PROBABILITY_PROMOTION_NOT_APPROVED")
    if _uses_llm(contender) and not evidence.llm_promotion_approved:
        local_blockers.append("LLM_PROMOTION_NOT_APPROVED")
    if contender in {
        TournamentContender.BEST_ADAPTIVE_PARTICIPATION,
        TournamentContender.CORE_PLUS_ACTIVE_ALPHA,
    } and not evidence.adaptive_participation_oos_validated:
        local_blockers.append("ADAPTIVE_PARTICIPATION_OOS_NOT_VALIDATED")
    evidence_class = supplied.evidence_class if supplied is not None else (
        TournamentEvidenceClass.UNAVAILABLE
    )
    metrics = supplied.metrics if supplied is not None else None
    eligible = (
        locked_ready
        and evidence_class is TournamentEvidenceClass.LOCKED_OOS
        and not local_blockers
        and metrics is not None
    )
    probability_influence = (
        supplied.formal_probability_influence
        if supplied is not None
        and eligible
        and evidence.probability_promotion_approved
        else 0.0
    )
    llm_influence = (
        supplied.formal_llm_influence
        if supplied is not None and eligible and evidence.llm_promotion_approved
        else 0.0
    )
    quant_influence = supplied.formal_quant_influence if supplied is not None else 1.0
    if not local_blockers and metrics is None:
        local_blockers.append("LOCKED_OOS_METRICS_NOT_SUPPLIED")
    return TournamentDiagnostic(
        contender=contender,
        evidence_class=evidence_class,
        metrics=metrics,
        eligible_for_promotion=eligible,
        formal_quant_influence=quant_influence,
        formal_probability_influence=probability_influence,
        formal_llm_influence=llm_influence,
        blockers=tuple(dict.fromkeys(local_blockers)),
    )


def _uses_probability(contender: TournamentContender) -> bool:
    return contender in {
        TournamentContender.QUANT_PLUS_PROBABILITY,
        TournamentContender.QUANT_PLUS_PROBABILITY_PLUS_LLM,
    }


def _uses_llm(contender: TournamentContender) -> bool:
    return contender in {
        TournamentContender.QUANT_PLUS_LLM_ALPHA_OVERLAY,
        TournamentContender.QUANT_PLUS_LLM_REGIME_CONTROLLER,
        TournamentContender.QUANT_PLUS_PROBABILITY_PLUS_LLM,
        TournamentContender.FULL_AGENTIC_CHALLENGER,
    }
