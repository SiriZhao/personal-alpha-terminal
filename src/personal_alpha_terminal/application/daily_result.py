from __future__ import annotations

import json
import platform
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


class StageStatus(StrEnum):
    PASS = "PASS"
    PASS_DEGRADED = "PASS_DEGRADED"
    OPTIONAL_UNAVAILABLE = "OPTIONAL_UNAVAILABLE"
    FAIL_BLOCKING = "FAIL_BLOCKING"
    NOT_RUN = "NOT_RUN"

    # Compatibility aliases for persisted pre-certificate snapshots.  New output
    # always serializes the explicit values above.
    WARN = "PASS_DEGRADED"
    FAIL = "FAIL_BLOCKING"
    SKIPPED = "NOT_RUN"


class DecisionReadiness(StrEnum):
    READY = "READY"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    status: StageStatus
    duration_seconds: float
    message: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class DataHealthItem:
    dataset: str
    expected_date: date | None
    latest_date: date | None
    age_days: int | None
    coverage: float | None
    missing_ratio: float | None
    source: str
    status: StageStatus
    detail: str = ""
    dataset_id: str = "UNAVAILABLE"
    as_of: date | None = None
    cutoff: datetime | None = None
    snapshot_id: str = "UNAVAILABLE"
    data_version: str = "UNAVAILABLE"
    provider: str = "UNAVAILABLE"
    row_count: int | None = None
    member_count: int | None = None
    quality_status: str = "UNAVAILABLE"
    content_hash: str = "UNAVAILABLE"
    certification_state: str = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class FactorRow:
    symbol: str
    components: dict[str, float]
    composite: float
    rank: int
    expected_alpha: float
    evidence_coverage: float
    status: str
    raw_values: dict[str, float] = field(default_factory=dict)
    winsorized_values: dict[str, float] = field(default_factory=dict)
    neutralized_values: dict[str, float] = field(default_factory=dict)
    neutralization_evidence: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProbabilityRow:
    condition: str
    target: str
    sample_size: int
    hits: int | None
    conditional_probability: float | None
    base_probability: float | None
    lift: float | None
    average_return: float | None
    median_return: float | None
    return_std: float | None
    credible_interval: tuple[float, float] | None
    reliability: str
    oos_status: str
    status: str


@dataclass(frozen=True, slots=True)
class PortfolioPositionRow:
    symbol: str
    shares: float | None
    price: float | None
    current_weight: float
    target_weight: float | None
    delta_weight: float | None


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    status: str
    nav: float | None
    cash: float | None
    cash_weight: float | None
    invested_weight: float | None
    positions: tuple[PortfolioPositionRow, ...]


@dataclass(frozen=True, slots=True)
class RiskSummary:
    status: str
    expected_volatility: float | None
    target_volatility: float | None
    drawdown: float | None
    hhi: float | None
    turnover: float | None
    gross_exposure: float | None
    cash_target: float | None
    exposure_multiplier: float | None
    largest_target_weight: float | None
    reasons: tuple[str, ...]
    recent_average_correlation: float | None = None
    baseline_average_correlation: float | None = None
    correlation_jump: float | None = None
    correlation_status: str = "NOT_CAPTURED"
    correlation_recent_window: int = 0
    correlation_baseline_window: int = 0
    correlation_sample_count: int = 0
    size_exposure_status: str = "NOT_CAPTURED"
    stress_status: str = "NOT_CAPTURED"
    stress_failures: tuple[str, ...] = ()
    stress_warnings: tuple[str, ...] = ()
    size_diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionRow:
    recommendation_id: str
    symbol: str
    action: str
    current_weight: float
    target_weight: float
    delta_weight: float
    estimated_value: float
    estimated_quantity: int
    estimated_cost: float
    expected_alpha: float
    confidence: float | None
    risk_contribution: float
    reason: str
    data_quality: str
    model_version: str
    data_version: str
    earliest_execution_time: datetime
    expiry: datetime
    confidence_source: str = "NOT_CALIBRATED"


