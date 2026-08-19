"""ROUND76 production-parity historical replay with fail-closed evidence gates."""

# ruff: noqa: E501

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.research.certified_data import CertifiedDataResult
from personal_alpha_terminal.research.data_evidence import EvidenceStatus
from personal_alpha_terminal.research.locked_oos_protocol import (
    LockedOOSProtocolManifest,
    LockedOOSSealState,
    validate_protocol_manifest,
)


class ReplayVariant(StrEnum):
    PURE_QUANT = "PURE_QUANT"
    ALPHA_ENGINE3_CHALLENGER = "ALPHA_ENGINE3_CHALLENGER"
    QUANT_PLUS_PROBABILITY = "QUANT_PLUS_PROBABILITY"
    QUANT_PLUS_LLM = "QUANT_PLUS_LLM"
    QUANT_PLUS_PROBABILITY_PLUS_LLM = "QUANT_PLUS_PROBABILITY_PLUS_LLM"
    FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE = "FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE"


class ReplayEvidenceClass(StrEnum):
    CERTIFIED_HISTORICAL = "CERTIFIED_HISTORICAL"
    FIXTURE_SUPPLEMENTARY = "FIXTURE_SUPPLEMENTARY"
    BLOCKED = "BLOCKED"


class ReplayOutcomeState(StrEnum):
    SIMULATED = "SIMULATED"
    FALLBACK_PURE_QUANT = "FALLBACK_PURE_QUANT"
    SKIPPED_MISSING_EVIDENCE = "SKIPPED_MISSING_EVIDENCE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ReplayPortfolioState:
    cash: float
    target_weights: Mapping[str, float]
    actual_weights: Mapping[str, float]
    ledger_hash: str

    def __post_init__(self) -> None:
        _validate_long_only_weights(self.target_weights, "target_weights")
        _validate_long_only_weights(self.actual_weights, "actual_weights")
        if not isfinite(self.cash) or self.cash < 0 or self.cash > 1:
            raise ValueError("cash must be a finite fraction in [0, 1]")
        if not self.ledger_hash.strip():
            raise ValueError("ledger_hash is required")


@dataclass(frozen=True, slots=True)
class ReplayExecutionAssumption:
    execution_session: date
    execution_time: datetime
    executable_open: float
    executable_volume: float
    trading_status: str
    benchmark_session: date
    policy: str

    def __post_init__(self) -> None:
        _require_aware(self.execution_time, "execution_time")
        if not isfinite(self.executable_open) or self.executable_open <= 0:
            raise ValueError("executable_open must be finite and positive")
        if not isfinite(self.executable_volume) or self.executable_volume <= 0:
            raise ValueError("executable_volume must be finite and positive")
        if self.trading_status != "TRADABLE":
            raise ValueError("historical execution requires TRADABLE status")
        if not self.policy.strip():
            raise ValueError("execution policy is required")


@dataclass(frozen=True, slots=True)
class HistoricalLLMEvidence:
    source_hash: str
    source_identifier: str
    available_at: datetime
    provenance: str

    def __post_init__(self) -> None:
        _require_aware(self.available_at, "LLM evidence available_at")
        if not all(
            item.strip()
            for item in (self.source_hash, self.source_identifier, self.provenance)
        ):
            raise ValueError("historical LLM evidence provenance is required")


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    decision_id: str
    decision_time: datetime
    evidence_cutoff: datetime
    universe_id: str
    universe_hash: str
    model_hash: str
    config_hash: str
    requested_variant: ReplayVariant
    portfolio_before: ReplayPortfolioState
    target_weights: Mapping[str, float]
    execution: ReplayExecutionAssumption
    transaction_cost_bps: float
    slippage_bps: float
    security_identity_valid: bool
    pit_universe_member: bool
    prices_actions_visible: bool
    fundamentals_filings_visible: bool
    news_events_visible: bool
    evidence_hashes: tuple[str, ...]
    probability_evidence_hash: str | None = None
    llm_evidence: tuple[HistoricalLLMEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.decision_time, "decision_time")
        _require_aware(self.evidence_cutoff, "evidence_cutoff")
        if self.evidence_cutoff > self.decision_time:
            raise ValueError("evidence_cutoff cannot be after decision_time")
        if self.execution.execution_time <= self.decision_time:
            raise ValueError("execution_time must be after decision_time")
        if self.execution.execution_session <= self.decision_time.date():
            raise ValueError("execution must use the next legal session, not same session")
        if self.execution.benchmark_session != self.execution.execution_session:
            raise ValueError("benchmark session must align with execution session")
        if not all(
            item.strip()
            for item in (
                self.decision_id,
                self.universe_id,
                self.universe_hash,
                self.model_hash,
                self.config_hash,
            )
        ):
            raise ValueError("replay decision identity is required")
        _validate_long_only_weights(self.target_weights, "target_weights")
        if not isfinite(self.transaction_cost_bps) or self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps must be non-negative")
        if not isfinite(self.slippage_bps) or self.slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative")
        if not self.evidence_hashes or any(not item.strip() for item in self.evidence_hashes):
            raise ValueError("immutable evidence hashes are required")

    @property
    def alignment_key(self) -> tuple[object, ...]:
        return (
            self.decision_time,
            self.evidence_cutoff,
            self.universe_id,
            self.universe_hash,
            self.model_hash,
            self.config_hash,
            self.transaction_cost_bps,
            self.slippage_bps,
            self.execution.execution_session,
            self.execution.policy,
        )


