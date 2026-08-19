"""Restart-safe operations for real Agentic Forward Shadow validation.

This module is deliberately operational. It coordinates the already-existing
Quant production path, Agentic Shadow branch, immutable forward ledger and
promotion evaluator without changing any Quant, optimizer or risk semantics.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum, StrEnum
from hashlib import sha256
from pathlib import Path
from typing import cast

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal import __version__
from personal_alpha_terminal.agents.llm.factory import build_llm_provider
from personal_alpha_terminal.agents.llm.providers import LLMProvider, LLMProviderError
from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.application.daily_result import DailyQuantResult
from personal_alpha_terminal.application.forward_competition import (
    SUPPORTED_EVALUATION_HORIZONS as COMPETITION_EVALUATION_HORIZONS,
)
from personal_alpha_terminal.application.forward_competition import (
    ForwardCompetitionDecisionSet,
    ForwardCompetitionLedger,
    ForwardCompetitionOutcome,
    competition_dashboard,
)
from personal_alpha_terminal.application.forward_evidence import (
    HYBRID_COUNTERFACTUAL_TYPE,
    OUTCOME_TYPE,
    PREDICTION_TYPE,
    QUANT_COUNTERFACTUAL_TYPE,
    REAL_FORWARD_ORIGIN,
    AgenticForwardEvidenceLedger,
    HybridCounterfactualRecord,
    PromotionEvaluationRecord,
    QuantCounterfactualRecord,
    SemanticForwardOutcomeRecord,
    SemanticForwardPredictionRecord,
    evaluate_runtime_promotion,
)
from personal_alpha_terminal.automation.runner import DailyPipelineLock
from personal_alpha_terminal.core.build_metadata import current_build_metadata
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.models.intelligence import (
    IntelligenceEvent,
    IntelligenceResearchResult,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.research.portfolio_competition import (
    EvidenceClass,
    OutcomeRecord,
    OutcomeStatus,
    PortfolioVariant,
)
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar

SHADOW_RUN_STATE_TYPE = "AGENTIC_SHADOW_RUN_STATE"
SHADOW_PROVIDER_CACHE_TYPE = "AGENTIC_SHADOW_PROVIDER_RESPONSE"
OUTCOME_COLLECTION_STATUS_TYPE = "AGENTIC_OUTCOME_COLLECTION_STATUS"
FORWARD_SHADOW_SCHEMA_VERSION = "forward-shadow-operations-v1"
FORWARD_SHADOW_PROMPT_VERSION = "company-thesis-v2"
FORWARD_SHADOW_PROVIDER_STATUS_PATH = Path("var/llm/forward_shadow_status.json")


class ForwardShadowExitCode(IntEnum):
    SUCCESS = 0
    SUCCESS_DEGRADED_SHADOW = 10
    RETRYABLE_PROVIDER_FAILURE = 20
    NO_MATURE_OUTCOMES = 0
    BLOCKED_DATA = 30
    CONFIG_ERROR = 40
    INVARIANT_VIOLATION = 50


class ShadowRunState(StrEnum):
    CREATED = "CREATED"
    QUANT_COMPLETED = "QUANT_COMPLETED"
    EVENTS_RESOLVED = "EVENTS_RESOLVED"
    LLM_REQUESTED = "LLM_REQUESTED"
    LLM_COMPLETED = "LLM_COMPLETED"
    THESIS_VALIDATED = "THESIS_VALIDATED"
    SHADOW_COMPUTED = "SHADOW_COMPUTED"
    PREDICTION_PERSISTED = "PREDICTION_PERSISTED"
    COUNTERFACTUAL_PERSISTED = "COUNTERFACTUAL_PERSISTED"
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


_STATE_ORDER = {
    state: index
    for index, state in enumerate(
        (
            ShadowRunState.CREATED,
            ShadowRunState.QUANT_COMPLETED,
            ShadowRunState.EVENTS_RESOLVED,
            ShadowRunState.LLM_REQUESTED,
            ShadowRunState.LLM_COMPLETED,
            ShadowRunState.THESIS_VALIDATED,
            ShadowRunState.SHADOW_COMPUTED,
            ShadowRunState.PREDICTION_PERSISTED,
            ShadowRunState.COUNTERFACTUAL_PERSISTED,
            ShadowRunState.COMPLETE,
        )
    )
}
_TERMINAL_STATES = {ShadowRunState.COMPLETE, ShadowRunState.FAILED}


@dataclass(frozen=True, slots=True)
class ShadowRunIdentity:
    shadow_run_id: str
    session_id: str
    session_date: date
    decision_timestamp: datetime
    provider: str
    model: str
    code_sha: str


@dataclass(frozen=True, slots=True)
class ForwardShadowRunResult:
    identity: ShadowRunIdentity
    result: DailyQuantResult
    state: ShadowRunState
    provider_failure: str | None
    prediction_count: int
    counterfactual_count: int
    promotion: dict[str, object]
    exit_code: ForwardShadowExitCode


@dataclass(frozen=True, slots=True)
class OutcomeCollectionResult:
    scanned_predictions: int
    matured_pairs: int
    outcomes_appended: int
    pending_not_matured: int
    pending_data: int
    blocked_provenance: int
    duplicate_outcomes: int
    promotion: PromotionEvaluationRecord
    exit_code: ForwardShadowExitCode
    competition_decision_sets: int = 0
    competition_outcomes_appended: int = 0
    competition_pending_not_matured: int = 0
    competition_pending_data: int = 0
    competition_blocked_provenance: int = 0
    competition_duplicate_outcomes: int = 0


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    model: str
    configured: bool
    enabled: bool
    credential: str
    connectivity: str
    last_successful_connection: str | None
    last_failure: str | None
    checked_at: str | None
    latency_ms: int | None
    attempt_count: int = 0
    success_count: int = 0
    failure_counts: dict[str, int] | None = None
    origin: str = "CONNECTIVITY_TEST"
    eligible_for_forward_evidence: bool = False
    eligible_for_promotion: bool = False

    def document(self) -> dict[str, object]:
        return asdict(self)


class ForwardShadowRunLedger:
    """Append-only operational state transitions stored beside forward evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = IntelligenceRepository(session)

    def append(
        self,
        identity: ShadowRunIdentity,
        state: ShadowRunState,
        *,
        metadata: dict[str, object] | None = None,
        observed_at: datetime | None = None,
    ) -> bool:
        transitions = self.transitions(identity.shadow_run_id)
        existing_states = {item["state"] for item in transitions}
        if state.value in existing_states:
            return False
        terminal = existing_states.intersection(state.value for state in _TERMINAL_STATES)
        if terminal:
            raise ValueError("terminal Forward Shadow run cannot transition")
        progress = max(
            (
                _STATE_ORDER[ShadowRunState(str(item["state"]))]
                for item in transitions
                if str(item.get("state")) in {member.value for member in _STATE_ORDER}
            ),
            default=-1,
        )
        if state in _STATE_ORDER and _STATE_ORDER[state] < progress:
            raise ValueError("Forward Shadow run cannot transition backwards")
        safe_metadata = dict(metadata or {})
        _validate_safe_operational_payload(safe_metadata)
        timestamp = _aware(observed_at or datetime.now(UTC))
        payload: dict[str, object] = {
            "shadow_run_id": identity.shadow_run_id,
            "session_id": identity.session_id,
            "session_date": identity.session_date.isoformat(),
            "decision_timestamp": identity.decision_timestamp.isoformat(),
            "provider": identity.provider,
            "model": identity.model,
            "schema_version": FORWARD_SHADOW_SCHEMA_VERSION,
            "code_sha": identity.code_sha,
            "state": state.value,
            "observed_at": timestamp.isoformat(),
            "metadata": safe_metadata,
            "production_lambda": 0.0,
            "production_llm_authority": 0.0,
            "production_source": "QUANT_ONLY",
            "manual_confirmation": True,
        }
        result_id = _identity("shadow-state", identity.shadow_run_id, state.value)
        self.repository.add_result(
            result_id=result_id,
            result_type=SHADOW_RUN_STATE_TYPE,
            schema_version=FORWARD_SHADOW_SCHEMA_VERSION,
            model_version=identity.code_sha,
            prompt_version=FORWARD_SHADOW_PROMPT_VERSION,
            data_cutoff=timestamp,
            status=state.value,
            payload=payload,
        )
        self.session.flush()
        return True

    def transitions(self, shadow_run_id: str | None = None) -> tuple[dict[str, object], ...]:
        statement = select(IntelligenceResearchResult).where(
            IntelligenceResearchResult.result_type == SHADOW_RUN_STATE_TYPE
        )
        rows = self.session.scalars(
            statement.order_by(
                IntelligenceResearchResult.data_cutoff,
                IntelligenceResearchResult.result_id,
            )
        )
        payloads = tuple(dict(row.payload) for row in rows)
        if shadow_run_id is None:
            return payloads
        return tuple(
            payload
            for payload in payloads
            if payload.get("shadow_run_id") == shadow_run_id
        )

    def latest(self, shadow_run_id: str) -> dict[str, object] | None:
        transitions = self.transitions(shadow_run_id)
        if not transitions:
            return None
        return max(transitions, key=lambda item: str(item.get("observed_at", "")))

    def latest_incomplete(self) -> dict[str, object] | None:
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for transition in self.transitions():
            grouped[str(transition.get("shadow_run_id", ""))].append(transition)
        candidates: list[dict[str, object]] = []
        for run_id, transitions in grouped.items():
            if not run_id:
                continue
            latest = max(transitions, key=lambda item: str(item.get("observed_at", "")))
            if str(latest.get("state")) not in {
                ShadowRunState.COMPLETE.value,
                ShadowRunState.FAILED.value,
            }:
                candidates.append(latest)
        if not candidates:
            return None
        return max(candidates, key=lambda item: str(item.get("decision_timestamp", "")))