@dataclass(frozen=True, slots=True)
class RejectedSignalRow:
    symbol: str
    rejected_by: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionLeg:
    sequence: int
    symbol: str
    action: str
    estimated_value: float
    estimated_quantity: int
    estimated_cost: float
    earliest_execution_time: datetime


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    status: str
    manual_execution_required: bool
    broker: str
    estimated_cash_before: float | None
    estimated_proceeds: float
    estimated_buys: float
    estimated_cash_after: float | None
    turnover: float | None
    estimated_cost: float
    legs: tuple[ExecutionLeg, ...]
    execution_plan_generated: bool = True
    broker_order_submitted: bool = False
    broker_api: str = "DISABLED"
    execution_mode: str = "MANUAL_ONLY"


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    name: str
    status: str
    observation_count: int
    period_return: float | None
    annualized_volatility: float | None
    note: str
    start_date: date | None = None
    end_date: date | None = None
    max_drawdown: float | None = None


@dataclass(frozen=True, slots=True)
class DailyQuantResult:
    run_id: str
    version: str
    started_at: datetime
    finished_at: datetime
    analysis_date: date
    trade_date: date
    market_session: str
    market_structure: str
    data_cutoff: datetime | None
    decision_readiness: DecisionReadiness
    llm_status: str
    stages: tuple[StageResult, ...]
    data_health: tuple[DataHealthItem, ...]
    market_regime: str
    market_regime_detail: str
    factors: tuple[FactorRow, ...]
    probabilities: tuple[ProbabilityRow, ...]
    candidates: tuple[FactorRow, ...]
    portfolio: PortfolioSummary
    risk: RiskSummary
    final_decisions: tuple[DecisionRow, ...]
    rejected_signals: tuple[RejectedSignalRow, ...]
    execution_plan: ExecutionPlan
    benchmarks: tuple[BenchmarkSummary, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance: dict[str, object]
    config_hash: str
    model_versions: tuple[str, ...]
    decision_traces: dict[str, dict[str, object]] | None = None
    certificate_path: str | None = None
    operational_readiness: str = "BLOCKED"
    operational_approval_artifact_id: str = "NOT_APPROVED"
    research_certification_state: str = "NOT_CERTIFIABLE"
    operational_policy_id: str = "NOT_CONFIGURED"
    operational_policy_decision: str = "BLOCK"
    operational_policy_effective: bool = False
    operational_policy_reason: str = "OPERATIONAL_POLICY_NOT_CONFIGURED"
    operationally_allowed: bool = False
    operational_degraded_reason: str | None = None
    # ROUND24: ETF multi-sleeve evidence and the AI Chinese advisory brief.
    # Both are additive; the Classical Champion path is unchanged.
    etf_universe: dict[str, object] = field(default_factory=dict)
    etf_targets: tuple[dict[str, object], ...] = field(default_factory=tuple)
    etf_composition: dict[str, object] | None = None
    ai_brief: dict[str, object] | None = None
    # ROUND25 PHASE 7: pre-execution overnight risk assessment (advisory only;
    # never cancels, never recomputes alpha).
    pre_execution: dict[str, object] | None = None
    # ROUND26 P0: sealed DecisionManifest -- the single source of truth for
    # every formal output of this run.
    decision_manifest: dict[str, object] | None = None
    # ROUND26 P0: current operational size/sector exposure evidence
    # (strictly separated from historical PIT exposure).
    current_exposure: dict[str, object] | None = None
    # ROUND28 P0: per-formal-decision immutable provenance (factor inputs,
    # optimizer raw/constrained target, risk, cost, gates and hashes).
    decision_provenance: dict[str, object] | None = None

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())

    @property
    def actionable(self) -> bool:
        required = {
            "CALENDAR",
            "DATA",
            "PIT",
            "FEATURE",
            "FACTOR",
            "SIGNAL",
            "PROBABILITY",
            "PORTFOLIO",
            "RISK",
            "DECISION",
            "EXECUTION",
        }
        completed = {
            item.name
            for item in self.stages
            if item.status in {StageStatus.PASS, StageStatus.PASS_DEGRADED}
        }
        return (
            self.decision_readiness is DecisionReadiness.READY
            and required <= completed
        )

    @property
    def diagnostic_analysis_complete(self) -> bool:
        """Return whether the portfolio-independent quant analysis completed.

        This is deliberately weaker than ``actionable``.  It allows a user with
        no initialized real portfolio to inspect PIT factors, alpha and
        probability evidence without suggesting that a trading decision exists.
        """

        # A strategy-approval failure does not invalidate the completed data and
        # alpha-candidate analysis. It remains non-actionable because ``actionable``
        # still requires SIGNAL through EXECUTION; this property only classifies
        # the portfolio-independent diagnostic core.
        required = {"CALENDAR", "DATA", "PIT", "FEATURE", "FACTOR"}
        completed = {
            item.name
            for item in self.stages
            if item.status in {StageStatus.PASS, StageStatus.PASS_DEGRADED}
        }
        return required <= completed

    @property
    def run_classification(self) -> str:
        if not self.actionable:
            return (
                "VALID_ANALYSIS_NON_ACTIONABLE"
                if self.diagnostic_analysis_complete
                else "INVALID_NON_ACTIONABLE"
            )
        if self.operationally_allowed:
            return "VALID_ANALYSIS_ACTIONABLE_PROVISIONAL"
        return "VALID_ANALYSIS_ACTIONABLE_CERTIFIED"

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_value(asdict(self)))

    def persist(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"{self.analysis_date.isoformat()}_{self.run_id}.json"
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(output)
        return output

    def persist_evidence(self, directory: Path) -> Path:
        """Persist stage manifests and the run certificate from this exact result.

        This method never calculates quant values.  It materializes evidence already
        produced by the canonical pipeline so every manifest has the same run id and
        cutoff as the terminal report.
        """

        run_directory = directory / self.run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        evidence_chain = build_stage_evidence_chain(self)
        for stage, evidence in zip(self.stages, evidence_chain, strict=True):
            payload = {
                "run_id": self.run_id,
                "analysis_date": self.analysis_date.isoformat(),
                "trade_date": self.trade_date.isoformat(),
                "data_cutoff": self.data_cutoff.isoformat() if self.data_cutoff else None,
                "stage": stage.name,
                "stage_version": self.version,
                "status": stage.status.value,
                "duration_seconds": stage.duration_seconds,
                "message": stage.message,
                "diagnostics": stage.metadata,
                **evidence,
                "output_row_count": stage.metadata.get("output_row_count", 0),
            }
            _atomic_json(run_directory / f"{stage.name.lower()}_manifest.json", payload)
        stage_evidence = {
            item.name: _json_value(item.metadata) for item in self.stages
        }
        probability_overlay = self.provenance.get("probability_overlay", {})
        if not isinstance(probability_overlay, dict):
            probability_overlay = {}
        certificate = {
            "certificate_schema": "pat-quant-run-certificate-v2",
            "run_id": self.run_id,
            "classification": self.run_classification,
            "trading_use": (
                "MANUAL_REVIEW_REQUIRED" if self.actionable else "DO_NOT_USE_FOR_TRADING"
            ),
            "operational_readiness": self.operational_readiness,
            "operational_approval_artifact_id": self.operational_approval_artifact_id,
            "operational_policy_id": self.operational_policy_id,
            "operational_policy_decision": self.operational_policy_decision,
            "operational_policy_effective": self.operational_policy_effective,
            "operational_policy_reason": self.operational_policy_reason,
            "operational_authorization": self.operational_policy_decision,
            "policy_id": self.operational_policy_id,
            "policy_hash": self.provenance.get(
                "operational_policy_hash", "NOT_CONFIGURED"
            ),
            "policy_identity_hash": self.provenance.get(
                "operational_policy_identity_hash", "NOT_CONFIGURED"
            ),
            "signal_authorization_class": self.provenance.get(
                "signal_authorization_class", "FAIL_BLOCKING"
            ),
            "operationally_allowed": self.operationally_allowed,
            "operational_degraded_reason": self.operational_degraded_reason,
            "research_certification_state": self.research_certification_state,
            "probability_mode": probability_overlay.get(
                "reason", "PROBABILITY_FALLBACK_CLASSICAL"
            ),
            "probability_influence": (
                1.0
                if probability_overlay.get("active")
                else 0.0
            ),
            "llm_mode": "SHADOW",
            "auto_execution": False,
            "manual_execution_only": True,
            "execution_plan_generated": self.execution_plan.execution_plan_generated,
            "broker_order_submitted": self.execution_plan.broker_order_submitted,
            "broker_api": self.execution_plan.broker_api,
            "execution_mode": self.execution_plan.execution_mode,
            "full_research_certified": False,
            "version": self.version,
            "build_identifier": self.provenance.get("build_identifier", self.version),
            "git_commit": self.provenance.get("git_commit", "UNAVAILABLE"),
            "randomness": self.provenance.get("randomness", "NOT_USED"),
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": sys.platform,
            },
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "analysis_date": self.analysis_date.isoformat(),
            "trade_date": self.trade_date.isoformat(),
            "market_session": self.market_session,
            "data_cutoff": self.data_cutoff.isoformat() if self.data_cutoff else None,
            "config_hash": self.config_hash,
            "identity_hashes": self.provenance.get("identity_hashes", {}),
            "canonical_input_hash": canonical_input_hash(self),
            "canonical_result_hash": canonical_result_hash(self),
            "evidence_identity": {
                "pit_cutoff": self.data_cutoff.isoformat() if self.data_cutoff else None,
                "data_snapshot_id": self.provenance.get(
                    "data_snapshot_id", "UNAVAILABLE"
                ),
                "data_hash": self.provenance.get("data_hash", "UNAVAILABLE"),
                "research_data_version": self.provenance.get(
                    "research_data_version", "UNAVAILABLE"
                ),
                "universe_version": self.provenance.get(
                    "universe_version", "UNAVAILABLE"
                ),
                "strategy_version": self.provenance.get(
                    "strategy_version", "UNAVAILABLE"
                ),
                "factor_version": self.provenance.get("factor_version", "UNAVAILABLE"),
                "signal_version": self.provenance.get("signal_version", "UNAVAILABLE"),
                "production_approval_artifact_id": self.provenance.get(
                    "production_approval_artifact_id", "NOT_APPROVED"
                ),
                "portfolio_validation_artifact_id": self.provenance.get(
                    "portfolio_validation_artifact_id", "NOT_APPROVED"
                ),
                "probability_artifact_id": self.provenance.get(
                    "probability_artifact_id", "OPTIONAL_UNAVAILABLE"
                ),
                "portfolio_snapshot_id": self.provenance.get(
                    "portfolio_snapshot_id", "NOT_INITIALIZED"
                ),
                "cost_assumptions": self.provenance.get("cost_assumptions", {}),
            },
            "stage_evidence_chain": evidence_chain,
            "stage_chain_root_hash": (
                evidence_chain[-1]["output_hash"] if evidence_chain else "UNAVAILABLE"
            ),
            "model_versions": list(self.model_versions),
            "stages": [_json_value(asdict(item)) for item in self.stages],
            "stage_evidence": stage_evidence,
            "data_certification": stage_evidence.get("DATA", {}),
            "data": [_json_value(asdict(item)) for item in self.data_health],
            "factor_count": len(self.factors),
            "factor_statistics": _factor_statistics(self.factors),
            "candidate_count": self._optimizer_candidate_count(),
            "signals": {
                "universe_size": self.provenance.get("universe_count", 0),
                "eligible": len(self.factors),
                "optimizer_candidate_count": self._optimizer_input_count(),
                "display_top10_candidates": [item.symbol for item in self.candidates],
                "rejected": len(self.rejected_signals),
            },
            "probability": [_json_value(asdict(item)) for item in self.probabilities],
            "portfolio": _json_value(asdict(self.portfolio)),
            "risk": _json_value(asdict(self.risk)),
            "decision_counts": {
                "BUY": sum(
                    item.action in {"BUY", "ADD", "INCREASE"}
                    for item in self.final_decisions
                ),
                "SELL": sum(item.action in {"SELL", "REDUCE"} for item in self.final_decisions),
                "HOLD": sum(item.action == "HOLD" for item in self.final_decisions),
                "REJECTED": len(self.rejected_signals),
            },
            "decision_recommendations": [
                _json_value(asdict(item)) for item in self.final_decisions
            ],
            "benchmarks": [_json_value(asdict(item)) for item in self.benchmarks],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "provenance": _json_value(self.provenance),
            "decision_traces": _json_value(self.decision_traces or {}),
            "decision_manifest": _json_value(self.decision_manifest or {}),
        }
        target = run_directory / "run_certificate.json"
        _atomic_json(target, certificate)
        if self.decision_provenance is not None:
            _atomic_json(
                run_directory / "decision_provenance.json",
                self.decision_provenance,
            )
        return target

    def _universe_evidence(self) -> dict[str, Any]:
        evidence = self.provenance.get("universe_evidence")
        return evidence if isinstance(evidence, dict) else {}

    def _optimizer_candidate_count(self) -> int:
        return int(str(self._universe_evidence().get("candidate_count", len(self.candidates))) or 0)

    def _optimizer_input_count(self) -> int:
        return int(str(self._universe_evidence().get("optimizer_input", 0)) or 0)


