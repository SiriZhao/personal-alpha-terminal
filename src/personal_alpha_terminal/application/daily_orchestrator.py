from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal import __version__
from personal_alpha_terminal.application.daily_result import (
    BenchmarkSummary,
    DailyQuantResult,
    DataHealthItem,
    DecisionReadiness,
    DecisionRow,
    ExecutionLeg,
    ExecutionPlan,
    FactorRow,
    PortfolioPositionRow,
    PortfolioSummary,
    ProbabilityRow,
    RejectedSignalRow,
    RiskSummary,
    StageResult,
    StageStatus,
)
from personal_alpha_terminal.application.data_certification import (
    DailyDataCertification,
)
from personal_alpha_terminal.application.data_service import DataService, SyncRunner
from personal_alpha_terminal.application.intelligence_service import (
    IntelligenceApplicationService,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
    TodayResult,
)
from personal_alpha_terminal.core.build_metadata import current_build_metadata
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import (
    EffectiveRuntimeConfig,
    effective_config_from_settings,
)
from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.intelligence.factor_registry import (
    CrossSectionalEventFactorEngine,
    default_llm_factor_registry,
)
from personal_alpha_terminal.intelligence.llm_runtime import (
    DEFAULT_LLM_RUNTIME_STATUS_PATH,
    llm_runtime_status,
)
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models import Portfolio
from personal_alpha_terminal.models.intelligence import (
    IntelligenceExtractionCache,
    IntelligenceFeature,
    IntelligenceRawInformation,
    IntelligenceResearchResult,
)
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSession,
    MarketSessionCalendar,
)

_STAGE_ORDER = (
    "CALENDAR",
    "DATA",
    "PIT",
    "LLM_INTELLIGENCE",
    "FEATURE",
    "FACTOR",
    "SIGNAL",
    "PROBABILITY",
    "PORTFOLIO",
    "RISK",
    "DECISION",
    "EXECUTION",
    "PERSISTENCE",
)