class PersistentShadowProvider:
    """Cache an exact provider response before downstream Shadow computation.

    The cache is operational reuse for one identical observation. It is never a
    prediction, outcome or promotion sample.
    """

    def __init__(
        self,
        provider: LLMProvider,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._provider = provider
        self._factory = session_factory
        self.name = provider.name
        self.model = provider.model

    def generate(self, request: LLMRequest) -> LLMResponse:
        request_hash = _llm_request_hash(self.name, self.model, request)
        result_id = _identity("provider-response", request_hash)
        with self._factory() as session:
            existing = session.scalar(
                select(IntelligenceResearchResult).where(
                    IntelligenceResearchResult.result_type == SHADOW_PROVIDER_CACHE_TYPE,
                    IntelligenceResearchResult.result_id == result_id,
                )
            )
            if existing is not None:
                return _cached_response(existing.payload)
        response = self._provider.generate(request)
        response_hash = sha256(response.content.encode("utf-8")).hexdigest()
        normalized = replace(
            response,
            request_hash=request_hash,
            response_hash=response_hash,
        )
        payload: dict[str, object] = {
            "origin": "FORWARD_SHADOW_INFERENCE",
            "eligible_for_forward_evidence": False,
            "eligible_for_promotion": False,
            "provider": normalized.provider,
            "model": normalized.model,
            "task_type": request.task_type,
            "prompt_version": request.prompt_version,
            "schema_version": FORWARD_SHADOW_SCHEMA_VERSION,
            "information_cutoff": (
                request.as_of.isoformat() if request.as_of is not None else None
            ),
            "input_document_ids": list(request.input_document_ids),
            "request_hash": request_hash,
            "response_hash": response_hash,
            "content": normalized.content,
            "provider_request_id": normalized.request_id,
            "prompt_tokens": normalized.prompt_tokens,
            "completion_tokens": normalized.completion_tokens,
            "cached_tokens": normalized.cached_tokens,
            "latency_ms": normalized.latency_ms,
            "retry_count": normalized.retry_count,
            "validation_status": normalized.validation_status,
            "estimated_cost_usd": normalized.estimated_cost_usd,
        }
        _validate_safe_operational_payload(payload)
        cutoff = _aware(request.as_of or datetime.now(UTC))
        with session_scope(self._factory) as session:
            IntelligenceRepository(session).add_result(
                result_id=result_id,
                result_type=SHADOW_PROVIDER_CACHE_TYPE,
                schema_version=FORWARD_SHADOW_SCHEMA_VERSION,
                model_version=self.model,
                prompt_version=request.prompt_version,
                data_cutoff=cutoff,
                status="RESPONSE_RECEIVED",
                payload=payload,
            )
        return normalized


class ForwardShadowOperations:
    """Operator service for daily Shadow, resume, outcomes and evidence status."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        effective_config: EffectiveRuntimeConfig,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = session_factory
        self._config = effective_config
        self._settings = effective_config.settings
        self._now = now
        self._calendar = MarketSessionCalendar(
            nasdaq_23h_enabled=effective_config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=effective_config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
            allow_deterministic_fallback=effective_config.allow_calendar_fallback,
        )

    def validate_runtime(self) -> None:
        settings = self._settings
        if settings.runtime_profile != "FORWARD_SHADOW_VALIDATION":
            raise ValueError(
                "Forward Shadow requires PAT_RUNTIME_PROFILE=FORWARD_SHADOW_VALIDATION"
            )
        if not settings.agentic_shadow_external_enabled:
            raise ValueError(
                "Forward Shadow external provider requires "
                "PAT_AGENTIC_SHADOW_EXTERNAL_ENABLED=true"
            )
        if settings.llm_provider in {"auto", "mock", "disabled"}:
            raise ValueError("Forward Shadow requires an explicit external provider")
        provider = build_llm_provider(settings)
        if provider.name == "disabled":
            raise ValueError("Forward Shadow provider credential is unavailable")

    def identity(
        self,
        *,
        decision_time: datetime | None = None,
    ) -> ShadowRunIdentity:
        timestamp = _aware(decision_time or self._now())
        session_date = self._calendar.completed_session_date(timestamp)
        provider, model, _, _ = _provider_configuration(self._settings)
        portfolio = str(self._config.portfolio_id or "NO_PORTFOLIO")
        session_digest = sha256(
            f"{session_date.isoformat()}|{portfolio}|US_EQUITY_FORWARD_SHADOW".encode()
        ).hexdigest()
        session_id = f"shadow-session-{session_date.isoformat()}-{session_digest[:12]}"
        shadow_run_id = f"daily-shadow-{session_date.isoformat()}-{session_digest[:12]}"
        return ShadowRunIdentity(
            shadow_run_id=shadow_run_id,
            session_id=session_id,
            session_date=session_date,
            decision_timestamp=timestamp,
            provider=provider,
            model=model,
            code_sha=current_build_metadata().git_commit,
        )

    def run_daily(
        self,
        *,
        decision_time: datetime | None = None,
        refresh: bool = True,
        progress: Callable[[str], None] | None = None,
        identity: ShadowRunIdentity | None = None,
    ) -> ForwardShadowRunResult:
        self.validate_runtime()
        run_identity = identity or self.identity(decision_time=decision_time)
        if decision_time is not None and _aware(decision_time) != run_identity.decision_timestamp:
            raise ValueError("resume decision timestamp does not match durable run identity")
        lock = DailyPipelineLock(
            self._settings.forward_shadow_lock_path,
            stale_after=timedelta(hours=self._settings.forward_shadow_lock_stale_hours),
            now=self._now,
        )
        with lock:
            with session_scope(self._factory) as session:
                ForwardShadowRunLedger(session).append(
                    run_identity,
                    ShadowRunState.CREATED,
                    metadata={"refresh": refresh},
                    observed_at=self._now(),
                )

            active_provider = PersistentShadowProvider(
                build_llm_provider(self._settings),
                self._factory,
            )

            def checkpoint(state: str, metadata: dict[str, object]) -> None:
                parsed = ShadowRunState(state)
                with session_scope(self._factory) as session:
                    ForwardShadowRunLedger(session).append(
                        run_identity,
                        parsed,
                        metadata=metadata,
                        observed_at=self._now(),
                    )

            try:
                result = ApplicationService(
                    self._factory,
                    self._settings,
                    snapshot_root=self._config.report_dir,
                    effective_config=self._config,
                ).run_daily_quant_report(
                    portfolio_id=self._config.portfolio_id,
                    decision_time=run_identity.decision_timestamp,
                    refresh=refresh,
                    progress=progress,
                    run_id=run_identity.shadow_run_id,
                    shadow_llm_provider_factory=lambda: active_provider,
                    shadow_checkpoint_callback=checkpoint,
                )
            except Exception:
                with session_scope(self._factory) as session:
                    ForwardShadowRunLedger(session).append(
                        run_identity,
                        ShadowRunState.FAILED,
                        metadata={"reason": "DAILY_ORCHESTRATOR_FAILURE"},
                        observed_at=self._now(),
                    )
                raise

            hybrid = result.hybrid_intelligence or {}
            persistence = _dict(hybrid.get("forward_evidence_persistence"))
            promotion = _dict(hybrid.get("promotion"))
            status = _dict(hybrid.get("status"))
            degradation = _dict(hybrid.get("degradation"))
            provider_failure = _provider_failure_from_document(hybrid)
            prediction_count = _nonnegative_integer(persistence.get("predictions"))
            counterfactual_count = _nonnegative_integer(
                persistence.get("counterfactuals")
            )
            production_lambda = _finite_number(promotion.get("production_lambda"))
            counts_valid = prediction_count is not None and counterfactual_count is not None
            predictions = prediction_count if prediction_count is not None else 0
            counterfactuals = counterfactual_count if counterfactual_count is not None else 0
            complete = (
                result.data_cutoff is not None
                and not persistence.get("error")
                and counts_valid
                and status.get("production_influence") in {False, "0%", None}
                and production_lambda == 0.0
            )
            final_state = (
                ShadowRunState.COMPLETE
                if complete and not degradation and provider_failure is None
                else ShadowRunState.DEGRADED
            )
            with session_scope(self._factory) as session:
                ForwardShadowRunLedger(session).append(
                    run_identity,
                    final_state,
                    metadata={
                        "prediction_count": predictions,
                        "counterfactual_count": counterfactuals,
                        "provider_failure": provider_failure,
                        "quant_action_hash": fingerprint(
                            [asdict(action) for action in result.final_decisions]
                        ),
                        "production_lambda": 0.0,
                    },
                    observed_at=self._now(),
                )
            exit_code = (
                ForwardShadowExitCode.SUCCESS
                if final_state is ShadowRunState.COMPLETE
                else ForwardShadowExitCode.RETRYABLE_PROVIDER_FAILURE
                if provider_failure
                else ForwardShadowExitCode.SUCCESS_DEGRADED_SHADOW
            )
            return ForwardShadowRunResult(
                identity=run_identity,
                result=result,
                state=final_state,
                provider_failure=provider_failure,
                prediction_count=predictions,
                counterfactual_count=counterfactuals,
                promotion=promotion,
                exit_code=exit_code,
            )

    def resume(
        self,
        *,
        shadow_run_id: str | None = None,
        refresh: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> ForwardShadowRunResult | None:
        with self._factory() as session:
            ledger = ForwardShadowRunLedger(session)
            latest = (
                ledger.latest(shadow_run_id)
                if shadow_run_id is not None
                else ledger.latest_incomplete()
            )
        if latest is None:
            return None
        latest_state = ShadowRunState(str(latest["state"]))
        if latest_state is ShadowRunState.COMPLETE:
            return None
        stored_sha = str(latest.get("code_sha", "UNAVAILABLE"))
        current_sha = current_build_metadata().git_commit
        if stored_sha != current_sha:
            raise ValueError("BLOCK_REQUIRES_NEW_RUN: code SHA changed since checkpoint")
        provider, model, _, _ = _provider_configuration(self._settings)
        if provider != str(latest.get("provider")) or model != str(latest.get("model")):
            raise ValueError("BLOCK_REQUIRES_NEW_RUN: provider/model provenance changed")
        identity = ShadowRunIdentity(
            shadow_run_id=str(latest["shadow_run_id"]),
            session_id=str(latest["session_id"]),
            session_date=date.fromisoformat(str(latest["session_date"])),
            decision_timestamp=_parse_aware(str(latest["decision_timestamp"])),
            provider=provider,
            model=model,
            code_sha=current_sha,
        )
        return self.run_daily(
            decision_time=identity.decision_timestamp,
            refresh=refresh,
            progress=progress,
            identity=identity,
        )

    def collect_outcomes(
        self,
        *,
        collected_at: datetime | None = None,
    ) -> OutcomeCollectionResult:
        timestamp = _aware(collected_at or self._now())
        lock = DailyPipelineLock(
            self._settings.forward_outcome_lock_path,
            stale_after=timedelta(hours=self._settings.forward_shadow_lock_stale_hours),
            now=self._now,
        )
        with lock, session_scope(self._factory) as session:
            result = _collect_matured_outcomes(
                session,
                config=self._config,
                calendar=self._calendar,
                collected_at=timestamp,
            )
        return result

    def dashboard(self, *, evaluated_at: datetime | None = None) -> dict[str, object]:
        timestamp = _aware(evaluated_at or self._now())
        with self._factory() as session:
            return build_forward_shadow_dashboard(
                session,
                settings=self._settings,
                evaluated_at=timestamp,
            )

    def doctor(self, *, checked_at: datetime | None = None) -> dict[str, object]:
        timestamp = _aware(checked_at or self._now())
        checks: list[dict[str, object]] = []
        try:
            self.validate_runtime()
            checks.append({"name": "runtime_profile", "status": "PASS"})
        except ValueError as error:
            checks.append(
                {"name": "runtime_profile", "status": "FAIL", "detail": str(error)}
            )
        provider = probe_forward_shadow_provider(self._settings, live=False)
        checks.append(
            {
                "name": "provider_configured",
                "status": "PASS" if provider.configured and provider.enabled else "FAIL",
                "detail": provider.document(),
            }
        )
        try:
            with self._factory() as session:
                session.execute(text("SELECT 1"))
                nested = session.begin_nested()
                IntelligenceRepository(session).add_result(
                    result_id=_identity("forward-shadow-doctor", timestamp.isoformat()),
                    result_type="FORWARD_SHADOW_DOCTOR_PROBE",
                    schema_version=FORWARD_SHADOW_SCHEMA_VERSION,
                    model_version=__version__,
                    prompt_version="not-applicable",
                    data_cutoff=timestamp,
                    status="ROLLBACK_PROBE",
                    payload={
                        "origin": "CONNECTIVITY_TEST",
                        "eligible_for_forward_evidence": False,
                        "eligible_for_promotion": False,
                    },
                )
                session.flush()
                nested.rollback()
                checks.append({"name": "database_writable", "status": "PASS"})
                price_count = int(
                    session.scalar(select(func.count()).select_from(Price)) or 0
                )
                checks.append(
                    {
                        "name": "market_data_available",
                        "status": "PASS" if price_count > 0 else "FAIL",
                        "count": price_count,
                    }
                )
                event_count = int(
                    session.scalar(select(func.count()).select_from(IntelligenceEvent)) or 0
                )
                checks.append(
                    {
                        "name": "event_repository_ready",
                        "status": "PASS",
                        "count": event_count,
                    }
                )
                session.scalar(
                    select(func.count()).select_from(IntelligenceResearchResult)
                )
                checks.append({"name": "forward_ledger_schema", "status": "PASS"})
                promotion = evaluate_runtime_promotion(
                    AgenticForwardEvidenceLedger(session),
                    evaluated_at=timestamp,
                    evaluation_id=_identity("doctor-promotion", timestamp.isoformat()),
                )
                checks.append(
                    {
                        "name": "promotion_evaluator",
                        "status": "PASS",
                        "reason": promotion.promotion_reason,
                    }
                )
        except Exception as error:  # noqa: BLE001 - doctor reports the boundary
            checks.append(
                {
                    "name": "database_and_ledgers",
                    "status": "FAIL",
                    "detail": type(error).__name__,
                }
            )
        try:
            completed = self._calendar.completed_session_date(timestamp)
            self._calendar.advance_trading_sessions(completed, 1)
            checks.append({"name": "outcome_calendar", "status": "PASS"})
        except (ImportError, RuntimeError, TypeError, ValueError) as error:
            checks.append(
                {
                    "name": "outcome_calendar",
                    "status": "FAIL",
                    "detail": type(error).__name__,
                }
            )
        checks.append(
            {
                "name": "production_authority",
                "status": "PASS",
                "production_lambda": 0.0,
                "production_llm_authority": "0%",
                "production_source": "QUANT_ONLY",
                "manual_confirmation": True,
            }
        )
        return {
            "status": (
                "PASS" if all(item.get("status") == "PASS" for item in checks) else "FAIL"
            ),
            "checked_at": timestamp.isoformat(),
            "checks": checks,
        }

    def reconcile(self, *, evaluated_at: datetime | None = None) -> dict[str, object]:
        timestamp = _aware(evaluated_at or self._now())
        with self._factory() as session:
            return reconcile_forward_shadow_evidence(session, evaluated_at=timestamp)


def probe_forward_shadow_provider(
    settings: Settings,
    *,
    live: bool,
    status_path: Path = FORWARD_SHADOW_PROVIDER_STATUS_PATH,
    provider: LLMProvider | None = None,
    now: datetime | None = None,
) -> ProviderHealth:
    checked_at = _aware(now or datetime.now(UTC))
    selected, model, _endpoint, credential = _provider_configuration(settings)
    enabled = bool(
        settings.runtime_profile == "FORWARD_SHADOW_VALIDATION"
        and settings.agentic_shadow_external_enabled
    )
    configured = selected not in {"auto", "mock", "disabled"} and credential == "PRESENT"
    previous = _load_provider_health(status_path)
    if not live:
        if previous is not None and previous.provider == selected and previous.model == model:
            return replace(previous, configured=configured, enabled=enabled)
        return ProviderHealth(
            provider=selected,
            model=model,
            configured=configured,
            enabled=enabled,
            credential=credential,
            connectivity="NOT_TESTED" if configured else "DISABLED_OR_UNCONFIGURED",
            last_successful_connection=None,
            last_failure=None,
            checked_at=None,
            latency_ms=None,
        )
    if not enabled or not configured:
        health = ProviderHealth(
            provider=selected,
            model=model,
            configured=configured,
            enabled=enabled,
            credential=credential,
            connectivity="CONFIG_ERROR",
            last_successful_connection=(
                previous.last_successful_connection if previous is not None else None
            ),
            last_failure="EXPLICIT_ENABLEMENT_OR_CREDENTIAL_MISSING",
            checked_at=checked_at.isoformat(),
            latency_ms=None,
        )
        _write_provider_health(status_path, health)
        return health
    active = provider or build_llm_provider(settings)
    request = LLMRequest(
        system_prompt=(
            "Return only the requested JSON object. This is a connectivity test, "
            "not investment research."
        ),
        user_prompt=(
            'Return exactly {"status":"ok","schema_version":'
            '"forward-shadow-provider-doctor-v1"}. '
            "This call has origin CONNECTIVITY_TEST and is not Forward evidence."
        ),
        temperature=0.0,
        task_type="CONNECTIVITY_TEST",
        prompt_version="forward-shadow-provider-doctor-v1",
        as_of=checked_at,
        max_tokens=96,
        thinking="disabled",
    )
    try:
        response = active.generate(request)
        payload = json.loads(response.content)
        expected = {
            "status": "ok",
            "schema_version": "forward-shadow-provider-doctor-v1",
        }
        if payload != expected:
            raise ValueError("structured connectivity response does not match schema")
        health = ProviderHealth(
            provider=active.name,
            model=active.model,
            configured=True,
            enabled=True,
            credential="PRESENT",
            connectivity="AVAILABLE",
            last_successful_connection=checked_at.isoformat(),
            last_failure=None,
            checked_at=checked_at.isoformat(),
            latency_ms=response.latency_ms,
            attempt_count=(previous.attempt_count if previous is not None else 0) + 1,
            success_count=(previous.success_count if previous is not None else 0) + 1,
            failure_counts=(previous.failure_counts if previous is not None else {}),
        )
    except LLMProviderError as error:
        failure = _normalize_provider_failure(error.category)
        health = ProviderHealth(
            provider=selected,
            model=model,
            configured=True,
            enabled=True,
            credential="PRESENT",
            connectivity="UNAVAILABLE",
            last_successful_connection=(
                previous.last_successful_connection if previous is not None else None
            ),
            last_failure=failure,
            checked_at=checked_at.isoformat(),
            latency_ms=None,
            attempt_count=(previous.attempt_count if previous is not None else 0) + 1,
            success_count=previous.success_count if previous is not None else 0,
            failure_counts=_increment_failure(previous, failure),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        failure = "MALFORMED_OUTPUT"
        health = ProviderHealth(
            provider=selected,
            model=model,
            configured=True,
            enabled=True,
            credential="PRESENT",
            connectivity="UNAVAILABLE",
            last_successful_connection=(
                previous.last_successful_connection if previous is not None else None
            ),
            last_failure=failure,
            checked_at=checked_at.isoformat(),
            latency_ms=None,
            attempt_count=(previous.attempt_count if previous is not None else 0) + 1,
            success_count=previous.success_count if previous is not None else 0,
            failure_counts=_increment_failure(previous, failure),
        )
    _write_provider_health(status_path, health)
    return health


def build_forward_shadow_dashboard(
    session: Session,
    *,
    settings: Settings,
    evaluated_at: datetime,
) -> dict[str, object]:
    ledger = AgenticForwardEvidenceLedger(session)
    competition = competition_dashboard(ForwardCompetitionLedger(session))
    predictions = ledger.records(PREDICTION_TYPE)
    outcomes = ledger.records(OUTCOME_TYPE)
    quant = ledger.records(QUANT_COUNTERFACTUAL_TYPE)
    hybrid = ledger.records(HYBRID_COUNTERFACTUAL_TYPE)
    promotion = evaluate_runtime_promotion(
        ledger,
        evaluated_at=evaluated_at,
        evaluation_id=_identity("promotion-dashboard", evaluated_at.isoformat()),
    )
    run_transitions = ForwardShadowRunLedger(session).transitions()
    latest_run = max(
        run_transitions,
        key=lambda item: str(item.get("observed_at", "")),
        default=None,
    )
    real_predictions = [
        row for row in predictions if row.get("evidence_origin") == REAL_FORWARD_ORIGIN
    ]
    outcome_horizons = Counter(str(row.get("evaluation_horizon")) for row in outcomes)
    statuses = _outcome_statuses(session)
    resolved_outcomes = {
        (
            str(row.get("counterfactual_observation_id", "")),
            str(row.get("evaluation_horizon", "")),
        )
        for row in outcomes
    }
    pending = sum(
        1
        for row in statuses
        if (
            str(row.get("observation_id", "")),
            str(row.get("evaluation_horizon", "")),
        )
        not in resolved_outcomes
        if row.get("status") in {"OUTCOME_NOT_MATURED", "OUTCOME_PENDING_DATA"}
    )
    blocked = sum(
        1
        for row in statuses
        if (
            str(row.get("observation_id", "")),
            str(row.get("evaluation_horizon", "")),
        )
        not in resolved_outcomes
        if row.get("status") == "OUTCOME_BLOCKED_PROVENANCE"
    )
    inferences = [
        row
        for row in predictions
        if row.get("llm_inference_status") not in {None, "UNAVAILABLE"}
    ]
    valid_inferences = [
        row for row in inferences if row.get("llm_inference_status") == "VALID"
    ]
    provider_health = probe_forward_shadow_provider(settings, live=False)
    provider_cache_rows = tuple(
        dict(row.payload)
        for row in session.scalars(
            select(IntelligenceResearchResult).where(
                IntelligenceResearchResult.result_type == SHADOW_PROVIDER_CACHE_TYPE
            )
        )
    )
    provider_costs = [
        value
        for row in provider_cache_rows
        if (value := _finite_number(row.get("estimated_cost_usd"))) is not None
        and value > 0
    ]
    reconciliation = reconcile_forward_shadow_evidence(
        session,
        evaluated_at=evaluated_at,
    )
    evidence_available = promotion.paired_sample_n > 0
    return {
        "provider_health": {
            **provider_health.document(),
            "structured_response_success_rate": (
                len(valid_inferences) / len(inferences) if inferences else None
            ),
            "request_count": len(provider_cache_rows),
            "input_tokens": sum(
                _nonnegative_integer(row.get("prompt_tokens")) or 0
                for row in provider_cache_rows
            ),
            "output_tokens": sum(
                _nonnegative_integer(row.get("completion_tokens")) or 0
                for row in provider_cache_rows
            ),
            "retry_count": sum(
                _nonnegative_integer(row.get("retry_count")) or 0
                for row in provider_cache_rows
            ),
            "average_latency_ms": (
                sum(
                    _nonnegative_integer(row.get("latency_ms")) or 0
                    for row in provider_cache_rows
                )
                / len(provider_cache_rows)
                if provider_cache_rows
                else None
            ),
            "provider_reported_cost_usd": sum(provider_costs) if provider_costs else None,
        },
        "daily_shadow_status": {
            "last_run": latest_run,
            "all_transition_count": len(run_transitions),
            "quant_production_source": "QUANT_ONLY",
        },
        "forward_evidence": {
            "total_predictions": len(predictions),
            "real_predictions": len(real_predictions),
            "matured_1d": outcome_horizons["1d"],
            "matured_5d": outcome_horizons["5d"],
            "matured_10d": outcome_horizons["10d"],
            "matured_20d": outcome_horizons["20d"],
            "pending_outcomes": pending,
            "blocked_outcomes": blocked,
            "valid_paired_observations": promotion.paired_sample_n,
            "independent_sessions": promotion.unique_session_n,
            "quant_counterfactuals": len(quant),
            "hybrid_counterfactuals": len(hybrid),
            "competition_complete_paired_sets": competition["complete_paired_sets"],
            "competition_independent_sessions": competition["independent_sessions"],
            "competition_promotion_eligible_sets": competition[
                "promotion_eligible_paired_sets"
            ],
        },
        "forward_competition": competition,
        "promotion_evidence": {
            "status": promotion.status,
            "promotion_reason": promotion.promotion_reason,
            "real_forward_n": promotion.real_forward_n,
            "minimum_required_n": promotion.minimum_required_n,
            "independent_sessions": promotion.unique_session_n,
            "minimum_sessions": promotion.minimum_unique_session_n,
            "mean_incremental_net_alpha": (
                promotion.incremental_alpha if evidence_available else None
            ),
            "median_incremental_net_alpha": (
                promotion.median_incremental_alpha if evidence_available else None
            ),
            "confidence_interval": (
                promotion.confidence_interval if evidence_available else None
            ),
            "lower_confidence_bound": (
                promotion.confidence_interval[0]
                if evidence_available and promotion.confidence_interval is not None
                else None
            ),
            "hit_rate": promotion.hit_rate if evidence_available else None,
            "cost_delta": promotion.cost_delta if evidence_available else None,
            "turnover_delta": promotion.turnover_delta if evidence_available else None,
            "drawdown_delta": promotion.drawdown_delta if evidence_available else None,
            "calibration": promotion.calibration_status,
            "regime_coverage": promotion.regime_coverage,
            "excluded_evidence_count": (
                promotion.contaminated_n + promotion.unpaired_n
            ),
            "excluded_reason_counts": reconciliation["excluded_reason_counts"],
        },
        "authority": {
            "production_llm_authority": "0%",
            "production_lambda": 0.0,
            "production_source": "QUANT_ONLY",
            "execution": "MANUAL_CONFIRMATION",
        },
    }


def reconcile_forward_shadow_evidence(
    session: Session,
    *,
    evaluated_at: datetime,
) -> dict[str, object]:
    ledger = AgenticForwardEvidenceLedger(session)
    prediction_rows = ledger.records(PREDICTION_TYPE)
    outcome_rows = ledger.records(OUTCOME_TYPE)
    quant_rows = ledger.records(QUANT_COUNTERFACTUAL_TYPE)
    hybrid_rows = ledger.records(HYBRID_COUNTERFACTUAL_TYPE)
    reasons: Counter[str] = Counter()
    predictions: dict[str, SemanticForwardPredictionRecord] = {}
    logical_predictions: Counter[str] = Counter()
    for row in prediction_rows:
        try:
            prediction = SemanticForwardPredictionRecord.model_validate(row)
        except ValueError:
            reasons["INCOMPLETE_PROVENANCE"] += 1
            continue
        predictions[prediction.prediction_id] = prediction
        logical_predictions[prediction.observation_id] += 1
        if prediction.evidence_origin != REAL_FORWARD_ORIGIN:
            reasons[f"ORIGIN_{prediction.evidence_origin}"] += 1
        if prediction.decision_timestamp > evaluated_at:
            reasons["FUTURE_OBSERVATION"] += 1
    duplicate_predictions = sum(count - 1 for count in logical_predictions.values() if count > 1)
    if duplicate_predictions:
        reasons["DUPLICATE"] += duplicate_predictions

    quant_pairs = _counterfactual_map(quant_rows, QuantCounterfactualRecord, reasons)
    hybrid_pairs = _counterfactual_map(hybrid_rows, HybridCounterfactualRecord, reasons)
    missing_pairs = len(set(quant_pairs) ^ set(hybrid_pairs))
    if missing_pairs:
        reasons["MISSING_PAIR"] += missing_pairs

    outcome_keys: Counter[tuple[str, str]] = Counter()
    orphan_outcomes = 0
    for row in outcome_rows:
        try:
            outcome = SemanticForwardOutcomeRecord.model_validate(row)
        except ValueError:
            reasons["INCOMPLETE_PROVENANCE"] += 1
            continue
        outcome_keys[(outcome.prediction_id, outcome.evaluation_horizon)] += 1
        if outcome.prediction_id not in predictions:
            orphan_outcomes += 1
            reasons["PREDICTION_ABSENT"] += 1
        if outcome.evidence_origin != REAL_FORWARD_ORIGIN:
            reasons[f"ORIGIN_{outcome.evidence_origin}"] += 1
        if outcome.outcome_timestamp > evaluated_at:
            reasons["FUTURE_OBSERVATION"] += 1
        pair_key = (outcome.counterfactual_observation_id, outcome.evaluation_horizon)
        if pair_key not in quant_pairs or pair_key not in hybrid_pairs:
            reasons["MISSING_PAIR"] += 1
        elif quant_pairs[pair_key].data_version != hybrid_pairs[pair_key].data_version:
            reasons["DATA_VERSION_MISMATCH"] += 1
    duplicate_outcomes = sum(count - 1 for count in outcome_keys.values() if count > 1)
    if duplicate_outcomes:
        reasons["DUPLICATE"] += duplicate_outcomes

    model_versions = {
        (
            prediction.llm_provider,
            prediction.llm_model,
            prediction.llm_schema_version,
            prediction.prompt_version,
            prediction.code_model_version,
        )
        for prediction in predictions.values()
        if prediction.evidence_origin == REAL_FORWARD_ORIGIN
    }
    if len(model_versions) > 1:
        reasons["MODEL_VERSION_INCONSISTENT"] += len(model_versions)
    return {
        "prediction_count": len(prediction_rows),
        "outcome_count": len(outcome_rows),
        "quant_counterfactual_count": len(quant_rows),
        "hybrid_counterfactual_count": len(hybrid_rows),
        "orphan_outcomes": orphan_outcomes,
        "duplicate_logical_predictions": duplicate_predictions,
        "duplicate_outcomes": duplicate_outcomes,
        "missing_pairs": missing_pairs,
        "invalid_origin_count": sum(
            count for reason, count in reasons.items() if reason.startswith("ORIGIN_")
        ),
        "future_timestamp_count": reasons["FUTURE_OBSERVATION"],
        "model_version_count": len(model_versions),
        "excluded_reason_counts": dict(sorted(reasons.items())),
        "read_only": True,
    }


def _collect_matured_outcomes(
    session: Session,
    *,
    config: EffectiveRuntimeConfig,
    calendar: MarketSessionCalendar,
    collected_at: datetime,
) -> OutcomeCollectionResult:
    ledger = AgenticForwardEvidenceLedger(session)
    prediction_rows = ledger.records(PREDICTION_TYPE)
    quant_rows = ledger.records(QUANT_COUNTERFACTUAL_TYPE)
    hybrid_rows = ledger.records(HYBRID_COUNTERFACTUAL_TYPE)
    predictions: dict[str, SemanticForwardPredictionRecord] = {}
    by_observation: dict[str, list[SemanticForwardPredictionRecord]] = defaultdict(list)
    for row in prediction_rows:
        try:
            prediction = SemanticForwardPredictionRecord.model_validate(row)
        except ValueError:
            continue
        if (
            prediction.evidence_origin != REAL_FORWARD_ORIGIN
            or prediction.status != "SHADOW"
            or prediction.structured_thesis is None
        ):
            continue
        predictions[prediction.prediction_id] = prediction
        by_observation[prediction.counterfactual_observation_id].append(prediction)
    reasons: Counter[str] = Counter()
    quant_pairs = _counterfactual_map(quant_rows, QuantCounterfactualRecord, reasons)
    hybrid_pairs = _counterfactual_map(hybrid_rows, HybridCounterfactualRecord, reasons)
    matured_pairs = 0
    outcomes_appended = 0
    duplicates = 0
    for pair_key in sorted(set(quant_pairs) & set(hybrid_pairs)):
        observation_id, horizon = pair_key
        observation_predictions = sorted(
            by_observation.get(observation_id, []),
            key=lambda item: item.security_id,
        )
        if not observation_predictions:
            continue
        quant = cast(QuantCounterfactualRecord, quant_pairs[pair_key])
        hybrid = cast(HybridCounterfactualRecord, hybrid_pairs[pair_key])
        if not _exact_counterfactual_pair(quant, hybrid):
            _append_outcome_status(
                session,
                observation_id=observation_id,
                horizon=horizon,
                status="OUTCOME_BLOCKED_PROVENANCE",
                reason="COUNTERFACTUAL_PAIR_MISMATCH",
                observed_at=collected_at,
            )
            reasons["OUTCOME_BLOCKED_PROVENANCE"] += 1
            continue
        base_session = calendar.completed_session_date(quant.information_cutoff)
        horizon_sessions = int(horizon.removesuffix("d"))
        exit_session = calendar.advance_trading_sessions(base_session, horizon_sessions)
        outcome_timestamp = calendar.market_close_utc(exit_session)
        if collected_at < outcome_timestamp:
            _append_outcome_status(
                session,
                observation_id=observation_id,
                horizon=horizon,
                status="OUTCOME_NOT_MATURED",
                reason=f"MATURITY_SESSION:{exit_session.isoformat()}",
                observed_at=collected_at,
            )
            reasons["OUTCOME_NOT_MATURED"] += 1
            continue
        matured_pairs += 1
        try:
            economics = _portfolio_outcome_economics(
                session,
                config=config,
                calendar=calendar,
                quant=quant,
                hybrid=hybrid,
                base_session=base_session,
                exit_session=exit_session,
                collected_at=collected_at,
            )
        except OutcomePendingData as error:
            _append_outcome_status(
                session,
                observation_id=observation_id,
                horizon=horizon,
                status="OUTCOME_PENDING_DATA",
                reason=str(error),
                observed_at=collected_at,
            )
            reasons["OUTCOME_PENDING_DATA"] += 1
            continue
        except OutcomeBlockedProvenance as error:
            _append_outcome_status(
                session,
                observation_id=observation_id,
                horizon=horizon,
                status="OUTCOME_BLOCKED_PROVENANCE",
                reason=str(error),
                observed_at=collected_at,
            )
            reasons["OUTCOME_BLOCKED_PROVENANCE"] += 1
            continue
        for prediction in observation_predictions:
            outcome = SemanticForwardOutcomeRecord(
                outcome_id=_identity("forward-outcome", prediction.prediction_id, horizon),
                prediction_id=prediction.prediction_id,
                observation_id=prediction.observation_id,
                counterfactual_observation_id=observation_id,
                decision_timestamp=prediction.decision_timestamp,
                information_cutoff=prediction.information_cutoff,
                outcome_timestamp=outcome_timestamp,
                evaluation_horizon=horizon,
                security_id=prediction.security_id,
                symbol_as_of_time=prediction.symbol_as_of_time,
                universe_identity=quant.universe_identity,
                execution_assumptions_hash=quant.execution_assumptions_hash,
                transaction_cost_model=quant.transaction_cost_model,
                slippage_model=quant.slippage_model,
                benchmark_convention=quant.benchmark_convention,
                data_version=quant.data_version,
                quant_net_return=economics["quant_net_return"],
                hybrid_net_return=economics["hybrid_net_return"],
                benchmark_return=economics["benchmark_return"],
                quant_cost=economics["quant_cost"],
                hybrid_cost=economics["hybrid_cost"],
                quant_turnover=economics["quant_turnover"],
                hybrid_turnover=economics["hybrid_turnover"],
                quant_drawdown=economics["quant_drawdown"],
                hybrid_drawdown=economics["hybrid_drawdown"],
                data_snapshot_identity=cast(
                    dict[str, str], economics["data_snapshot_identity"]
                ),
                source_identity=str(economics["source_identity"]),
                regime=_prediction_regime(observation_predictions),
                evidence_origin=REAL_FORWARD_ORIGIN,
            )
            if ledger.append_outcome(outcome):
                outcomes_appended += 1
            else:
                duplicates += 1
    promotion = evaluate_runtime_promotion(
        ledger,
        evaluated_at=collected_at,
        evaluation_id=_identity(
            "promotion-collection",
            collected_at.isoformat(),
            str(outcomes_appended),
            str(len(predictions)),
        ),
    )
    ledger.append_promotion_evaluation(promotion)
    competition = _collect_matured_competition_outcomes(
        session,
        config=config,
        calendar=calendar,
        collected_at=collected_at,
    )
    return OutcomeCollectionResult(
        scanned_predictions=len(predictions),
        matured_pairs=matured_pairs,
        outcomes_appended=outcomes_appended,
        pending_not_matured=reasons["OUTCOME_NOT_MATURED"],
        pending_data=reasons["OUTCOME_PENDING_DATA"],
        blocked_provenance=reasons["OUTCOME_BLOCKED_PROVENANCE"],
        duplicate_outcomes=duplicates,
        promotion=promotion,
        competition_decision_sets=competition["decision_sets"],
        competition_outcomes_appended=competition["outcomes_appended"],
        competition_pending_not_matured=competition["pending_not_matured"],
        competition_pending_data=competition["pending_data"],
        competition_blocked_provenance=competition["blocked_provenance"],
        competition_duplicate_outcomes=competition["duplicate_outcomes"],
        exit_code=(
            ForwardShadowExitCode.SUCCESS
            if outcomes_appended or competition["outcomes_appended"]
            else ForwardShadowExitCode.NO_MATURE_OUTCOMES
        ),
    )


def _collect_matured_competition_outcomes(
    session: Session,
    *,
    config: EffectiveRuntimeConfig,
    calendar: MarketSessionCalendar,
    collected_at: datetime,
) -> dict[str, int]:
    """Attach outcomes only after a frozen real-forward set reaches its horizon.

    This remains independent from the older semantic-LLM prediction ledger. A
    degraded fallback is kept in the immutable record for auditability, but
    ``competition_dashboard`` excludes any set with degraded variants from
    promotion-eligible sample counts.
    """

    ledger = ForwardCompetitionLedger(session)
    counts = {
        "decision_sets": 0,
        "outcomes_appended": 0,
        "pending_not_matured": 0,
        "pending_data": 0,
        "blocked_provenance": 0,
        "duplicate_outcomes": 0,
    }
    existing_outcomes = {
        (item.competition_id, item.evaluation_horizon, item.outcome.variant)
        for item in ledger.outcomes()
    }
    for decision in ledger.decision_sets():
        counts["decision_sets"] += 1
        base_session = calendar.completed_session_date(
            decision.tournament.information_cutoff
        )
        for horizon in COMPETITION_EVALUATION_HORIZONS:
            exit_session = calendar.advance_trading_sessions(
                base_session, int(horizon.removesuffix("d"))
            )
            outcome_timestamp = calendar.market_close_utc(exit_session)
            frozen_variants = tuple(decision.tournament.variants)
            if collected_at < outcome_timestamp:
                counts["pending_not_matured"] += len(frozen_variants)
                continue
            for frozen in frozen_variants:
                outcome_key = (decision.competition_id, horizon, frozen.variant)
                if outcome_key in existing_outcomes:
                    counts["duplicate_outcomes"] += 1
                    continue
                try:
                    quant, hybrid = _competition_counterfactual_pair(
                        decision,
                        frozen.variant,
                        horizon,
                    )
                    economics = _portfolio_outcome_economics(
                        session,
                        config=config,
                        calendar=calendar,
                        quant=quant,
                        hybrid=hybrid,
                        base_session=base_session,
                        exit_session=exit_session,
                        collected_at=collected_at,
                    )
                except OutcomePendingData:
                    counts["pending_data"] += 1
                    continue
                except OutcomeBlockedProvenance:
                    counts["blocked_provenance"] += 1
                    continue
                realized_return = _economics_float(economics, "quant_net_return")
                benchmark_return = _economics_float(economics, "benchmark_return")
                max_drawdown = _economics_float(economics, "quant_drawdown")
                turnover = _economics_float(economics, "quant_turnover")
                expected_cost = _economics_float(economics, "quant_cost")
                outcome = ForwardCompetitionOutcome(
                    competition_id=decision.competition_id,
                    decision_set_hash=decision.decision_set_hash,
                    evaluation_horizon=horizon,
                    outcome=OutcomeRecord(
                        outcome_id=_identity(
                            "forward-competition-outcome-record",
                            decision.competition_id,
                            frozen.variant.value,
                            horizon,
                        ),
                        decision_id=frozen.decision_id,
                        variant=frozen.variant,
                        outcome_time=outcome_timestamp,
                        evidence_class=EvidenceClass.FORWARD_SHADOW,
                        status=OutcomeStatus.COMPLETE,
                        realized_return=realized_return,
                        benchmark_return=benchmark_return,
                        excess_return=realized_return - benchmark_return,
                        max_drawdown=max_drawdown,
                        turnover=turnover,
                        expected_cost=expected_cost,
                        sample_session_count=len(
                            calendar.trading_session_window(base_session, exit_session)
                        ),
                    ),
                    data_snapshot_identity=cast(
                        dict[str, str], economics["data_snapshot_identity"]
                    ),
                    source_identity=str(economics["source_identity"]),
                    evidence_origin="REAL_FORWARD",
                )
                if ledger.append_outcome(outcome):
                    counts["outcomes_appended"] += 1
                    existing_outcomes.add(outcome_key)
                else:
                    counts["duplicate_outcomes"] += 1
    return counts


def _economics_float(economics: dict[str, object], field: str) -> float:
    value = economics.get(field)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise OutcomeBlockedProvenance(f"OUTCOME_ECONOMICS_INVALID:{field}")
    return float(value)


def _competition_counterfactual_pair(
    decision: ForwardCompetitionDecisionSet,
    variant: PortfolioVariant,
    horizon: str,
) -> tuple[QuantCounterfactualRecord, HybridCounterfactualRecord]:
    frozen = next(
        item for item in decision.tournament.variants if item.variant is variant
    )
    target_weights = {
        decision.symbol_to_security_id[symbol]: float(weight)
        for symbol, weight in frozen.target_weights.items()
    }
    common = {
        "observation_id": decision.competition_id,
        "decision_timestamp": frozen.decision_time,
        "information_cutoff": frozen.information_cutoff,
        "security_ids": decision.permanent_security_ids,
        "universe_identity": frozen.universe_identity,
        "evaluation_horizon": horizon,
        "execution_assumptions_hash": frozen.execution_assumptions_hash,
        "transaction_cost_model": frozen.transaction_cost_model,
        "slippage_model": frozen.execution_assumptions_hash,
        "benchmark_convention": frozen.benchmark,
        "data_version": decision.data_hash,
        "current_weights": decision.current_weights,
        "target_weights": target_weights,
        "risk_result": {"freeze_hash": frozen.freeze_hash},
        "optimizer_result": {"freeze_hash": frozen.freeze_hash},
    }
    return (
        QuantCounterfactualRecord(
            counterfactual_id=_identity(
                "forward-competition-quant", decision.competition_id, variant.value, horizon
            ),
            **common,
        ),
        HybridCounterfactualRecord(
            counterfactual_id=_identity(
                "forward-competition-hybrid", decision.competition_id, variant.value, horizon
            ),
            **common,
        ),
    )


class OutcomePendingData(RuntimeError):
    pass


class OutcomeBlockedProvenance(RuntimeError):
    pass


def _portfolio_outcome_economics(
    session: Session,
    *,
    config: EffectiveRuntimeConfig,
    calendar: MarketSessionCalendar,
    quant: QuantCounterfactualRecord,
    hybrid: HybridCounterfactualRecord,
    base_session: date,
    exit_session: date,
    collected_at: datetime,
) -> dict[str, object]:
    sessions = calendar.trading_session_window(base_session, exit_session)
    if len(sessions) < 2 or sessions[0] != base_session or sessions[-1] != exit_session:
        raise OutcomeBlockedProvenance("CERTIFIED_SESSION_WINDOW_INVALID")
    security_ids = tuple(sorted(set(quant.security_ids) | set(hybrid.security_ids)))
    security_rows = tuple(
        session.scalars(
            select(SecurityMaster).where(
                SecurityMaster.canonical_code.in_(security_ids),
                SecurityMaster.available_time <= quant.information_cutoff,
            )
        )
    )
    security_by_id: dict[str, SecurityMaster] = {}
    for security_id in security_ids:
        candidates = [row for row in security_rows if row.canonical_code == security_id]
        if not candidates:
            raise OutcomeBlockedProvenance(f"SECURITY_IDENTITY_MISSING:{security_id}")
        symbols = {row.symbol for row in candidates}
        if len(symbols) != 1:
            raise OutcomeBlockedProvenance(f"SECURITY_IDENTITY_AMBIGUOUS:{security_id}")
        security_by_id[security_id] = max(
            candidates,
            key=lambda row: (_db_aware(row.available_time), row.id),
        )
    benchmark_candidates = tuple(
        session.scalars(
            select(SecurityMaster).where(
                SecurityMaster.symbol == quant.benchmark_convention,
                SecurityMaster.available_time <= quant.information_cutoff,
            )
        )
    )
    benchmark_ids = {row.canonical_code for row in benchmark_candidates}
    if len(benchmark_ids) != 1:
        raise OutcomeBlockedProvenance("BENCHMARK_IDENTITY_AMBIGUOUS_OR_MISSING")
    benchmark = max(
        benchmark_candidates,
        key=lambda row: (_db_aware(row.available_time), row.id),
    )
    stock_ids = {row.id for row in security_by_id.values()} | {benchmark.id}
    rows = tuple(
        session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(stock_ids),
                Price.trade_date.in_(sessions),
                Price.price_type == "unadjusted_ohlcv",
                Price.available_time.is_not(None),
                Price.available_time <= collected_at,
            )
            .order_by(Price.stock_id, Price.trade_date, Price.available_time, Price.id)
        )
    )
    chosen: dict[tuple[int, date], Price] = {}
    primary_source = preferred_source("US")
    for stock_id in sorted(stock_ids):
        price_candidates = [row for row in rows if row.stock_id == stock_id]
        try:
            selected = select_consistent_price_series(
                price_candidates,
                preferred=primary_source,
            )
        except ValueError as error:
            raise OutcomeBlockedProvenance(
                f"PRICE_SOURCE_PROVENANCE:{stock_id}:{error}"
            ) from error
        for row in selected:
            chosen[(stock_id, row.trade_date)] = row
    required_stock_ids = {row.id for row in security_by_id.values()} | {benchmark.id}
    missing = [
        f"{stock_id}:{session_date}"
        for stock_id in sorted(required_stock_ids)
        for session_date in sessions
        if (stock_id, session_date) not in chosen
    ]
    if missing:
        raise OutcomePendingData("MISSING_EXACT_SESSION_PRICE:" + ",".join(missing[:10]))
    adjusted_availability = {row.adjusted_close is not None for row in chosen.values()}
    if len(adjusted_availability) != 1:
        raise OutcomeBlockedProvenance("MIXED_ADJUSTED_PRICE_AVAILABILITY")
    use_adjusted = adjusted_availability == {True}

    def price_value(row: Price) -> float:
        value = row.adjusted_close if use_adjusted else row.close
        assert value is not None
        return float(value)

    prices: dict[str, list[float]] = {}
    for security_id, security in security_by_id.items():
        prices[security_id] = [
            price_value(chosen[(security.id, session_date)]) for session_date in sessions
        ]
    benchmark_prices = [
        price_value(chosen[(benchmark.id, session_date)]) for session_date in sessions
    ]
    if any(value <= 0 for series in prices.values() for value in series) or any(
        value <= 0 for value in benchmark_prices
    ):
        raise OutcomeBlockedProvenance("NON_POSITIVE_PRICE")
    quant_turnover = _turnover(quant.current_weights, quant.target_weights)
    hybrid_turnover = _turnover(hybrid.current_weights, hybrid.target_weights)
    cost_rate = TransactionCostModel(config.transaction_cost).conservative_rate
    quant_cost = quant_turnover * cost_rate
    hybrid_cost = hybrid_turnover * cost_rate
    quant_path = _portfolio_path(quant.target_weights, prices)
    hybrid_path = _portfolio_path(hybrid.target_weights, prices)
    benchmark_return = benchmark_prices[-1] / benchmark_prices[0] - 1.0
    source_rows = [
        {
            "stock_id": row.stock_id,
            "trade_date": row.trade_date.isoformat(),
            "close": str(row.close),
            "adjusted_close": str(row.adjusted_close),
            "source": row.source,
            "provider": row.provider,
            "available_time": _db_aware(cast(datetime, row.available_time)).isoformat(),
            "adjustment_method": row.adjustment_method,
        }
        for row in sorted(chosen.values(), key=lambda item: (item.stock_id, item.trade_date))
    ]
    source_identity = fingerprint(source_rows)
    snapshot_identity = {
        "outcome_source_hash": source_identity,
        "entry_session": base_session.isoformat(),
        "exit_session": exit_session.isoformat(),
        "return_semantics": (
            "YAHOO_ADJUSTED_CLOSE_TOTAL_RETURN_EXACT_SESSION_V1"
            if use_adjusted
            else "YAHOO_UNADJUSTED_CLOSE_EXACT_SESSION_V1"
        ),
        "transaction_cost_version": config.transaction_cost.version,
        "benchmark_security_id": benchmark.canonical_code,
    }
    return {
        "quant_net_return": quant_path[-1] - quant_cost,
        "hybrid_net_return": hybrid_path[-1] - hybrid_cost,
        "benchmark_return": benchmark_return,
        "quant_cost": quant_cost,
        "hybrid_cost": hybrid_cost,
        "quant_turnover": quant_turnover,
        "hybrid_turnover": hybrid_turnover,
        "quant_drawdown": _drawdown(quant_path, quant_cost),
        "hybrid_drawdown": _drawdown(hybrid_path, hybrid_cost),
        "data_snapshot_identity": snapshot_identity,
        "source_identity": source_identity,
    }


def _portfolio_path(
    weights: dict[str, float],
    prices: dict[str, list[float]],
) -> list[float]:
    if any(not math.isfinite(weight) or weight < 0 for weight in weights.values()):
        raise OutcomeBlockedProvenance("INVALID_COUNTERFACTUAL_WEIGHT")
    if sum(weights.values()) > 1.0 + 1e-8:
        raise OutcomeBlockedProvenance("COUNTERFACTUAL_WEIGHT_SUM_EXCEEDS_ONE")
    count = len(next(iter(prices.values()))) if prices else 0
    path: list[float] = []
    for index in range(count):
        value = sum(
            weights.get(security_id, 0.0) * (series[index] / series[0] - 1.0)
            for security_id, series in prices.items()
        )
        path.append(value)
    return path


def _turnover(current: dict[str, float], target: dict[str, float]) -> float:
    return sum(
        abs(target.get(key, 0.0) - current.get(key, 0.0))
        for key in set(current) | set(target)
    )


def _drawdown(path: list[float], cost: float) -> float:
    values = [max(1e-12, 1.0 + value - cost) for value in path]
    peak = values[0]
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, (peak - value) / peak)
    return maximum


def _append_outcome_status(
    session: Session,
    *,
    observation_id: str,
    horizon: str,
    status: str,
    reason: str,
    observed_at: datetime,
) -> bool:
    payload: dict[str, object] = {
        "observation_id": observation_id,
        "evaluation_horizon": horizon,
        "status": status,
        "reason": reason,
        "observed_at": observed_at.isoformat(),
        "eligible_for_promotion": False,
    }
    result_id = _identity("outcome-status", observation_id, horizon, status, reason)
    existing = session.scalar(
        select(IntelligenceResearchResult).where(
            IntelligenceResearchResult.result_type == OUTCOME_COLLECTION_STATUS_TYPE,
            IntelligenceResearchResult.result_id == result_id,
        )
    )
    if existing is not None:
        return False
    IntelligenceRepository(session).add_result(
        result_id=result_id,
        result_type=OUTCOME_COLLECTION_STATUS_TYPE,
        schema_version=FORWARD_SHADOW_SCHEMA_VERSION,
        model_version=__version__,
        prompt_version="outcome-collector-v1",
        data_cutoff=observed_at,
        status=status,
        payload=payload,
    )
    session.flush()
    return True


def _outcome_statuses(session: Session) -> tuple[dict[str, object], ...]:
    rows = session.scalars(
        select(IntelligenceResearchResult)
        .where(IntelligenceResearchResult.result_type == OUTCOME_COLLECTION_STATUS_TYPE)
        .order_by(IntelligenceResearchResult.data_cutoff)
    )
    latest: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        payload = dict(row.payload)
        key = (
            str(payload.get("observation_id", "")),
            str(payload.get("evaluation_horizon", "")),
        )
        latest[key] = payload
    return tuple(latest.values())


def _counterfactual_map(
    rows: tuple[dict[str, object], ...],
    model: type[QuantCounterfactualRecord] | type[HybridCounterfactualRecord],
    reasons: Counter[str],
) -> dict[tuple[str, str], QuantCounterfactualRecord | HybridCounterfactualRecord]:
    output: dict[
        tuple[str, str], QuantCounterfactualRecord | HybridCounterfactualRecord
    ] = {}
    for row in rows:
        try:
            record = model.model_validate(row)
        except ValueError:
            reasons["INCOMPLETE_PROVENANCE"] += 1
            continue
        key = (record.observation_id, record.evaluation_horizon)
        existing = output.get(key)
        if existing is not None and existing != record:
            reasons["DUPLICATE"] += 1
            continue
        output[key] = record
    return output


def _exact_counterfactual_pair(
    quant: QuantCounterfactualRecord,
    hybrid: HybridCounterfactualRecord,
) -> bool:
    return all(
        getattr(quant, field) == getattr(hybrid, field)
        for field in (
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
    )


def _prediction_regime(predictions: list[SemanticForwardPredictionRecord]) -> str:
    values = {
        str(
            prediction.quant_risk_result.get(
                "regime",
                prediction.quant_risk_result.get("risk_regime", "UNAVAILABLE"),
            )
        )
        for prediction in predictions
    }
    return next(iter(values)) if len(values) == 1 else "REGIME_PROVENANCE_INCONSISTENT"


def _provider_configuration(settings: Settings) -> tuple[str, str, str, str]:
    selected = settings.llm_provider
    if selected == "openai":
        return selected, settings.openai_model, "OPENAI_DEFAULT", (
            "PRESENT" if settings.openai_api_key else "MISSING"
        )
    if selected == "deepseek":
        return selected, settings.deepseek_model, settings.deepseek_base_url, (
            "PRESENT" if settings.deepseek_api_key else "MISSING"
        )
    if selected == "anthropic":
        return selected, settings.anthropic_model, settings.anthropic_base_url, (
            "PRESENT" if settings.anthropic_api_key else "MISSING"
        )
    if selected == "custom":
        return selected, settings.custom_model, settings.custom_base_url, (
            "PRESENT" if settings.custom_api_key else "MISSING"
        )
    return selected, "UNAVAILABLE", "UNAVAILABLE", "MISSING"


def _provider_failure_from_document(document: dict[str, object]) -> str | None:
    inferences = document.get("llm_inferences")
    if not isinstance(inferences, list):
        return None
    errors = [
        _normalize_provider_failure(str(item.get("error_code")))
        for item in inferences
        if isinstance(item, dict) and item.get("error_code")
    ]
    return errors[0] if errors else None


def _normalize_provider_failure(category: str) -> str:
    mapping = {
        "AUTHENTICATION_FAILED": "AUTH_FAILURE",
        "RATE_LIMITED": "RATE_LIMIT",
        "QUOTA_EXCEEDED": "RATE_LIMIT",
        "TIMEOUT": "TIMEOUT",
        "PROVIDER_UNAVAILABLE": "PROVIDER_ERROR",
        "REQUEST_FAILED": "NETWORK_ERROR",
        "STRUCTURED_OUTPUT_INVALID": "MALFORMED_OUTPUT",
        "GroundingViolation": "IDENTITY_FAILURE",
        "PITViolation": "PIT_VALIDATION_FAILURE",
        "ValidationError": "SCHEMA_VALIDATION_FAILURE",
        "ValueError": "SCHEMA_VALIDATION_FAILURE",
    }
    return mapping.get(category, category if category != "None" else "UNKNOWN_FAILURE")


def _llm_request_hash(provider: str, model: str, request: LLMRequest) -> str:
    return fingerprint(
        {
            "provider": provider,
            "model": model,
            "system_prompt": request.system_prompt,
            "user_prompt": request.user_prompt,
            "temperature": request.temperature,
            "task_type": request.task_type,
            "prompt_version": request.prompt_version,
            "input_document_ids": request.input_document_ids,
            "as_of": request.as_of,
            "max_tokens": request.max_tokens,
            "thinking": request.thinking,
            "reasoning_effort": request.reasoning_effort,
        }
    )


def _cached_response(payload: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        content=str(payload["content"]),
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        is_mock=False,
        request_id=(
            str(payload["provider_request_id"])
            if payload.get("provider_request_id") is not None
            else None
        ),
        request_hash=str(payload["request_hash"]),
        response_hash=str(payload["response_hash"]),
        prompt_tokens=_required_nonnegative_integer(payload.get("prompt_tokens")),
        completion_tokens=_required_nonnegative_integer(
            payload.get("completion_tokens")
        ),
        cached_tokens=_required_nonnegative_integer(payload.get("cached_tokens")),
        latency_ms=_required_nonnegative_integer(payload.get("latency_ms")),
        retry_count=_required_nonnegative_integer(payload.get("retry_count")),
        validation_status=str(payload.get("validation_status", "NOT_VALIDATED")),
        estimated_cost_usd=_required_finite_number(payload.get("estimated_cost_usd")),
    )


def _write_provider_health(path: Path, health: ProviderHealth) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(health.document(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_provider_health(path: Path) -> ProviderHealth | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(ProviderHealth.__dataclass_fields__)
        return ProviderHealth(**{key: value for key, value in payload.items() if key in allowed})
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _validate_safe_operational_payload(value: object, path: str = "root") -> None:
    forbidden = {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "token",
        "cookie",
        "secret",
        "account_id",
        "cash_balance",
        "total_account_value",
        "position_quantity",
        "cost_basis",
        "order_history",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in forbidden or any(
                marker in normalized
                for marker in ("api_key", "password", "authorization", "cookie")
            ):
                raise ValueError(f"forbidden operational payload field: {path}.{key}")
            _validate_safe_operational_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_safe_operational_payload(item, f"{path}[{index}]")


def _identity(prefix: str, *parts: str) -> str:
    return sha256("|".join((prefix, *parts)).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _db_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_aware(value: str) -> datetime:
    return _aware(datetime.fromisoformat(value))


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value >= 0 and value.is_integer() else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _required_nonnegative_integer(value: object) -> int:
    parsed = _nonnegative_integer(value)
    if parsed is None:
        raise ValueError("cached provider metadata contains an invalid integer")
    return parsed


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _required_finite_number(value: object) -> float:
    parsed = _finite_number(value)
    if parsed is None:
        raise ValueError("cached provider metadata contains an invalid finite number")
    return parsed


def _increment_failure(
    previous: ProviderHealth | None,
    failure: str,
) -> dict[str, int]:
    counts = dict(previous.failure_counts or {}) if previous is not None else {}
    counts[failure] = counts.get(failure, 0) + 1
    return counts