def canonical_input_hash(result: DailyQuantResult) -> str:
    """Stable identity for repeated runs over the same decision inputs."""

    return fingerprint(
        {
            "analysis_date": result.analysis_date,
            "trade_date": result.trade_date,
            "data_cutoff": result.data_cutoff,
            "config_hash": result.config_hash,
            "identity_hashes": result.provenance.get("identity_hashes", {}),
            "data_snapshot_id": result.provenance.get("data_snapshot_id"),
            "data_hash": result.provenance.get("data_hash"),
            "research_data_version": result.provenance.get("research_data_version"),
            "universe_version": result.provenance.get("universe_version"),
            "portfolio_snapshot_id": result.provenance.get("portfolio_snapshot_id"),
        }
    )


def canonical_result_hash(result: DailyQuantResult) -> str:
    """Stable hash of decision-critical outputs, excluding run timing and UUID."""

    return fingerprint(
        {
            "canonical_input_hash": canonical_input_hash(result),
            "classification": result.run_classification,
            "operational_readiness": result.operational_readiness,
            "operational_approval_artifact_id": result.operational_approval_artifact_id,
            "operational_policy_id": result.operational_policy_id,
            "operational_policy_decision": result.operational_policy_decision,
            "operational_policy_effective": result.operational_policy_effective,
            "operational_policy_reason": result.operational_policy_reason,
            "operationally_allowed": result.operationally_allowed,
            "operational_degraded_reason": result.operational_degraded_reason,
            "research_certification_state": result.research_certification_state,
            "stage_statuses": [
                (item.name, item.status.value, item.message) for item in result.stages
            ],
            "factors": [asdict(item) for item in result.factors],
            "probabilities": [asdict(item) for item in result.probabilities],
            "portfolio": asdict(result.portfolio),
            "risk": asdict(result.risk),
            "decisions": [asdict(item) for item in result.final_decisions],
            "blockers": result.blockers,
            "warnings": result.warnings,
        }
    )