@dataclass(frozen=True, slots=True)
class ReplayAccounting:
    cash: float
    target_weights: Mapping[str, float]
    actual_weights: Mapping[str, float]
    turnover: float
    transaction_cost: float
    slippage_cost: float
    realized_pnl: float
    unrealized_pnl: float
    portfolio_return: float
    benchmark_return: float
    concentration: float
    gross_exposure: float
    risk_constraints_satisfied: bool
    ledger_hash: str

    def __post_init__(self) -> None:
        _validate_long_only_weights(self.target_weights, "accounting target_weights")
        _validate_long_only_weights(self.actual_weights, "accounting actual_weights")
        for field_name in (
            "cash",
            "turnover",
            "transaction_cost",
            "slippage_cost",
            "realized_pnl",
            "unrealized_pnl",
            "portfolio_return",
            "benchmark_return",
            "concentration",
            "gross_exposure",
        ):
            value = float(getattr(self, field_name))
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if self.cash < 0 or self.cash > 1 or self.turnover < 0:
            raise ValueError("cash/turnover are invalid")
        if self.transaction_cost < 0 or self.slippage_cost < 0:
            raise ValueError("costs must be non-negative")
        if self.concentration < 0 or self.gross_exposure < 0:
            raise ValueError("concentration/exposure must be non-negative")
        if not self.risk_constraints_satisfied:
            raise ValueError("historical replay cannot bypass risk constraints")
        if not self.ledger_hash.strip():
            raise ValueError("accounting ledger_hash is required")


@dataclass(frozen=True, slots=True)
class ReplayArtifact:
    decision_id: str
    decision_timestamp: datetime
    evidence_cutoff: datetime
    universe_id: str
    universe_hash: str
    model_hash: str
    config_hash: str
    requested_variant: ReplayVariant
    effective_variant: ReplayVariant
    outcome_state: ReplayOutcomeState
    evidence_class: ReplayEvidenceClass
    target_weights: Mapping[str, float]
    execution_assumption: ReplayExecutionAssumption
    transaction_cost_bps: float
    slippage_bps: float
    accounting: ReplayAccounting | None
    blockers: tuple[str, ...]
    artifact_hash: str

    def document(self) -> dict[str, object]:
        document = asdict(self)
        document["decision_timestamp"] = self.decision_timestamp.astimezone(UTC).isoformat()
        document["evidence_cutoff"] = self.evidence_cutoff.astimezone(UTC).isoformat()
        document["requested_variant"] = self.requested_variant.value
        document["effective_variant"] = self.effective_variant.value
        document["outcome_state"] = self.outcome_state.value
        document["evidence_class"] = self.evidence_class.value
        return document


@dataclass(frozen=True, slots=True)
class ReplayRunResult:
    status: EvidenceStatus
    artifacts: tuple[ReplayArtifact, ...]
    blockers: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "artifacts": [item.document() for item in self.artifacts],
            "blockers": list(self.blockers),
        }