class DailyQuantOrchestrator:
    """Single application entry for the production daily decision report.

    The orchestrator coordinates data refresh, calendar resolution and the existing
    production DB -> alpha -> portfolio pipeline. It never calculates a signal or
    changes a decision in the presentation layer.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        effective_config: EffectiveRuntimeConfig | Settings,
        *,
        snapshot_root: Path | None = None,
        sync_runner: SyncRunner | None = None,
        llm_runtime_status_path: Path = DEFAULT_LLM_RUNTIME_STATUS_PATH,
    ) -> None:
        self._factory = session_factory
        if isinstance(effective_config, Settings):
            effective_config = effective_config_from_settings(effective_config)
        self._effective_config = effective_config
        self._settings = effective_config.settings
        self._snapshot_root = snapshot_root or (effective_config.report_dir / "daily-runs")
        self._sync_runner = sync_runner
        self._llm_runtime_status_path = llm_runtime_status_path
        self._calendar = MarketSessionCalendar(
            nasdaq_23h_enabled=effective_config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=effective_config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
            allow_deterministic_fallback=effective_config.allow_calendar_fallback,
        )

    def run(
        self,
        *,
        portfolio_id: int | None = None,
        decision_time: datetime | None = None,
        refresh: bool = True,
    ) -> DailyQuantResult:
        started_at = datetime.now(UTC)
        run_id = f"daily-{uuid4().hex}"
        now = decision_time or started_at
        effective_decision_time = now
        if now.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        stages: dict[str, StageResult] = {}
        blockers: list[str] = []
        warnings: list[str] = []

        stage_started = perf_counter()
        try:
            market = self._calendar.classify(now)
            analysis_date = self._analysis_date(market.timestamp_et, market.session)
            stages["CALENDAR"] = StageResult(
                "CALENDAR",
                StageStatus.PASS,
                perf_counter() - stage_started,
                f"{market.session.value}; trade date {market.trade_date}",
                {
                    "timezone": "America/New_York",
                    "structure": market.structure_version.value,
                },
            )
        except (ImportError, RuntimeError, TypeError, ValueError) as error:
            fallback_date = now.astimezone(UTC).date()
            return self._blocked_result(
                run_id=run_id,
                started_at=started_at,
                now=now,
                analysis_date=fallback_date,
                trade_date=fallback_date,
                market_session="UNKNOWN",
                market_structure="UNKNOWN",
                failed_stage="CALENDAR",
                reason=f"calendar resolution failed: {error}",
                stages=stages,
            )

        resolved_portfolio = self._resolve_portfolio(portfolio_id)
        portfolio_issue = self._portfolio_preflight_issue(
            requested=portfolio_id,
            resolved=resolved_portfolio,
        )
        data_health: tuple[DataHealthItem, ...] = ()
        certification: DailyDataCertification | None = None
        data_failure_reasons: list[str] = []
        stage_started = perf_counter()
        try:
            with self._factory.begin() as session:
                data_service = DataService(
                    session,
                    self._settings,
                    snapshot_root=self._snapshot_root.parent / "data-snapshots",
                    sync_runner=self._sync_runner,
                )
                if refresh:
                    sync = data_service.sync_market_data(
                        start_date=data_service.refresh_start_date(analysis_date=analysis_date),
                        end_date=analysis_date,
                    )
                    if sync.status == "BLOCKED":
                        data_failure_reasons.append(
                            "required provider refresh failed: " + ", ".join(sync.failed_symbols)
                        )
                    if sync.status != "CERTIFIED":
                        warnings.append(f"market refresh completed as {sync.status}")
                    if decision_time is None:
                        # A live decision can only occur after the newly retrieved evidence
                        # exists.  Calendar/trade-date resolution remains anchored to run start.
                        effective_decision_time = datetime.now(UTC)
                readiness = data_service.get_data_readiness(as_of=effective_decision_time)
                manifest = data_service.latest_manifest()
                certification = data_service.daily_certification(
                    analysis_date=analysis_date,
                    decision_time=effective_decision_time,
                )
                data_health = (
                    DataHealthItem(
                        dataset="LIVE_RAW_OHLCV",
                        expected_date=analysis_date,
                        latest_date=certification.latest_date,
                        age_days=(
                            (analysis_date - certification.latest_date).days
                            if certification.latest_date is not None
                            else None
                        ),
                        coverage=certification.coverage,
                        missing_ratio=self._missing_ratio(manifest),
                        source=certification.provider,
                        status=certification.status,
                        detail=(
                            "; ".join((*certification.blockers, *certification.warnings))
                            or readiness.technical_reason
                        ),
                        dataset_id="market-data:US:raw-ohlcv",
                        as_of=analysis_date,
                        cutoff=certification.pit_cutoff,
                        snapshot_id=certification.snapshot_id or "UNAVAILABLE",
                        data_version=certification.snapshot_id or "UNAVAILABLE",
                        provider=certification.provider,
                        row_count=certification.valid_bars,
                        quality_status=certification.status.value,
                        content_hash=certification.data_hash or "UNAVAILABLE",
                        certification_state=certification.status.value,
                    ),
                )
                warnings.extend(certification.warnings)
                if certification.status is StageStatus.FAIL_BLOCKING:
                    data_failure_reasons.extend(certification.blockers)
            if data_failure_reasons:
                raise RuntimeError("; ".join(dict.fromkeys(data_failure_reasons)))
            stages["DATA"] = StageResult(
                "DATA",
                certification.status,
                perf_counter() - stage_started,
                (
                    "canonical required market data certified"
                    if certification.status is StageStatus.PASS
                    else "optional data degraded; required strategy inputs are intact"
                ),
                {
                    "refresh": refresh,
                    **certification.metadata(),
                    "output_row_count": certification.valid_bars,
                },
            )
        except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
            blockers.append(str(error))
            if portfolio_issue is not None:
                blockers.append(portfolio_issue)
                stages["PORTFOLIO"] = StageResult(
                    "PORTFOLIO",
                    StageStatus.FAIL_BLOCKING,
                    0.0,
                    portfolio_issue,
                    {"blocker_category": "USER_STATE", "output_row_count": 0},
                )
            evidence = certification.metadata() if certification is not None else {}
            stages["DATA"] = StageResult(
                "DATA",
                StageStatus.FAIL_BLOCKING,
                perf_counter() - stage_started,
                str(error),
                {
                    "refresh": refresh,
                    **evidence,
                    "output_row_count": (
                        certification.valid_bars if certification is not None else 0
                    ),
                },
            )
            return self._finalize_blocked(
                run_id,
                started_at,
                effective_decision_time,
                analysis_date,
                market.trade_date,
                market.session.value,
                market.structure_version.value,
                stages,
                data_health,
                blockers,
                warnings,
            )

        stage_started = perf_counter()
        with self._factory.begin() as session:
            workflow_result = ProductionDailyWorkflow(session, self._effective_config).run(
                portfolio_id=resolved_portfolio,
                decision_time=effective_decision_time,
            )
        quant_duration = perf_counter() - stage_started
        self._merge_quant_stages(stages, workflow_result, quant_duration)
        stage_started = perf_counter()
        self._add_llm_intelligence_stage(
            stages,
            as_of=effective_decision_time,
            duration_started=stage_started,
            warnings=warnings,
            run_id=run_id,
            eligible_symbols=tuple(item.symbol for item in workflow_result.factors),
        )
        blockers.extend(workflow_result.blockers)
        warnings.extend(workflow_result.warnings)
        for name in _STAGE_ORDER:
            if name != "PERSISTENCE" and name not in stages:
                stages[name] = StageResult(
                    name,
                    StageStatus.NOT_RUN,
                    0.0,
                    f"NOT RUN; Blocked by {self._failed_stage(stages)}",
                    {"blocked_by": self._failed_stage(stages)},
                )
        result = self._build_result(
            run_id=run_id,
            started_at=started_at,
            now=effective_decision_time,
            analysis_date=analysis_date,
            trade_date=market.trade_date,
            market_session=market.session.value,
            market_structure=market.structure_version.value,
            stages=stages,
            data_health=data_health,
            workflow=workflow_result,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )
        return self._persist_result(result)

    def _add_llm_intelligence_stage(
        self,
        stages: dict[str, StageResult],
        *,
        as_of: datetime,
        duration_started: float,
        warnings: list[str],
        run_id: str,
        eligible_symbols: tuple[str, ...],
    ) -> None:
        provider, model, configured, connectivity = self._configured_llm_identity()
        if not configured:
            stages["LLM_INTELLIGENCE"] = StageResult(
                "LLM_INTELLIGENCE",
                StageStatus.OPTIONAL_UNAVAILABLE,
                perf_counter() - duration_started,
                (
                    "LLM provider is disabled or has no inherited credential; "
                    "classical Quant Core continues"
                ),
                {
                    "provider": provider,
                    "model": model,
                    "connectivity": connectivity,
                    "processed_documents": 0,
                    "detected_events": 0,
                    "factor_status": "SHADOW",
                    "production_influence": False,
                    "output_row_count": 0,
                    "advisory_status": "UNAVAILABLE",
                    "advisory_quant_impact": "NONE",
                    "fallback": "CLASSICAL_CHAMPION",
                },
            )
            return
        try:
            with self._factory.begin() as session:
                status = IntelligenceApplicationService(session).status(as_of=as_of)
                events = (
                    IntelligenceRepository(session).visible_events(as_of)
                    if self._metadata_count(status, "canonical_event_count")
                    else ()
                )
                observations = (
                    CrossSectionalEventFactorEngine(
                        default_llm_factor_registry(model_version=model)
                    ).build(
                        events,
                        as_of=as_of,
                        eligible_symbols=eligible_symbols,
                    )
                    if events
                    else ()
                )
                latest_round13_record = session.scalar(
                    select(IntelligenceResearchResult)
                    .where(
                        IntelligenceResearchResult.result_type
                        == "ROUND13_SEC_SHADOW_FEATURES",
                        IntelligenceResearchResult.data_cutoff <= as_of,
                    )
                    .order_by(IntelligenceResearchResult.data_cutoff.desc())
                )
                latest_round13 = (
                    latest_round13_record.payload if latest_round13_record else {}
                )
                pit_document_count = session.scalar(
                    select(func.count())
                    .select_from(IntelligenceRawInformation)
                    .where(IntelligenceRawInformation.observed_at <= as_of)
                ) or 0
                issuer_resolved_document_count = session.scalar(
                    select(func.count())
                    .select_from(IntelligenceRawInformation)
                    .where(IntelligenceRawInformation.issuer_id.is_not(None))
                ) or 0
                security_mapped_document_count = session.scalar(
                    select(func.count())
                    .select_from(IntelligenceRawInformation)
                    .where(IntelligenceRawInformation.permanent_security_id.is_not(None))
                ) or 0
                latest_event_time = max((item.observed_at for item in events), default=None)
                cache_entries = session.scalar(
                    select(func.count()).select_from(IntelligenceExtractionCache)
                ) or 0
                shadow_observations = session.scalar(
                    select(func.count())
                    .select_from(IntelligenceFeature)
                    .where(
                        IntelligenceFeature.status == "SHADOW_ONLY",
                        IntelligenceFeature.data_cutoff <= as_of,
                    )
                ) or 0
                if observations:
                    payload: dict[str, object] = {
                        "run_id": run_id,
                        "as_of": as_of.isoformat(),
                        "status": "SHADOW",
                        "production_influence": False,
                        "observations": [
                            {
                                "symbol": item.symbol,
                                "factor_name": item.factor_name,
                                "raw_value": item.raw_value,
                                "normalized_value": item.normalized_value,
                                "extraction_confidence": item.extraction_confidence,
                                "statistical_probability": item.statistical_probability,
                                "event_ids": item.event_ids,
                                "observation_hash": item.observation_hash,
                            }
                            for item in observations
                        ],
                    }
                    IntelligenceRepository(session).add_result(
                        result_id=fingerprint(payload),
                        result_type="LLM_SHADOW_FACTOR_SNAPSHOT",
                        schema_version="llm-shadow-factor-v1",
                        model_version=model,
                        prompt_version="event-extraction-v2",
                        data_cutoff=as_of,
                        status="SHADOW",
                        payload=payload,
                    )
            event_count = self._metadata_count(status, "canonical_event_count")
            raw_count = self._metadata_count(status, "raw_information_count")
            cache_count = self._metadata_count(status, "cache_entry_count")
            message = (
                "PIT-safe structured intelligence loaded in SHADOW mode"
                if event_count
                else "NO_NEW_PIT_DOCUMENTS"
            )
            stages["LLM_INTELLIGENCE"] = StageResult(
                "LLM_INTELLIGENCE",
                StageStatus.PASS_DEGRADED,
                perf_counter() - duration_started,
                message,
                {
                    "provider": provider,
                    "model": model,
                    "connectivity": connectivity,
                    "raw_documents": raw_count,
                    "processed_documents": int(
                        str(latest_round13.get("processed_documents", 0))
                    ),
                    "detected_events": event_count,
                    "new_documents": int(str(latest_round13.get("processed_documents", 0))),
                    "pit_eligible_documents": pit_document_count,
                    "issuer_resolved_documents": issuer_resolved_document_count,
                    "security_mapped_documents": security_mapped_document_count,
                    "llm_calls": int(str(latest_round13.get("llm_calls", 0))),
                    "cache_hits": int(str(latest_round13.get("llm_cache_hits", 0))),
                    "accepted_events": int(str(latest_round13.get("events_accepted", 0))),
                    "quarantined_events": int(
                        str(latest_round13.get("events_quarantined", 0))
                    ),
                    "shadow_factor_observations": shadow_observations,
                    "latest_event_time": (
                        latest_event_time.isoformat() if latest_event_time else None
                    ),
                    "estimated_api_cost_usd": float(
                        str(latest_round13.get("estimated_api_cost_usd", 0.0))
                    ),
                    "cache_entry_count": max(cache_count, cache_entries),
                    "factor_status": "SHADOW",
                    "production_influence": False,
                    "fallback": "CLASSICAL_CHAMPION",
                    "fallback_reason": (
                        "LLM_FACTORS_NOT_PRODUCTION_APPROVED"
                        if event_count
                        else "CERTIFIED_PIT_TEXT_UNAVAILABLE"
                    ),
                    "output_row_count": event_count,
                    "advisory_status": "ADVISORY" if event_count else "SHADOW",
                    "advisory_quant_impact": "SHADOW" if observations else "NONE",
                    "advisory_pit_documents": raw_count,
                },
            )
            warnings.append(
                "LLM intelligence is SHADOW-only and cannot change production recommendations"
            )
        except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
            stages["LLM_INTELLIGENCE"] = StageResult(
                "LLM_INTELLIGENCE",
                StageStatus.OPTIONAL_UNAVAILABLE,
                perf_counter() - duration_started,
                (
                    f"LLM intelligence unavailable ({type(error).__name__}); "
                    "classical Quant Core continues"
                ),
                {
                    "provider": provider,
                    "model": model,
                    "connectivity": connectivity,
                    "factor_status": "UNAVAILABLE",
                    "production_influence": False,
                    "fallback": "CLASSICAL_CHAMPION",
                    "fallback_reason": "LLM_INTELLIGENCE_UNAVAILABLE",
                    "output_row_count": 0,
                    "advisory_status": "UNAVAILABLE",
                    "advisory_quant_impact": "NONE",
                },
            )

    def _configured_llm_identity(self) -> tuple[str, str, bool, str]:
        selected = self._settings.llm_provider
        runtime = llm_runtime_status(self._settings, self._llm_runtime_status_path)
        if selected == "deepseek":
            return (
                "deepseek",
                self._settings.deepseek_model,
                bool(self._settings.deepseek_api_key),
                runtime.connectivity,
            )
        if selected == "openai":
            return (
                "openai",
                self._settings.openai_model,
                bool(self._settings.openai_api_key),
                "CONFIGURED_NOT_TESTED",
            )
        if selected == "anthropic":
            return (
                "anthropic",
                self._settings.anthropic_model,
                bool(self._settings.anthropic_api_key),
                "CONFIGURED_NOT_TESTED",
            )
        if selected == "custom":
            return (
                "custom",
                self._settings.custom_model,
                bool(self._settings.custom_api_key),
                "CONFIGURED_NOT_TESTED",
            )
        if selected == "auto" and self._settings.deepseek_api_key:
            return "deepseek", self._settings.deepseek_model, True, runtime.connectivity
        if selected == "mock":
            return "mock", "deterministic-grounded-mock-v1", False, "TEST_ONLY"
        if runtime.credential == "PRESENT" and runtime.connectivity == "AVAILABLE":
            return runtime.provider, runtime.model, True, runtime.connectivity
        return selected, "NOT_CONFIGURED", False, runtime.connectivity

    def _resolve_portfolio(self, requested: int | None) -> int | None:
        if requested is None:
            return None
        with self._factory() as session:
            return requested if session.get(Portfolio, requested) is not None else None

    def _portfolio_preflight_issue(
        self,
        *,
        requested: int | None,
        resolved: int | None,
    ) -> str | None:
        if resolved is not None:
            return None
        with self._factory() as session:
            count = len(tuple(session.scalars(select(Portfolio.id).limit(2))))
        if count == 0:
            return "PORTFOLIO NOT INITIALIZED; run portfolio-init or portfolio-import"
        if requested is not None:
            return f"configured portfolio id {requested} does not exist"
        return (
            "PORTFOLIO NOT SELECTED; set portfolio_id in config.yaml after verifying "
            "the manual ledger"
        )

    def _analysis_date(self, timestamp_et: datetime, session: MarketSession) -> date:
        candidate = timestamp_et.date()
        if session is MarketSession.POSTMARKET and self._calendar.is_trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
        while not self._calendar.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    @staticmethod
    def _merge_quant_stages(
        stages: dict[str, StageResult], workflow: TodayResult, duration: float
    ) -> None:
        mapping = {
            "Data Quality Gate": "DATA",
            "PIT Universe": "PIT",
            "Broad Equity Universe": "PIT",
            "Point-in-Time Inputs": "PIT",
            "Feature Engine": "FEATURE",
            "Factor Engine": "FACTOR",
            "Alpha Signals": "SIGNAL",
            "Probability Overlay": "PROBABILITY",
            "Risk Model": "RISK",
            "Risk Budget": "RISK",
            "Portfolio Construction": "PORTFOLIO",
            "Trade Generator": "EXECUTION",
            "Daily Decision": "DECISION",
        }
        for item in workflow.pipeline_stages:
            name = mapping.get(item.name)
            if name is None:
                continue
            status = {
                "BLOCKED": StageStatus.FAIL_BLOCKING,
                "DEGRADED": StageStatus.PASS_DEGRADED,
            }.get(item.status, StageStatus.PASS)
            previous = stages.get(name)
            if previous is not None and previous.status is StageStatus.FAIL:
                continue
            if name == "DATA" and previous is not None and status is StageStatus.PASS:
                continue
            stages[name] = StageResult(
                name,
                status,
                0.0,
                item.detail,
                {
                    "source": item.name,
                    "output_row_count": (
                        len(workflow.factors)
                        if name in {"FEATURE", "FACTOR"}
                        else (
                            len(workflow.recommendations)
                            if name in {"SIGNAL", "DECISION", "EXECUTION"}
                            else 1
                        )
                    ),
                    **(
                        {
                            "authorization_class": (
                                workflow.signal_authorization_class
                            ),
                            "research_certification": (
                                workflow.research_certification_state
                            ),
                            "operational_policy_id": workflow.operational_policy_id,
                            "evidence_level": workflow.signal_evidence_level,
                        }
                        if name == "SIGNAL"
                        else {}
                    ),
                },
            )
        if workflow.factors:
            stages.setdefault(
                "FEATURE",
                StageResult(
                    "FEATURE",
                    StageStatus.PASS,
                    0.0,
                    "PIT price features computed",
                    {
                        "feature_names": sorted(
                            {name for item in workflow.factors for name in item.components}
                        ),
                        "valid_count": len(workflow.factors),
                        "missing_count": max(0, workflow.universe_count - len(workflow.factors)),
                        "output_row_count": len(workflow.factors),
                    },
                ),
            )
            stages.setdefault(
                "FACTOR",
                StageResult(
                    "FACTOR",
                    StageStatus.PASS,
                    0.0,
                    f"{len(workflow.factors)} cross-sectional observations",
                    {
                        "factor_names": sorted(
                            {name for item in workflow.factors for name in item.components}
                        ),
                        "cross_sectional_sample_size": len(workflow.factors),
                        "output_row_count": len(workflow.factors),
                    },
                ),
            )
        stages.setdefault(
            "PROBABILITY",
            StageResult(
                "PROBABILITY",
                (
                    StageStatus.PASS
                    if workflow.probability_overlay_active
                    else StageStatus.PASS_DEGRADED
                ),
                0.0,
                (
                    "approved calibrated residual overlay active"
                    if workflow.probability_overlay_active
                    else (
                        f"deterministic base alpha unchanged; {workflow.probability_overlay_reason}"
                    )
                ),
                {
                    "overlay_active": workflow.probability_overlay_active,
                    "overlay_state": workflow.probability_overlay_state,
                    "fallback_reason": workflow.probability_overlay_reason,
                    "position_influence": (1.0 if workflow.probability_overlay_active else 0.0),
                    "output_row_count": len(workflow.probability_overlay_effects),
                },
            ),
        )
        first_quant = next(
            (name for name in _STAGE_ORDER if name in stages and name != "CALENDAR"),
            None,
        )
        if first_quant is not None:
            stage_result = stages[first_quant]
            stages[first_quant] = replace(stage_result, duration_seconds=duration)

    def _build_result(
        self,
        *,
        run_id: str,
        started_at: datetime,
        now: datetime,
        analysis_date: date,
        trade_date: date,
        market_session: str,
        market_structure: str,
        stages: dict[str, StageResult],
        data_health: tuple[DataHealthItem, ...],
        workflow: TodayResult,
        blockers: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> DailyQuantResult:
        actionable = workflow.status in {"GENERATED", "NO_DECISION"} and not blockers
        data_cutoff = self._resolved_data_cutoff(stages, workflow.data_cutoff)
        data_metadata = stages.get(
            "DATA", StageResult("DATA", StageStatus.NOT_RUN, 0.0, "", {})
        ).metadata
        snapshot_id = str(data_metadata.get("snapshot_id") or "UNAVAILABLE")
        snapshot_hash = str(data_metadata.get("data_hash") or "UNAVAILABLE")
        build = current_build_metadata()
        factors = tuple(
            FactorRow(
                item.symbol,
                item.components,
                item.composite,
                item.rank,
                item.expected_alpha,
                item.evidence_coverage,
                item.status,
                item.raw_values,
                item.winsorized_values,
                item.neutralized_values,
                item.neutralization_evidence,
            )
            for item in workflow.factors
        )
        probability = tuple(
            ProbabilityRow(
                item.condition_id,
                "benchmark-relative residual return > approved threshold",
                item.sample_size,
                None,
                item.posterior_probability,
                None,
                None,
                item.probability_adjustment,
                None,
                None,
                None,
                "CALIBRATED LOCKED OOS",
                workflow.probability_calibration_status,
                "PASS",
            )
            for item in workflow.probability_overlay_effects
        ) or (
            ProbabilityRow(
                "Validated conditional residual overlay",
                "benchmark-relative return; advisory fallback",
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "INSUFFICIENT EVIDENCE",
                workflow.probability_overlay_reason,
                "PASS_DEGRADED",
            ),
        )
        target_weights = workflow.target.target_weights if workflow.target else {}
        current = workflow.current_weights or {}
        input_positions = {item.symbol: item for item in workflow.portfolio_positions}
        positions = tuple(
            PortfolioPositionRow(
                symbol,
                (input_positions[symbol].quantity if symbol in input_positions else None),
                (input_positions[symbol].reference_price if symbol in input_positions else None),
                current.get(symbol, 0.0),
                target_weights.get(symbol) if workflow.target else None,
                (
                    target_weights.get(symbol, 0.0) - current.get(symbol, 0.0)
                    if workflow.target
                    else None
                ),
            )
            for symbol in sorted(set(current) | set(target_weights))
        )
        actual_cash_weight = (
            workflow.cash_balance / workflow.portfolio_value
            if workflow.cash_balance is not None
            and workflow.portfolio_value is not None
            and workflow.portfolio_value > 0
            else None
        )
        portfolio = PortfolioSummary(
            workflow.portfolio_status,
            workflow.portfolio_value,
            workflow.cash_balance,
            actual_cash_weight,
            (1.0 - actual_cash_weight if actual_cash_weight is not None else None),
            positions,
        )
        target = workflow.target
        risk = RiskSummary(
            "PASS" if workflow.risk is not None and target is not None else "BLOCKED",
            target.expected_volatility if target else None,
            workflow.configured_target_volatility if target else None,
            None,
            target.hhi if target else None,
            target.turnover if target else None,
            workflow.gross_target,
            workflow.cash_target,
            None,
            max(target.target_weights.values(), default=0.0) if target else None,
            target.risk_reductions if target else tuple(blockers),
            (workflow.risk_state.average_correlation if workflow.risk_state is not None else None),
            (
                workflow.risk_state.baseline_average_correlation
                if workflow.risk_state is not None
                else None
            ),
            workflow.risk_state.correlation_jump if workflow.risk_state is not None else None,
            (
                workflow.risk_state.correlation_status.value
                if workflow.risk_state is not None
                else "NOT_CAPTURED"
            ),
            (
                workflow.risk_state.correlation_recent_window
                if workflow.risk_state is not None
                else 0
            ),
            (
                workflow.risk_state.correlation_baseline_window
                if workflow.risk_state is not None
                else 0
            ),
            (
                min(
                    workflow.risk_state.correlation_recent_samples,
                    workflow.risk_state.correlation_baseline_samples,
                )
                if workflow.risk_state is not None
                else 0
            ),
            (
                workflow.risk.size_exposure_status.value
                if workflow.risk is not None
                else "NOT_CAPTURED"
            ),
            workflow.stress.status.value if workflow.stress is not None else "NOT_CAPTURED",
            workflow.stress.hard_failures if workflow.stress is not None else (),
            workflow.stress.warnings if workflow.stress is not None else (),
        )
        decisions = tuple(
            DecisionRow(
                item.recommendation_id,
                item.symbol,
                item.action,
                item.current_weight,
                item.target_weight,
                item.target_delta,
                item.estimated_value,
                item.estimated_quantity,
                item.expected_cost,
                item.expected_alpha,
                item.confidence,
                item.risk_contribution,
                item.reason,
                item.data_quality,
                item.model_version,
                item.data_version,
                item.earliest_execution_time,
                item.expiry,
            )
            for item in workflow.recommendations
        )
        rejected = [
            RejectedSignalRow("ALL", self._failed_stage(stages), reason) for reason in blockers
        ]
        if target is not None:
            rejected.extend(
                RejectedSignalRow("PORTFOLIO", "RISK", reason) for reason in target.risk_reductions
            )
        execution = self._execution_plan(workflow, decisions, actionable)
        benchmarks = self._benchmarks(workflow)
        pit_status = (
            StageStatus.PASS if workflow.data_certification == "APPROVED" else StageStatus.FAIL
        )
        strategy_data_health = (
            *data_health,
            DataHealthItem(
                "POINT_IN_TIME_TOTAL_RETURN",
                analysis_date,
                data_cutoff.date() if data_cutoff else None,
                ((analysis_date - data_cutoff.date()).days if data_cutoff else None),
                None,
                None,
                ",".join(workflow.source_ids) or "UNAVAILABLE",
                pit_status,
                f"data_version={workflow.data_hash}",
                dataset_id="research-data:US:pit-total-return",
                as_of=analysis_date,
                cutoff=data_cutoff,
                snapshot_id=snapshot_id,
                data_version=workflow.data_hash,
                provider=str(data_metadata.get("provider") or "UNAVAILABLE"),
                row_count=len(workflow.factors),
                quality_status=pit_status.value,
                content_hash=snapshot_hash,
                certification_state=pit_status.value,
            ),
            DataHealthItem(
                "CERTIFIED_US_UNIVERSE",
                analysis_date,
                analysis_date if workflow.universe_count else None,
                0 if workflow.universe_count else None,
                (
                    len(workflow.factors) / workflow.universe_count
                    if workflow.universe_count
                    else None
                ),
                None,
                ",".join(workflow.source_ids) or "UNAVAILABLE",
                pit_status,
                f"members={workflow.universe_count}; valid={len(workflow.factors)}",
                dataset_id="universe:US:certified-live",
                as_of=analysis_date,
                cutoff=data_cutoff,
                snapshot_id=workflow.universe_snapshot_id,
                data_version=workflow.data_hash,
                provider=str(data_metadata.get("provider") or "UNAVAILABLE"),
                member_count=workflow.universe_count,
                quality_status=pit_status.value,
                content_hash=snapshot_hash,
                certification_state=pit_status.value,
            ),
        )
        return DailyQuantResult(
            run_id,
            __version__,
            started_at,
            datetime.now(UTC),
            analysis_date,
            trade_date,
            market_session,
            market_structure,
            data_cutoff,
            DecisionReadiness.READY if actionable else DecisionReadiness.NOT_ACTIONABLE,
            self._llm_status(stages),
            self._ordered_stages(stages),
            strategy_data_health,
            workflow.risk_regime,
            (
                workflow.risk_regime_detail
                or "Regime probability is unavailable; no uncalibrated score changes alpha."
            ),
            factors,
            probability,
            tuple(sorted(factors, key=lambda item: item.rank)[:10]),
            portfolio,
            risk,
            decisions if actionable else (),
            tuple(rejected),
            execution,
            benchmarks,
            blockers,
            warnings,
            {
                "database_run_id": workflow.run_id,
                "data_hash": snapshot_hash,
                "data_snapshot_id": snapshot_id,
                "research_data_version": workflow.data_hash,
                "universe_version": workflow.universe_snapshot_id,
                "model_hash": workflow.model_hash,
                "strategy_version": workflow.strategy_version,
                "factor_version": workflow.strategy_version,
                "signal_version": workflow.strategy_version,
                "production_approval_artifact_id": (workflow.production_approval_artifact_id),
                "portfolio_validation_artifact_id": (workflow.portfolio_validation_artifact_id),
                "probability_artifact_id": workflow.probability_artifact_id,
                "portfolio_id": self._effective_config.portfolio_id or "UNSELECTED",
                "portfolio_snapshot_id": workflow.portfolio_snapshot_id,
                "deterministic_core_model": workflow.strategy_version,
                "ml_model": "NOT_REQUIRED",
                "llm_model": self._llm_provenance(stages),
                "build_identifier": build.build_id,
                "git_commit": build.git_commit,
                "build_time": build.build_time,
                "dependency_lock_hash": build.dependency_lock_hash,
                "randomness": "NOT_USED",
                "source_ids": workflow.source_ids,
                "universe_count": workflow.universe_count,
                "universe_evidence": workflow.universe_evidence,
                "probability_overlay": {
                    "active": workflow.probability_overlay_active,
                    "state": workflow.probability_overlay_state,
                    "reason": workflow.probability_overlay_reason,
                    "effects": [
                        {
                            "symbol": item.symbol,
                            "condition_id": item.condition_id,
                            "base_expected_excess_return": (item.base_expected_excess_return),
                            "probability_adjustment": item.probability_adjustment,
                            "adjusted_expected_excess_return": (
                                item.adjusted_expected_excess_return
                            ),
                            "posterior_probability": item.posterior_probability,
                            "sample_size": item.sample_size,
                        }
                        for item in workflow.probability_overlay_effects
                    ],
                },
                "manual_broker": "Charles Schwab",
                "automatic_execution": False,
                "data_mode": (
                    "LIVE_REFRESH"
                    if data_metadata.get("refresh")
                    else "CACHE_REPLAY"
                ),
                "lifecycle": workflow.lifecycle,
                "lifecycle_blocked_symbols": workflow.lifecycle_blocked_symbols,
                "transaction_cost_assumption": (
                    f"commission {self._effective_config.transaction_cost.commission_bps} bps; "
                    f"spread {self._effective_config.transaction_cost.spread_bps} bps; "
                    f"slippage {self._effective_config.transaction_cost.slippage_bps} bps; "
                    f"impact {self._effective_config.transaction_cost.impact_coefficient_bps} bps; "
                    "GROSS benchmark returns shown pre-cost (no live strategy track record)"
                ),
                "cost_assumptions": {
                    "commission_bps": self._effective_config.transaction_cost.commission_bps,
                    "spread_bps": self._effective_config.transaction_cost.spread_bps,
                    "slippage_bps": self._effective_config.transaction_cost.slippage_bps,
                    "impact_coefficient_bps": (
                        self._effective_config.transaction_cost.impact_coefficient_bps
                    ),
                    "model_version": self._effective_config.transaction_cost.version,
                },
                "identity_hashes": {
                    **(workflow.identity_hashes or {}),
                    "model_approval_hash": workflow.model_approval_hash,
                },
                "probability_calibration_status": workflow.probability_calibration_status,
                "operational_approval_artifact_id": workflow.operational_approval_artifact_id,
                "operational_readiness": workflow.operational_readiness,
                "research_certification_state": workflow.research_certification_state,
                "operational_policy_id": workflow.operational_policy_id,
                "operational_policy_decision": workflow.operational_policy_decision,
                "operational_policy_effective": workflow.operational_policy_effective,
                "operational_policy_reason": workflow.operational_policy_reason,
                "operational_policy_hash": workflow.operational_policy_hash,
                "operational_policy_identity_hash": (
                    workflow.operational_policy_identity_hash
                ),
                "signal_authorization_class": workflow.signal_authorization_class,
                "signal_evidence_level": workflow.signal_evidence_level,
                "operationally_allowed": workflow.operationally_allowed,
                "operational_degraded_reason": workflow.operational_degraded_reason,
                "full_research_certified": False,
            },
            self._effective_config.canonical_run_config_hash,
            tuple(
                sorted(
                    {
                        workflow.strategy_version,
                        *(
                            item.model_version
                            for item in decisions
                            if item.model_version != "UNAVAILABLE"
                        ),
                    }
                    - {"UNAVAILABLE"}
                )
            ),
            self._decision_traces(
                factors,
                decisions,
                target_weights,
                current,
                workflow.probability_counterfactual,
            ),
            None,
            workflow.operational_readiness,
            workflow.operational_approval_artifact_id,
            workflow.research_certification_state,
            workflow.operational_policy_id,
            workflow.operational_policy_decision,
            workflow.operational_policy_effective,
            workflow.operational_policy_reason,
            workflow.operationally_allowed,
            workflow.operational_degraded_reason,
        )

    @staticmethod
    def _resolved_data_cutoff(
        stages: dict[str, StageResult], workflow_cutoff: datetime | None
    ) -> datetime | None:
        """Prefer the certified market-observation cutoff from DATA evidence.

        PIT return frames use session dates as their index, so their maximum
        index is midnight UTC and is not the actual market-data cutoff.  The DATA
        certificate carries the canonical timezone-aware observation cutoff.
        """

        fallback = StageResult("DATA", StageStatus.NOT_RUN, 0, "", {})
        value = stages.get("DATA", fallback).metadata.get("pit_cutoff")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return workflow_cutoff
            return parsed if parsed.tzinfo is not None else workflow_cutoff
        return workflow_cutoff

    @staticmethod
    def _decision_traces(
        factors: tuple[FactorRow, ...],
        decisions: tuple[DecisionRow, ...],
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        probability_counterfactual: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, dict[str, object]]:
        probability_counterfactual = probability_counterfactual or {}
        decision_by_symbol = {item.symbol: item for item in decisions}
        traces: dict[str, dict[str, object]] = {}
        for factor in factors:
            decision = decision_by_symbol.get(factor.symbol)
            traces[factor.symbol] = {
                "ticker": factor.symbol,
                "data_quality": decision.data_quality if decision else "NOT_CAPTURED",
                "factor_raw_values": factor.raw_values or "NOT_CAPTURED",
                "factor_winsorized_values": (factor.winsorized_values or "NOT_CAPTURED"),
                "factor_normalized_values": "NOT_CAPTURED",
                "factor_neutralized_values": (factor.neutralized_values or factor.components),
                "cross_sectional_rank": factor.rank,
                "composite_alpha": factor.composite,
                "expected_alpha": factor.expected_alpha,
                "base_alpha": factor.expected_alpha,
                "evidence_coverage": factor.evidence_coverage,
                "calibrated_probability": "NOT_CAPTURED",
                "probability_adjustment": 0.0,
                "raw_alpha_target": "NOT_CAPTURED",
                "portfolio_optimized_target": "NOT_CAPTURED",
                "risk_adjusted_target": target_weights.get(factor.symbol),
                "final_trade_target": decision.target_weight if decision else None,
                "current_weight": current_weights.get(factor.symbol, 0.0),
                "target_weight": target_weights.get(factor.symbol),
                "delta_weight": (
                    target_weights[factor.symbol] - current_weights.get(factor.symbol, 0.0)
                    if factor.symbol in target_weights
                    else None
                ),
                "final_action": decision.action if decision else "REJECTED_OR_HOLD",
                "rejection_reason": None if decision else factor.status,
                **probability_counterfactual.get(factor.symbol, {}),
            }
        for symbol, probability_trace in probability_counterfactual.items():
            traces.setdefault(symbol, dict(probability_trace))
        return traces

    @staticmethod
    def _benchmarks(workflow: TodayResult) -> tuple[BenchmarkSummary, ...]:
        rows: list[BenchmarkSummary] = []
        evidence_by_symbol = {item.symbol: item for item in workflow.benchmark_evidences}
        primary = evidence_by_symbol.get(workflow.benchmark_symbol)
        if workflow.benchmark_observations and workflow.benchmark_period_return is not None:
            rows.append(
                BenchmarkSummary(
                    workflow.benchmark_symbol,
                    "PIT PROXY",
                    workflow.benchmark_observations,
                    workflow.benchmark_period_return,
                    workflow.benchmark_annualized_volatility,
                    (
                        "Same PIT return dataset; no unsupported long-horizon "
                        "annualization is shown."
                    ),
                    start_date=primary.start_date if primary else None,
                    end_date=primary.end_date if primary else None,
                    max_drawdown=primary.max_drawdown if primary else None,
                )
            )
        else:
            rows.append(
                BenchmarkSummary(
                    workflow.benchmark_symbol,
                    "UNAVAILABLE",
                    0,
                    None,
                    None,
                    "No certified comparable sample",
                )
            )
        nasdaq_symbol = next(
            (
                item.symbol
                for item in workflow.benchmark_evidences
                if item.symbol != workflow.benchmark_symbol
            ),
            None,
        )
        if nasdaq_symbol is not None:
            evidence = evidence_by_symbol[nasdaq_symbol]
            rows.append(
                BenchmarkSummary(
                    evidence.symbol,
                    "PIT PROXY",
                    evidence.observation_count,
                    evidence.period_return,
                    evidence.annualized_volatility,
                    ("Same PIT return dataset and cutoff as the strategy; Nasdaq-100 proxy."),
                    start_date=evidence.start_date,
                    end_date=evidence.end_date,
                    max_drawdown=evidence.max_drawdown,
                )
            )
        else:
            rows.append(
                BenchmarkSummary(
                    "QQQ",
                    "NOT_AVAILABLE",
                    0,
                    None,
                    None,
                    "Nasdaq-100 proxy not present in the certified PIT universe",
                )
            )
        return tuple(rows)

    @staticmethod
    def _execution_plan(
        workflow: TodayResult,
        decisions: tuple[DecisionRow, ...],
        actionable: bool,
    ) -> ExecutionPlan:
        if not actionable:
            return ExecutionPlan(
                "BLOCKED", True, "Charles Schwab (manual only)", None, 0.0, 0.0, None, None, 0.0, ()
            )
        actionable_rows = tuple(item for item in decisions if item.action != "HOLD")
        priority = {"SELL": 0, "REDUCE": 1, "BUY": 2, "ADD": 3, "INCREASE": 3}
        ordered = sorted(
            actionable_rows,
            key=lambda item: (priority.get(item.action, 9), item.symbol),
        )
        legs = tuple(
            ExecutionLeg(
                index,
                item.symbol,
                item.action,
                item.estimated_value,
                item.estimated_quantity,
                item.estimated_cost,
                item.earliest_execution_time,
            )
            for index, item in enumerate(ordered, start=1)
        )
        proceeds = sum(
            item.estimated_value for item in ordered if item.action in {"SELL", "REDUCE"}
        )
        buys = sum(
            item.estimated_value for item in ordered if item.action in {"BUY", "ADD", "INCREASE"}
        )
        costs = sum(item.estimated_cost for item in ordered)
        cash_before = workflow.cash_balance
        cash_after = cash_before + proceeds - buys - costs if cash_before is not None else None
        return ExecutionPlan(
            "READY" if legs else "NO_ACTION",
            True,
            "Charles Schwab (manual only)",
            cash_before,
            proceeds,
            buys,
            cash_after,
            workflow.target.turnover if workflow.target else 0.0,
            costs,
            legs,
        )

    def _persist_result(self, result: DailyQuantResult) -> DailyQuantResult:
        started = perf_counter()
        try:
            updated = replace(
                result,
                stages=(
                    *result.stages,
                    StageResult(
                        "PERSISTENCE",
                        StageStatus.PASS,
                        0.0,
                        "immutable snapshot and stage evidence saved",
                        {"output_row_count": 1},
                    ),
                ),
                finished_at=datetime.now(UTC),
            )
            certificate = updated.persist_evidence(self._snapshot_root)
            updated = replace(updated, certificate_path=str(certificate.resolve()))
            updated.persist(self._snapshot_root)
            return updated
        except OSError as error:
            blocker = f"decision snapshot persistence failed: {error}"
            return replace(
                result,
                decision_readiness=DecisionReadiness.NOT_ACTIONABLE,
                final_decisions=(),
                execution_plan=replace(result.execution_plan, status="BLOCKED", legs=()),
                blockers=(*result.blockers, blocker),
                stages=(
                    *result.stages,
                    StageResult(
                        "PERSISTENCE", StageStatus.FAIL, perf_counter() - started, blocker, {}
                    ),
                ),
                finished_at=datetime.now(UTC),
            )

    def _finalize_blocked(
        self,
        run_id: str,
        started_at: datetime,
        now: datetime,
        analysis_date: date,
        trade_date: date,
        market_session: str,
        market_structure: str,
        stages: dict[str, StageResult],
        data_health: tuple[DataHealthItem, ...],
        blockers: list[str],
        warnings: list[str],
    ) -> DailyQuantResult:
        data_metadata = stages.get(
            "DATA", StageResult("DATA", StageStatus.NOT_RUN, 0.0, "", {})
        ).metadata
        build = current_build_metadata()
        for name in _STAGE_ORDER:
            if name != "PERSISTENCE" and name not in stages:
                stages[name] = StageResult(
                    name,
                    StageStatus.NOT_RUN,
                    0.0,
                    f"NOT RUN; Blocked by {self._failed_stage(stages)}",
                    {"blocked_by": self._failed_stage(stages)},
                )
        result = DailyQuantResult(
            run_id,
            __version__,
            started_at,
            datetime.now(UTC),
            analysis_date,
            trade_date,
            market_session,
            market_structure,
            self._blocked_data_cutoff(stages),
            DecisionReadiness.NOT_ACTIONABLE,
            self._llm_status(stages),
            self._ordered_stages(stages),
            data_health,
            "UNAVAILABLE",
            "quant stages did not reach a calibrated regime input",
            (),
            (
                ProbabilityRow(
                    "Validated conditional overlay",
                    "base alpha confidence / position cap",
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "INSUFFICIENT EVIDENCE",
                    "NOT CALIBRATED OOS",
                    "NOT_RUN",
                ),
            ),
            (),
            PortfolioSummary(
                (
                    "NOT_INITIALIZED"
                    if any("PORTFOLIO NOT INITIALIZED" in item for item in blockers)
                    else "NOT_CHECKED"
                ),
                None,
                None,
                None,
                None,
                (),
            ),
            RiskSummary(
                "BLOCKED",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                tuple(blockers),
            ),
            (),
            tuple(
                RejectedSignalRow(
                    "ALL",
                    ("PORTFOLIO" if item.startswith("PORTFOLIO ") else self._failed_stage(stages)),
                    item,
                )
                for item in blockers
            ),
            ExecutionPlan(
                "BLOCKED",
                True,
                "Charles Schwab (manual only)",
                None,
                0.0,
                0.0,
                None,
                None,
                0.0,
                (),
            ),
            (),
            tuple(blockers),
            tuple(warnings),
            {
                "automatic_execution": False,
                "manual_broker": "Charles Schwab",
                "build_identifier": build.build_id,
                "git_commit": build.git_commit,
                "build_time": build.build_time,
                "dependency_lock_hash": build.dependency_lock_hash,
                "randomness": "NOT_USED",
                "data_snapshot_id": data_metadata.get("snapshot_id"),
                "data_hash": data_metadata.get("data_hash", "UNAVAILABLE"),
                "data_evidence_paths": data_metadata.get("evidence_paths", {}),
                "pit_cutoff": data_metadata.get("pit_cutoff"),
                "identity_hashes": {
                    "runtime_config_hash": self._effective_config.runtime_config_hash,
                    "strategy_parameter_hash": self._effective_config.strategy_parameter_hash,
                    "data_version_hash": data_metadata.get("data_hash", "UNAVAILABLE"),
                    "portfolio_constraint_hash": self._effective_config.portfolio_constraint_hash,
                    "risk_model_hash": self._effective_config.risk_model_hash,
                    "cost_model_hash": self._effective_config.cost_model_hash,
                    "model_approval_hash": "UNAVAILABLE",
                },
            },
            self._effective_config.canonical_run_config_hash,
            (),
        )
        return self._persist_result(result)

    @staticmethod
    def _blocked_data_cutoff(stages: dict[str, StageResult]) -> datetime | None:
        fallback = StageResult("DATA", StageStatus.NOT_RUN, 0, "", {})
        value = stages.get("DATA", fallback).metadata.get("pit_cutoff")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return None

    def _blocked_result(
        self,
        *,
        run_id: str,
        started_at: datetime,
        now: datetime,
        analysis_date: date,
        trade_date: date,
        market_session: str,
        market_structure: str,
        failed_stage: str,
        reason: str,
        stages: dict[str, StageResult],
    ) -> DailyQuantResult:
        stages[failed_stage] = StageResult(failed_stage, StageStatus.FAIL, 0.0, reason, {})
        return self._finalize_blocked(
            run_id,
            started_at,
            now,
            analysis_date,
            trade_date,
            market_session,
            market_structure,
            stages,
            (),
            [reason],
            [],
        )

    @staticmethod
    def _ordered_stages(stages: dict[str, StageResult]) -> tuple[StageResult, ...]:
        return tuple(stages[name] for name in _STAGE_ORDER if name in stages)

    @staticmethod
    def _llm_status(stages: dict[str, StageResult]) -> str:
        stage = stages.get("LLM_INTELLIGENCE")
        if stage is None:
            return "OPTIONAL_UNAVAILABLE"
        provider = str(stage.metadata.get("provider", "UNAVAILABLE"))
        model = str(stage.metadata.get("model", "UNAVAILABLE"))
        factor_status = str(stage.metadata.get("factor_status", "UNAVAILABLE"))
        return f"{stage.status.value}/{factor_status}/{provider}/{model}"

    @staticmethod
    def _llm_provenance(stages: dict[str, StageResult]) -> str:
        stage = stages.get("LLM_INTELLIGENCE")
        if stage is None:
            return "OPTIONAL_UNAVAILABLE/INFLUENCE_NONE"
        provider = str(stage.metadata.get("provider", "UNAVAILABLE"))
        model = str(stage.metadata.get("model", "UNAVAILABLE"))
        connectivity = str(stage.metadata.get("connectivity", "NOT_TESTED"))
        influence = "NONE" if not stage.metadata.get("production_influence") else "INVALID"
        return f"{provider}/{model}/{connectivity}/INFLUENCE_{influence}"

    @staticmethod
    def _metadata_count(payload: dict[str, object], key: str) -> int:
        value = payload.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _missing_ratio(manifest: object | None) -> float | None:
        summary = getattr(manifest, "missingness_summary", None)
        if not isinstance(summary, dict):
            return None
        value = summary.get("overall")
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _failed_stage(stages: dict[str, StageResult]) -> str:
        return next(
            (
                name
                for name in _STAGE_ORDER
                if stages.get(name) and stages[name].status is StageStatus.FAIL
            ),
            "GATE",
        )

    def _config_fingerprint(self) -> str:
        return self._effective_config.canonical_run_config_hash