def build_stage_evidence_chain(result: DailyQuantResult) -> list[dict[str, object]]:
    """Create a sequential chain from the exact immutable stage outputs."""

    identity_hashes = result.provenance.get("identity_hashes", {})
    if not isinstance(identity_hashes, dict):
        identity_hashes = {}
    previous = fingerprint(
        {
            "run_id": result.run_id,
            "analysis_date": result.analysis_date,
            "trade_date": result.trade_date,
            "data_cutoff": result.data_cutoff,
            "runtime_config_hash": identity_hashes.get(
                "runtime_config_hash", result.config_hash
            ),
        }
    )
    chain: list[dict[str, object]] = []
    for stage in result.stages:
        relevant_model_hash = _stage_model_hash(stage.name, identity_hashes, result)
        input_hash = fingerprint(
            {
                "previous_stage_output_hash": previous,
                "runtime_config_hash": identity_hashes.get(
                    "runtime_config_hash", result.config_hash
                ),
                "relevant_model_hash": relevant_model_hash,
            }
        )
        output_hash = fingerprint(
            {
                "stage_name": stage.name,
                "stage_status": stage.status,
                "message": stage.message,
                "diagnostics": stage.metadata,
                "canonical_stage_output": _stage_output_payload(result, stage.name),
                "input_hash": input_hash,
            }
        )
        chain.append(
            {
                "stage_name": stage.name,
                "stage_status": stage.status.value,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "previous_stage_output_hash": previous,
                "runtime_config_hash": identity_hashes.get(
                    "runtime_config_hash", result.config_hash
                ),
                "relevant_model_hash": relevant_model_hash,
                "code_build_provenance": result.provenance.get(
                    "build_identifier", result.version
                ),
                "started_at": result.started_at.isoformat(),
                "completed_at": result.finished_at.isoformat(),
                "blockers": (
                    list(result.blockers)
                    if stage.status is StageStatus.FAIL_BLOCKING
                    else []
                ),
                "warnings": (
                    list(result.warnings)
                    if stage.status is StageStatus.PASS_DEGRADED
                    else []
                ),
                "artifact_reference": f"{stage.name.lower()}_manifest.json",
            }
        )
        previous = output_hash
    return chain