class ProductionParityReplayEngine:
    """Replay production-shaped decisions using a simulation callback only.

    The callback receives already-validated inputs and returns accounting.  This
    module has no broker dependency or order API and never writes a live ledger.
    """

    def run(
        self,
        decisions: Sequence[ReplayDecision],
        *,
        data_certification: CertifiedDataResult,
        locked_oos_manifest: LockedOOSProtocolManifest | None,
        simulate_execution: Callable[[ReplayDecision, ReplayVariant], ReplayAccounting],
        evidence_class: ReplayEvidenceClass = ReplayEvidenceClass.CERTIFIED_HISTORICAL,
    ) -> ReplayRunResult:
        gate_status, gate_blockers = _replay_gate(data_certification, locked_oos_manifest)
        if gate_blockers:
            return ReplayRunResult(gate_status, (), gate_blockers)
        if locked_oos_manifest is None:
            raise AssertionError("validated replay gate must provide a locked OOS manifest")
        artifacts: list[ReplayArtifact] = []
        blockers: list[str] = []
        for decision in sorted(decisions, key=lambda item: (item.decision_time, item.decision_id)):
            decision_blockers = _decision_blockers(decision, locked_oos_manifest)
            if decision_blockers:
                blockers.extend(f"{decision.decision_id}:{item}" for item in decision_blockers)
                artifacts.append(_blocked_artifact(decision, tuple(decision_blockers)))
                continue
            effective_variant, outcome_state, variant_blockers = _effective_variant(decision)
            if outcome_state is ReplayOutcomeState.SKIPPED_MISSING_EVIDENCE:
                artifacts.append(_skipped_artifact(decision, effective_variant, variant_blockers))
                continue
            accounting = simulate_execution(decision, effective_variant)
            artifact = _artifact(
                decision,
                effective_variant=effective_variant,
                outcome_state=outcome_state,
                evidence_class=evidence_class,
                accounting=accounting,
                blockers=variant_blockers,
            )
            artifacts.append(artifact)
        alignment_blockers = validate_synchronized_variants(artifacts)
        blockers.extend(alignment_blockers)
        if evidence_class is not ReplayEvidenceClass.CERTIFIED_HISTORICAL:
            blockers.append("CERTIFIED_HISTORICAL_REPLAY_ARTIFACTS_REQUIRED")
        status = EvidenceStatus.PASS if not blockers else EvidenceStatus.BLOCKED_DATA_QUALITY
        return ReplayRunResult(status, tuple(artifacts), tuple(dict.fromkeys(blockers)))


def production_parity_replay_status(
    *,
    data_certification: CertifiedDataResult,
    locked_oos_manifest: LockedOOSProtocolManifest | None,
) -> ReplayRunResult:
    """Return readiness only; it never executes a historical decision."""

    status, blockers = _replay_gate(data_certification, locked_oos_manifest)
    return ReplayRunResult(status, (), blockers)


def validate_synchronized_variants(artifacts: Iterable[ReplayArtifact]) -> tuple[str, ...]:
    """Ensure each variant comparison shares cutoff, universe, costs and execution."""

    by_timestamp: dict[datetime, list[ReplayArtifact]] = defaultdict(list)
    for artifact in artifacts:
        if artifact.outcome_state in {ReplayOutcomeState.SIMULATED, ReplayOutcomeState.FALLBACK_PURE_QUANT}:
            by_timestamp[artifact.decision_timestamp].append(artifact)
    blockers: list[str] = []
    for timestamp, rows in by_timestamp.items():
        if len(rows) < 2:
            continue
        baseline = _artifact_alignment_key(rows[0])
        for row in rows[1:]:
            if _artifact_alignment_key(row) != baseline:
                blockers.append(f"{timestamp.isoformat()}:SYNCHRONIZED_VARIANT_ALIGNMENT_MISMATCH")
                break
    return tuple(blockers)