def _stage_output_payload(result: DailyQuantResult, stage_name: str) -> object:
    if stage_name == "CALENDAR":
        return {
            "analysis_date": result.analysis_date,
            "trade_date": result.trade_date,
            "market_session": result.market_session,
            "market_structure": result.market_structure,
        }
    if stage_name == "DATA":
        return {
            "data_health": [asdict(item) for item in result.data_health],
            "data_hash": result.provenance.get("data_hash", "UNAVAILABLE"),
        }
    if stage_name == "PIT":
        return {
            "data_cutoff": result.data_cutoff,
            "universe_count": result.provenance.get("universe_count", 0),
        }
    if stage_name == "FEATURE":
        return [
            {"symbol": item.symbol, "raw_values": item.raw_values}
            for item in result.factors
        ]
    if stage_name == "FACTOR":
        return [asdict(item) for item in result.factors]
    if stage_name == "SIGNAL":
        return [asdict(item) for item in result.candidates]
    if stage_name == "PROBABILITY":
        return [asdict(item) for item in result.probabilities]
    if stage_name == "PORTFOLIO":
        return asdict(result.portfolio)
    if stage_name == "RISK":
        return asdict(result.risk)
    if stage_name == "DECISION":
        return [asdict(item) for item in result.final_decisions]
    if stage_name == "EXECUTION":
        return asdict(result.execution_plan)
    if stage_name == "ETF_SLEEVE":
        return {
            "universe": result.etf_universe,
            "targets": list(result.etf_targets),
            "composition": result.etf_composition,
        }
    if stage_name == "AI_BRIEF":
        return {
            "brief_source": (
                result.ai_brief.get("source") if result.ai_brief else None
            ),
            "llm_status": (
                result.ai_brief.get("llm_status") if result.ai_brief else None
            ),
        }
    if stage_name == "PERSISTENCE":
        return {
            "classification": result.run_classification,
            "blockers": result.blockers,
            "warnings": result.warnings,
        }
    return "NOT_APPLICABLE"


def _stage_model_hash(
    stage_name: str, identity_hashes: dict[str, object], result: DailyQuantResult
) -> object:
    if stage_name in {"FACTOR", "SIGNAL", "PROBABILITY"}:
        return identity_hashes.get("strategy_parameter_hash", result.model_versions)
    if stage_name == "PORTFOLIO":
        return identity_hashes.get("portfolio_constraint_hash", "UNAVAILABLE")
    if stage_name == "RISK":
        return identity_hashes.get("risk_model_hash", "UNAVAILABLE")
    if stage_name in {"DECISION", "EXECUTION"}:
        return {
            "portfolio": identity_hashes.get("portfolio_constraint_hash", "UNAVAILABLE"),
            "risk": identity_hashes.get("risk_model_hash", "UNAVAILABLE"),
            "cost": identity_hashes.get("cost_model_hash", "UNAVAILABLE"),
            "approval": identity_hashes.get("model_approval_hash", "UNAVAILABLE"),
        }
    return identity_hashes.get(
        "data_version_hash", result.provenance.get("data_hash", "UNAVAILABLE")
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    return value


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_value(payload), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _factor_statistics(rows: tuple[FactorRow, ...]) -> dict[str, dict[str, float | int]]:
    names = sorted({name for row in rows for name in row.components})
    result: dict[str, dict[str, float | int]] = {}
    for name in names:
        values = [row.components[name] for row in rows if name in row.components]
        if not values:
            continue
        result[name] = {
            "N": len(values),
            "mean": statistics.fmean(values),
            "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "median": statistics.median(values),
            "max": max(values),
            "missing": len(rows) - len(values),
            "cross_sectional_rank_coverage": len(values) / len(rows) if rows else 0.0,
        }
    return result