def persist_replay_artifact(path: Path, artifact: ReplayArtifact) -> None:
    """Write one artifact once; frozen replay evidence cannot be overwritten."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            artifact.document(),
            handle,
            default=str,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")


def _replay_gate(
    data_certification: CertifiedDataResult,
    locked_oos_manifest: LockedOOSProtocolManifest | None,
) -> tuple[EvidenceStatus, tuple[str, ...]]:
    blockers: list[str] = []
    if data_certification.overall_status is not EvidenceStatus.PASS:
        blockers.append("CERTIFIED_PIT_SURVIVORSHIP_BENCHMARK_TRADABILITY_DATA_REQUIRED")
    if locked_oos_manifest is None:
        blockers.append("LOCKED_OOS_PROTOCOL_REQUIRED")
    else:
        if data_certification.package_hash != locked_oos_manifest.dataset_hash:
            blockers.append("LOCKED_OOS_DATASET_HASH_MISMATCH")
        blockers.extend(validate_protocol_manifest(locked_oos_manifest))
        if locked_oos_manifest.seal_state is not LockedOOSSealState.SEALED:
            blockers.append("LOCKED_OOS_PROTOCOL_MUST_BE_SEALED_BEFORE_REPLAY")
    status = EvidenceStatus.BLOCKED_DATA_QUALITY if data_certification.overall_status is not EvidenceStatus.PASS else EvidenceStatus.BLOCKED_OOS
    return (EvidenceStatus.PASS, ()) if not blockers else (status, tuple(dict.fromkeys(blockers)))


def _decision_blockers(
    decision: ReplayDecision,
    locked_oos_manifest: LockedOOSProtocolManifest,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not decision.security_identity_valid:
        blockers.append("HISTORICAL_SECURITY_IDENTITY_UNRESOLVED")
    if not decision.pit_universe_member:
        blockers.append("PIT_UNIVERSE_MEMBERSHIP_UNRESOLVED")
    if not decision.prices_actions_visible:
        blockers.append("PIT_PRICES_OR_CORPORATE_ACTIONS_NOT_VISIBLE")
    if not decision.fundamentals_filings_visible:
        blockers.append("PIT_FUNDAMENTALS_OR_FILINGS_NOT_VISIBLE")
    if not decision.news_events_visible:
        blockers.append("PIT_NEWS_OR_EVENTS_NOT_VISIBLE")
    if decision.model_hash != locked_oos_manifest.model_hash:
        blockers.append("LOCKED_OOS_MODEL_HASH_MISMATCH")
    if decision.config_hash != locked_oos_manifest.config_hash:
        blockers.append("LOCKED_OOS_CONFIG_HASH_MISMATCH")
    if abs(decision.transaction_cost_bps - locked_oos_manifest.transaction_costs_bps) > 1e-12:
        blockers.append("LOCKED_OOS_TRANSACTION_COSTS_MISMATCH")
    if abs(decision.slippage_bps - locked_oos_manifest.slippage_bps) > 1e-12:
        blockers.append("LOCKED_OOS_SLIPPAGE_MISMATCH")
    if any(item.available_at > decision.evidence_cutoff for item in decision.llm_evidence):
        blockers.append("LLM_EVIDENCE_AFTER_DECISION_CUTOFF")
    return tuple(blockers)


def _effective_variant(
    decision: ReplayDecision,
) -> tuple[ReplayVariant, ReplayOutcomeState, tuple[str, ...]]:
    requested = decision.requested_variant
    needs_probability = requested in {
        ReplayVariant.QUANT_PLUS_PROBABILITY,
        ReplayVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM,
        ReplayVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE,
    }
    needs_llm = requested in {
        ReplayVariant.QUANT_PLUS_LLM,
        ReplayVariant.QUANT_PLUS_PROBABILITY_PLUS_LLM,
        ReplayVariant.FULL_INTELLIGENCE_ADAPTIVE_EXPOSURE,
    }
    blockers: list[str] = []
    if needs_probability and not decision.probability_evidence_hash:
        blockers.append("PROBABILITY_HISTORICAL_EVIDENCE_MISSING")
    if needs_llm and not decision.llm_evidence:
        blockers.append("LLM_HISTORICAL_EVIDENCE_MISSING_QUANT_FAIL_SOFT")
    if needs_llm and any(item.available_at > decision.evidence_cutoff for item in decision.llm_evidence):
        blockers.append("LLM_EVIDENCE_AFTER_CUTOFF_QUANT_FAIL_SOFT")
    if blockers:
        if needs_llm:
            return ReplayVariant.PURE_QUANT, ReplayOutcomeState.FALLBACK_PURE_QUANT, tuple(blockers)
        return requested, ReplayOutcomeState.SKIPPED_MISSING_EVIDENCE, tuple(blockers)
    return requested, ReplayOutcomeState.SIMULATED, ()


def _artifact(
    decision: ReplayDecision,
    *,
    effective_variant: ReplayVariant,
    outcome_state: ReplayOutcomeState,
    evidence_class: ReplayEvidenceClass,
    accounting: ReplayAccounting,
    blockers: tuple[str, ...],
) -> ReplayArtifact:
    provisional = ReplayArtifact(
        decision_id=decision.decision_id,
        decision_timestamp=decision.decision_time,
        evidence_cutoff=decision.evidence_cutoff,
        universe_id=decision.universe_id,
        universe_hash=decision.universe_hash,
        model_hash=decision.model_hash,
        config_hash=decision.config_hash,
        requested_variant=decision.requested_variant,
        effective_variant=effective_variant,
        outcome_state=outcome_state,
        evidence_class=evidence_class,
        target_weights=dict(decision.target_weights),
        execution_assumption=decision.execution,
        transaction_cost_bps=decision.transaction_cost_bps,
        slippage_bps=decision.slippage_bps,
        accounting=accounting,
        blockers=blockers,
        artifact_hash="",
    )
    return replace(provisional, artifact_hash=_artifact_hash(provisional))


def _blocked_artifact(decision: ReplayDecision, blockers: tuple[str, ...]) -> ReplayArtifact:
    return _artifact_without_accounting(
        decision,
        effective_variant=decision.requested_variant,
        outcome_state=ReplayOutcomeState.BLOCKED,
        blockers=blockers,
    )


def _skipped_artifact(
    decision: ReplayDecision,
    effective_variant: ReplayVariant,
    blockers: tuple[str, ...],
) -> ReplayArtifact:
    return _artifact_without_accounting(
        decision,
        effective_variant=effective_variant,
        outcome_state=ReplayOutcomeState.SKIPPED_MISSING_EVIDENCE,
        blockers=blockers,
    )


def _artifact_without_accounting(
    decision: ReplayDecision,
    *,
    effective_variant: ReplayVariant,
    outcome_state: ReplayOutcomeState,
    blockers: tuple[str, ...],
) -> ReplayArtifact:
    provisional = ReplayArtifact(
        decision_id=decision.decision_id,
        decision_timestamp=decision.decision_time,
        evidence_cutoff=decision.evidence_cutoff,
        universe_id=decision.universe_id,
        universe_hash=decision.universe_hash,
        model_hash=decision.model_hash,
        config_hash=decision.config_hash,
        requested_variant=decision.requested_variant,
        effective_variant=effective_variant,
        outcome_state=outcome_state,
        evidence_class=ReplayEvidenceClass.BLOCKED,
        target_weights=dict(decision.target_weights),
        execution_assumption=decision.execution,
        transaction_cost_bps=decision.transaction_cost_bps,
        slippage_bps=decision.slippage_bps,
        accounting=None,
        blockers=blockers,
        artifact_hash="",
    )
    return replace(provisional, artifact_hash=_artifact_hash(provisional))


def _artifact_alignment_key(artifact: ReplayArtifact) -> tuple[object, ...]:
    execution = artifact.execution_assumption
    return (
        artifact.evidence_cutoff,
        artifact.universe_id,
        artifact.universe_hash,
        artifact.model_hash,
        artifact.config_hash,
        artifact.transaction_cost_bps,
        artifact.slippage_bps,
        execution.execution_session,
        execution.policy,
    )


def _artifact_hash(artifact: ReplayArtifact) -> str:
    payload = asdict(artifact)
    payload["artifact_hash"] = ""
    return fingerprint(payload)


def _validate_long_only_weights(weights: Mapping[str, float], label: str) -> None:
    if not weights:
        raise ValueError(f"{label} cannot be empty")
    total = 0.0
    for symbol, value in weights.items():
        if not symbol.strip() or not isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"{label} must be finite and long-only")
        total += float(value)
    if total > 1.0000001:
        raise ValueError(f"{label} cannot exceed 100% gross long exposure")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
