from __future__ import annotations

import json as _json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal import __version__
from personal_alpha_terminal.agents.llm.factory import build_llm_provider
from personal_alpha_terminal.agents.llm.providers import DeepSeekProvider, LLMProvider
from personal_alpha_terminal.ai_advisory import (
    PRODUCTION_INFLUENCE,
    build_quant_facts,
)
from personal_alpha_terminal.application.agentic_shadow_service import (
    AgenticShadowEvidence,
    load_agentic_shadow_evidence,
)
from personal_alpha_terminal.application.current_exposure import (
    acquire_current_sec_sic,
    acquire_current_size_observations,
    build_current_sector_exposure,
    build_current_size_exposure,
)
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
from personal_alpha_terminal.application.decision_manifest import (
    RunIdentity,
    seal_decision_manifest,
)
from personal_alpha_terminal.application.etf_sleeve_service import (
    EtfSleeveApplicationService,
)
from personal_alpha_terminal.application.forward_evidence import (
    AgenticForwardEvidenceLedger,
    EvidenceOrigin,
    append_daily_shadow_evidence,
    evaluate_runtime_promotion,
)
from personal_alpha_terminal.application.intelligence_service import (
    IntelligenceApplicationService,
)
from personal_alpha_terminal.application.pre_execution import (
    PreExecutionCheck,
    build_assessment,
    check_halts_and_corporate_events,
    check_market_gap,
    check_overnight_news,
    check_stale_market_data,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
    TodayResult,
)
from personal_alpha_terminal.application.size_diagnostics import (
    build_size_tilt_diagnostic,
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
from personal_alpha_terminal.intelligence.market_news import (
    NewsIntelligenceService,
    NewsLedger,
    materialize_news_facts,
    news_item_from_document,
)
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models import Portfolio, Price, SecurityMaster
from personal_alpha_terminal.models.intelligence import (
    IntelligenceEvent,
    IntelligenceExtractionCache,
    IntelligenceFeature,
    IntelligenceRawInformation,
    IntelligenceResearchResult,
)
from personal_alpha_terminal.probability.forward_ledger import (
    ProbabilityForwardLedger,
    build_prediction,
)
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSessionCalendar,
    MarketSessionState,
)

_STAGE_ORDER = (
    "CALENDAR",
    "DATA",
    "PIT",
    "LLM_INTELLIGENCE",
    "ETF_SLEEVE",
    "AI_BRIEF",
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
        shadow_llm_provider_factory: Callable[[], LLMProvider] | None = None,
    ) -> None:
        self._factory = session_factory
        if isinstance(effective_config, Settings):
            effective_config = effective_config_from_settings(effective_config)
        self._effective_config = effective_config
        self._settings = effective_config.settings
        self._snapshot_root = snapshot_root or (effective_config.report_dir / "daily-runs")
        self._sync_runner = sync_runner
        self._llm_runtime_status_path = llm_runtime_status_path
        self._shadow_llm_provider_factory = shadow_llm_provider_factory
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
        progress: Callable[[str], None] | None = None,
    ) -> DailyQuantResult:
        started_at = datetime.now(UTC)
        run_id = f"daily-{uuid4().hex}"
        run_identity = RunIdentity.create(run_id)
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
            analysis_date = self._analysis_date(market)
            trade_date = market.trade_date
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
        _data_segment_log: list[tuple[str, float]] = []

        def _segment(name: str, started: float) -> None:
            _data_segment_log.append((name, round(perf_counter() - started, 4)))

        try:
            _seg = perf_counter()
            with self._factory.begin() as session:
                _segment("session_begin", _seg)
                _seg = perf_counter()
                data_service = DataService(
                    session,
                    self._settings,
                    snapshot_root=self._snapshot_root.parent / "data-snapshots",
                    sync_runner=self._sync_runner,
                )
                _segment("data_service_init", _seg)
                if refresh:
                    if progress is not None:
                        progress("[\u5e02\u573a\u6570\u636e] \u5237\u65b0\u4e2d")
                    sync = data_service.sync_market_data(
                        start_date=data_service.refresh_start_date(analysis_date=analysis_date),
                        end_date=analysis_date,
                        progress=progress,
                    )
                    if progress is not None:
                        progress("[\u5e02\u573a\u6570\u636e] \u5237\u65b0\u5b8c\u6210")
                    if sync.status == "BLOCKED":
                        data_failure_reasons.append(
                            "required provider refresh failed: " + ", ".join(sync.failed_symbols)
                        )
                    if sync.status != "CERTIFIED" and sync.status != "BLOCKED":
                        warnings.append(
                            "live refresh completed with quarantined symbols; "
                            "certification evidence is recorded in the DATA stage"
                        )
                    if decision_time is None:
                        # A live decision can only occur after the newly retrieved evidence
                        # exists.  Calendar/trade-date resolution remains anchored to run start.
                        effective_decision_time = datetime.now(UTC)
                _seg = perf_counter()
                readiness = data_service.get_data_readiness(as_of=effective_decision_time)
                _segment("get_data_readiness", _seg)
                _seg = perf_counter()
                manifest = data_service.latest_manifest()
                _segment("latest_manifest", _seg)
                _seg = perf_counter()
                certification = data_service.daily_certification(
                    analysis_date=analysis_date,
                    decision_time=effective_decision_time,
                )
                _segment("daily_certification_1", _seg)
                if certification.latest_completed_session is not None:
                    resolved_analysis = certification.latest_completed_session
                    if resolved_analysis != analysis_date:
                        analysis_date = resolved_analysis
                        trade_date = self._calendar.next_trading_day(analysis_date)
                    _seg = perf_counter()
                    certification = data_service.daily_certification(
                        analysis_date=analysis_date,
                        decision_time=effective_decision_time,
                    )
                    _segment("daily_certification_2", _seg)
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
                    "data_stage_profile": (
                        data_service.profile_document()
                        if hasattr(data_service, "profile_document")
                        else {}
                    ),
                    "data_stage_segments": dict(_data_segment_log),
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
                trade_date,
                market.session.value,
                market.structure_version.value,
                stages,
                data_health,
                blockers,
                warnings,
            )

        stage_started = perf_counter()
        if progress is not None:
            progress("[PIT] \u80a1\u7968\u6c60\u6784\u5efa\u4e2d")
        with self._factory.begin() as session:
            workflow_result = ProductionDailyWorkflow(session, self._effective_config).run(
                portfolio_id=resolved_portfolio,
                decision_time=effective_decision_time,
                analysis_date=analysis_date,
                run_identity=run_identity,
            )
        quant_duration = perf_counter() - stage_started
        self._merge_quant_stages(stages, workflow_result, quant_duration)
        if progress is not None:
            progress("[FACTOR] \u8ba1\u7b97\u5b8c\u6210")
        stage_started = perf_counter()
        self._add_llm_intelligence_stage(
            stages,
            as_of=effective_decision_time,
            duration_started=stage_started,
            warnings=warnings,
            run_id=run_id,
            eligible_symbols=tuple(item.symbol for item in workflow_result.factors),
        )
        stage_started = perf_counter()
        etf_universe, etf_targets, etf_composition = self._add_etf_sleeve_stage(
            stages,
            as_of=effective_decision_time,
            duration_started=stage_started,
            analysis_date=analysis_date,
            workflow_result=workflow_result,
        )
        current_exposure = self._build_current_exposure(
            workflow_result=workflow_result,
            decision_as_of=effective_decision_time,
        )
        current_exposure = current_exposure or {}
        stage_started = perf_counter()
        ai_brief = self._add_ai_brief_stage(
            stages,
            as_of=effective_decision_time,
            duration_started=stage_started,
            run_id=run_id,
            run_identity=run_identity,
            workflow_result=workflow_result,
            etf_evidence={
                "counts": etf_universe,
                "targets": list(etf_targets),
                "composition": etf_composition,
            },
            current_exposure=current_exposure,
        )
        from personal_alpha_terminal.application.hybrid_intelligence_service import (
            build_shadow_hybrid_document,
        )

        shadow_evidence = AgenticShadowEvidence(companies={})
        try:
            with self._factory.begin() as session:
                pit_events = IntelligenceRepository(session).visible_events(
                    effective_decision_time
                )
                shadow_evidence = load_agentic_shadow_evidence(
                    session,
                    events=pit_events,
                    eligible_symbols=tuple(
                        item.symbol for item in workflow_result.factors
                    ),
                    decision_time=effective_decision_time,
                )
            provider_name, _, configured, _ = self._configured_llm_identity()
            shadow_provider = (
                self._shadow_llm_provider_factory()
                if self._shadow_llm_provider_factory is not None
                else build_llm_provider(
                    self._settings.model_copy(
                        update={"llm_provider": provider_name}
                    )
                )
                if configured
                else None
            )
            hybrid_intelligence = build_shadow_hybrid_document(
                workflow=workflow_result,
                llm_stage=stages.get("LLM_INTELLIGENCE"),
                evidence=shadow_evidence,
                provider=shadow_provider,
                effective_config=self._effective_config,
            )
        except Exception as error:
            warnings.append(
                "Agentic Shadow degraded "
                f"({type(error).__name__}); Quant production output is unchanged"
            )
            hybrid_intelligence = build_shadow_hybrid_document(
                workflow=workflow_result,
                llm_stage=stages.get("LLM_INTELLIGENCE"),
                evidence=AgenticShadowEvidence(companies={}),
                provider=None,
                effective_config=self._effective_config,
            )
            degradation = hybrid_intelligence.get("degradation")
            if isinstance(degradation, dict):
                degradation["pipeline_failure"] = type(error).__name__
        llm_stage = stages.get("LLM_INTELLIGENCE")
        if llm_stage is not None:
            counts = hybrid_intelligence.get("counts")
            metrics = counts if isinstance(counts, dict) else {}
            raw_inferences = hybrid_intelligence.get("llm_inferences")
            inference_count = len(raw_inferences) if isinstance(raw_inferences, list) else 0
            stages["LLM_INTELLIGENCE"] = replace(
                llm_stage,
                metadata={
                    **llm_stage.metadata,
                    "shadow_thesis_calls": inference_count,
                    "real_structured_theses": self._metadata_count(
                        metrics, "real_structured_theses"
                    ),
                    "real_shadow_llm_decisions": self._metadata_count(
                        metrics, "real_shadow_llm_decisions"
                    ),
                    "hybrid_counterfactual_executed": self._metadata_count(
                        metrics, "hybrid_counterfactual_executed"
                    ),
                    "production_influence": False,
                },
            )
        try:
            with self._factory.begin() as session:
                forward_counts = append_daily_shadow_evidence(
                    session,
                    workflow=workflow_result,
                    hybrid_document=hybrid_intelligence,
                    evidence=shadow_evidence,
                    run_id=run_id,
                    decision_id=run_identity.decision_id,
                    evidence_origin=self._agentic_evidence_origin(
                        hybrid_intelligence
                    ),
                )
                ledger = AgenticForwardEvidenceLedger(session)
                promotion = evaluate_runtime_promotion(
                    ledger,
                    evaluated_at=effective_decision_time,
                    evaluation_id=f"promotion-{run_id}",
                )
                promotion_added = ledger.append_promotion_evaluation(promotion)
            forward_counts["promotion_evaluations"] = int(promotion_added)
            hybrid_intelligence["forward_evidence_persistence"] = forward_counts
            hybrid_intelligence["promotion"] = promotion.model_dump(mode="json")
            hybrid_status = hybrid_intelligence.get("status")
            if isinstance(hybrid_status, dict):
                hybrid_status["promotion_gate"] = promotion.reason_codes[0]
        except Exception as error:
            warnings.append(
                "Agentic forward evidence persistence degraded "
                f"({type(error).__name__}); production Quant output is unchanged"
            )
            hybrid_intelligence["forward_evidence_persistence"] = {
                "predictions": 0,
                "counterfactuals": 0,
                "promotion_evaluations": 0,
                "error": type(error).__name__,
            }
            hybrid_intelligence["promotion"] = {
                "status": "BLOCKED",
                "promotion_reason": "PROMOTION_EVALUATION_FAILED",
                "reason_codes": ["PROMOTION_EVALUATION_FAILED"],
                "real_forward_n": 0,
                "minimum_required_n": 120,
                "paired_sample_n": 0,
                "production_lambda": 0.0,
                "human_approval_required": True,
                "error": type(error).__name__,
            }
            hybrid_status = hybrid_intelligence.get("status")
            if isinstance(hybrid_status, dict):
                hybrid_status["promotion_gate"] = "PROMOTION_EVALUATION_FAILED"
        self._record_probability_predictions(
            workflow_result=workflow_result,
            run_identity=run_identity,
            # The frozen decision cutoff is a property of the certified
            # analysis inputs, never the wall-clock time a report was
            # regenerated.  Using the latter would fabricate a new OOS
            # observation on every same-day rerun.
            decision_as_of=workflow_result.data_cutoff or effective_decision_time,
            trade_date=trade_date,
        )
        stage_started = perf_counter()
        pre_execution = self._add_pre_execution_stage(
            stages,
            as_of=effective_decision_time,
            duration_started=stage_started,
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
            trade_date=trade_date,
            market_session=market.session.value,
            market_structure=market.structure_version.value,
            stages=stages,
            data_health=data_health,
            workflow=workflow_result,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            etf_universe=etf_universe,
            etf_targets=etf_targets,
            etf_composition=etf_composition,
            ai_brief=ai_brief,
            pre_execution=pre_execution,
            run_identity=run_identity,
            current_exposure=current_exposure,
            hybrid_intelligence=hybrid_intelligence,
        )
        if result.decision_manifest is not None:
            try:
                from personal_alpha_terminal.application.run_bundle import (
                    RunBundleStore,
                    finalize_run_bundle,
                )

                sealed = finalize_run_bundle(
                    store=RunBundleStore(
                        self._effective_config.report_dir / "evidence-bundles"
                    ),
                    run_id=run_id,
                    decision_manifest=result.decision_manifest,
                )
                if isinstance(result.decision_provenance, dict):
                    result.decision_provenance["evidence_bundle"] = sealed
            except (FileNotFoundError, RuntimeError, ValueError):
                # The staged bundle is sealed lazily; a missing or invalid stage
                # is surfaced through the certificate provenance below rather
                # than aborting an already-computed decision.
                pass
        return self._persist_result(result)

    def _record_probability_predictions(
        self,
        *,
        workflow_result: TodayResult,
        run_identity: RunIdentity | None,
        decision_as_of: datetime,
        trade_date: date,
    ) -> None:
        """ROUND26 P0: immutable forward probability predictions.

        One prediction per formal recommendation is appended at decision time
        (before any outcome is observable).  With the current fallback model
        every prediction records raw/calibrated probability None and state
        CLASSICAL_FALLBACK -- an honest forward baseline, not fabricated
        calibration.
        """

        if run_identity is None or not workflow_result.recommendations:
            return
        market_data_semantic_hash = fingerprint(
            {
                "schema": "forward-prediction-market-input-v1",
                "decision_cutoff": decision_as_of,
                "analysis_factors": [
                    {
                        "symbol": item.symbol,
                        "components": item.components,
                        "raw_values": item.raw_values,
                        "winsorized_values": item.winsorized_values,
                        "neutralized_values": item.neutralized_values,
                        "expected_alpha": item.expected_alpha,
                    }
                    for item in sorted(workflow_result.factors, key=lambda item: item.symbol)
                ],
                "benchmark": workflow_result.benchmark_symbol,
            }
        )
        overlay = {
            item.symbol: item
            for item in workflow_result.probability_overlay_effects
        }
        # Keep forward evidence alongside the active run root.  Production's
        # default ``reports/daily-runs`` resolves to ``var/probability-forward``;
        # isolated/replay/test snapshot roots cannot contaminate that live
        # append-only ledger.
        ledger = ProbabilityForwardLedger(
            self._snapshot_root.parent.parent / "var" / "probability-forward"
        )
        try:
            for rank, recommendation in enumerate(
                sorted(
                    workflow_result.recommendations,
                    key=lambda item: (-item.expected_alpha, item.symbol),
                ),
                start=1,
            ):
                effect = overlay.get(recommendation.symbol)
                ledger.append_prediction(
                    build_prediction(
                        run_id=run_identity.run_id,
                        decision_id=run_identity.decision_id,
                        ticker=recommendation.symbol,
                        decision_cutoff=decision_as_of,
                        factor_rank=rank,
                        base_alpha=recommendation.expected_alpha,
                        raw_probability=(
                            float(effect.posterior_probability)
                            if effect is not None
                            and effect.posterior_probability is not None
                            else None
                        ),
                        calibrated_probability=(
                            float(effect.posterior_probability)
                            if effect is not None
                            and effect.posterior_probability is not None
                            else None
                        ),
                        model_id=str(
                            workflow_result.probability_artifact_id
                        ),
                        model_hash=str(
                            (workflow_result.identity_hashes or {}).get(
                                "probability_artifact_hash", "UNAVAILABLE"
                            )
                        ),
                        cost_hurdle_bps=float(
                            self._effective_config.transaction_cost.commission_bps
                            + self._effective_config.transaction_cost.spread_bps
                            + self._effective_config.transaction_cost.slippage_bps
                        ),
                        condition_state=(
                            "CALIBRATED_OVERLAY"
                            if workflow_result.probability_overlay_active
                            else "CLASSICAL_FALLBACK"
                        ),
                        trade_date=trade_date.isoformat(),
                        market_data_semantic_hash=market_data_semantic_hash,
                        universe_semantic_hash=str(
                            (workflow_result.universe_evidence or {}).get(
                                "universe_hash", workflow_result.universe_snapshot_id
                            )
                        ),
                        portfolio_predecision_hash=str(
                            workflow_result.portfolio_snapshot_id
                        ),
                        run_type="PRODUCTION_DECISION",
                    )
                )
        except (OSError, ValueError):
            # Forward-ledger writes are research-only; a failed append must
            # never block the production chain.
            return

    def _build_current_exposure(
        self,
        *,
        workflow_result: TodayResult,
        decision_as_of: datetime,
    ) -> dict[str, object] | None:
        """ROUND26 P0: current operational size/sector exposure evidence."""

        symbols = tuple(
            item.symbol for item in workflow_result.recommendations if item.symbol
        )
        if not symbols:
            return None
        try:
            current_observations, size_acquisition = acquire_current_size_observations(
                symbols=symbols, as_of=decision_as_of
            )
            with self._factory.begin() as session:
                size = build_current_size_exposure(
                    session,
                    as_of=decision_as_of,
                    target_symbols=symbols,
                    current_observations=current_observations,
                )
                security_types = {
                    str(symbol): str(asset_type)
                    for symbol, asset_type in session.execute(
                        select(SecurityMaster.symbol, SecurityMaster.asset_type).where(
                            SecurityMaster.symbol.in_(symbols)
                        )
                    ).all()
                }
        except (OSError, SQLAlchemyError, ValueError):
            size = {
                "exposure_kind": "CURRENT_OPERATIONAL",
                "status": "SIZE_RISK_DEGRADED",
                "size_coverage": 0.0,
                "portfolio_unknown_size_weight": 1.0,
                "missing_never_assumed_large_cap": True,
                "detail": "size evidence unavailable; honest degraded status",
            }
            size_acquisition = {"status": "UNAVAILABLE"}
            security_types = {symbol: "UNKNOWN" for symbol in symbols}
        sector_rows, sector_acquisition = acquire_current_sec_sic(
            symbols=symbols, security_types=security_types
        )
        sector = build_current_sector_exposure(
            sector_rows=sector_rows,
            target_symbols=symbols,
            classification_source="SEC_SIC",
        )
        return {
            "size_exposure": size,
            "sector_exposure": sector,
            "exposure_kind": "CURRENT_OPERATIONAL",
            "historical_pit_boundary": "CURRENT DATA NEVER USED FOR HISTORICAL NEUTRALIZATION",
            "size_acquisition": size_acquisition,
            "sector_acquisition": sector_acquisition,
        }

    def _add_etf_sleeve_stage(
        self,
        stages: dict[str, StageResult],
        *,
        as_of: datetime,
        duration_started: float,
        analysis_date: date,
        workflow_result: TodayResult,
    ) -> tuple[dict[str, object], tuple[dict[str, object], ...], dict[str, object] | None]:
        """ROUND24 ETF multi-sleeve stage; additive, never blocks equity path."""

        enabled = bool(
            getattr(self._effective_config, "etf_sleeves_enabled", False)
            or self._settings.etf_sleeves_enabled
        )
        if not enabled:
            stages["ETF_SLEEVE"] = StageResult(
                "ETF_SLEEVE",
                StageStatus.OPTIONAL_UNAVAILABLE,
                perf_counter() - duration_started,
                "ETF sleeves disabled by configuration",
                {
                    "enabled": False,
                    "output_row_count": 0,
                    "model_status": "RESEARCH_CANDIDATE",
                },
            )
            return {}, (), None
        try:
            with self._factory.begin() as session:
                service = EtfSleeveApplicationService(
                    session, self._effective_config
                )
                if workflow_result.target is not None:
                    equity_weights = {
                        symbol: weight
                        for symbol, weight in (
                            workflow_result.target.target_weights.items()
                        )
                        if weight > 0
                    }
                else:
                    equity_weights = {
                        item.symbol: item.target_weight
                        for item in workflow_result.recommendations
                        if item.target_weight > 0
                    }
                current_weights = {
                    item.symbol: item.current_weight
                    for item in workflow_result.recommendations
                }
                portfolio_value = (
                    workflow_result.portfolio_value
                    if workflow_result.portfolio_value is not None
                    and workflow_result.portfolio_value > 0
                    else 100_000.0
                )
                outcome = service.run(
                    universe_date=analysis_date,
                    decision_time=as_of,
                    equity_weights=equity_weights,
                    current_weights=current_weights,
                    portfolio_value=portfolio_value,
                )
            evidence = outcome.evidence()
            counts = cast(dict[str, object], evidence.get("counts", {}))
            core_docs = cast(
                tuple[dict[str, object], ...], evidence.get("core_targets", ())
            )
            tactical_docs = cast(
                tuple[dict[str, object], ...], evidence.get("tactical_targets", ())
            )
            targets = tuple(
                {**item, "instrument_type": "ETF"}
                for item in (*core_docs, *tactical_docs)
            )
            tradable = counts.get("tradable_eligible")
            status = (
                StageStatus.PASS if tradable else StageStatus.PASS_DEGRADED
            )
            stages["ETF_SLEEVE"] = StageResult(
                "ETF_SLEEVE",
                status,
                perf_counter() - duration_started,
                (
                    f"ETF sleeves evaluated: core {counts.get('core_eligible', 0)}, "
                    f"tactical {counts.get('tactical_eligible', 0)}, "
                    f"blocked complex {counts.get('blocked_complex', 0)}"
                ),
                {
                    "enabled": True,
                    "model_status": "RESEARCH_CANDIDATE",
                    "look_through": "UNAVAILABLE",
                    "counts": counts,
                    "warnings": list(
                        cast(tuple[str, ...], evidence.get("warnings", ()))
                    ),
                    "output_row_count": len(targets),
                },
            )
            return (
                dict(counts),
                targets,
                (
                    cast(dict[str, object], evidence.get("composition"))
                    if isinstance(evidence.get("composition"), dict)
                    else None
                ),
            )
        except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
            stages["ETF_SLEEVE"] = StageResult(
                "ETF_SLEEVE",
                StageStatus.OPTIONAL_UNAVAILABLE,
                perf_counter() - duration_started,
                (
                    f"ETF sleeve evaluation unavailable ({type(error).__name__}); "
                    "equity path unchanged"
                ),
                {
                    "enabled": True,
                    "model_status": "RESEARCH_CANDIDATE",
                    "output_row_count": 0,
                    "error": str(error),
                },
            )
            return {}, (), None

    def _add_ai_brief_stage(
        self,
        stages: dict[str, StageResult],
        *,
        as_of: datetime,
        duration_started: float,
        run_id: str,
        run_identity: RunIdentity | None = None,
        workflow_result: TodayResult,
        etf_evidence: dict[str, object],
        current_exposure: dict[str, object],
    ) -> dict[str, object] | None:
        """ROUND24 AI Chinese advisory brief stage (B1-B9)."""

        enabled = bool(
            getattr(self._effective_config, "ai_brief_enabled", False)
            or self._settings.ai_brief_enabled
        )
        if not enabled:
            stages["AI_BRIEF"] = StageResult(
                "AI_BRIEF",
                StageStatus.OPTIONAL_UNAVAILABLE,
                perf_counter() - duration_started,
                "AI Chinese brief disabled by configuration",
                {
                    "enabled": False,
                    "production_influence": "NONE",
                    "output_row_count": 0,
                },
            )
            return None
        provider, model, configured, connectivity = self._configured_llm_identity()
        try:
            with self._factory.begin() as session:
                events = tuple(
                    {
                        "event_id": str(item.event_id),
                        "symbol": item.symbol,
                        "event_type": item.event_type,
                        "effective_at": (
                            item.effective_at.isoformat()
                            if item.effective_at is not None
                            else None
                        ),
                        "observed_at": (
                            item.observed_at.isoformat()
                            if item.observed_at is not None
                            else None
                        ),
                        "payload": item.payload,
                    }
                    for item in session.scalars(
                        select(IntelligenceEvent)
                        .where(
                            IntelligenceEvent.observed_at <= as_of,
                            IntelligenceEvent.data_cutoff <= as_of,
                            IntelligenceEvent.symbol.is_not(None),
                        )
                        .order_by(IntelligenceEvent.effective_at.desc())
                        .limit(50)
                    )
                )
            decision_id = (
                run_identity.decision_id
                if run_identity is not None
                else f"decision-{run_id.removeprefix('daily-')}"
            )
            certificate_view = {
                "run_id": run_id,
                "decision_id": decision_id,
                "analysis_date": workflow_result.decision_time.date().isoformat(),
                "trade_date": workflow_result.decision_time.date().isoformat(),
                "market_session": workflow_result.market_session,
                "warnings": list(workflow_result.warnings),
                "llm_mode": "SHADOW",
                "probability_mode": "PROBABILITY_FALLBACK_CLASSICAL",
                "probability_influence": 0.0,
                "operational_authorization": (
                    workflow_result.operational_policy_decision
                ),
                "signal_authorization_class": workflow_result.signal_authorization_class,
                "research_certification_state": workflow_result.research_certification_state,
                "auto_execution": False,
                "broker_api": "DISABLED",
                "manual_execution_only": True,
                "data": [
                    {
                        "dataset": "CERTIFIED_US_UNIVERSE",
                        "member_count": workflow_result.universe_count,
                    }
                ],
                "decision_recommendations": [
                    {
                        "symbol": item.symbol,
                        "instrument_type": "COMMON_STOCK",
                        "sleeve": "EQUITY_ALPHA",
                        "action": item.action,
                        "current_weight": item.current_weight,
                        "target_weight": item.target_weight,
                        "expected_alpha": item.expected_alpha,
                        "risk_contribution": item.risk_contribution,
                        "estimated_cost": item.expected_cost,
                        "estimated_value": item.estimated_value,
                        "data_quality": item.data_quality,
                        "reason": item.reason,
                    }
                    for item in workflow_result.recommendations
                ],
                "factor_count": len(workflow_result.factors),
                "candidate_count": len(workflow_result.recommendations),
                "benchmarks": [
                    {
                        "symbol": item.symbol,
                        "period_return": item.period_return,
                        "annualized_volatility": item.annualized_volatility,
                        "observations": item.observation_count,
                    }
                    for item in workflow_result.benchmark_evidences
                ],
                "portfolio": {
                    "total_value": workflow_result.portfolio_value,
                    "cash_balance": workflow_result.cash_balance,
                },
                "risk": (
                    {
                        "current_drawdown": (
                            workflow_result.risk_state.current_drawdown
                        ),
                        "rolling_volatility": (
                            workflow_result.risk_state.rolling_volatility
                        ),
                        "portfolio_beta": workflow_result.risk_state.portfolio_beta,
                        "concentration_hhi": (
                            workflow_result.risk_state.concentration_hhi
                        ),
                    }
                    if workflow_result.risk_state is not None
                    else {}
                ),
                "etf_evidence": etf_evidence,
            }
            facts, data_gaps = build_quant_facts(
                run_certificate=certificate_view,
                pit_events=events,
                etf_evidence=etf_evidence,
                decision_as_of=as_of,
            )
            facts["data_gaps"] = data_gaps
            facts["current_exposure"] = current_exposure
            provider_factory = None
            if configured:
                provider_factory = lambda: DeepSeekProvider(  # noqa: E731
                    api_key=cast(str, self._settings.deepseek_api_key),
                    model=model,
                    timeout_seconds=self._settings.llm_timeout_seconds,
                    max_retries=self._settings.llm_max_retries,
                    base_url=self._settings.deepseek_base_url,
                )
            market_state_doc: dict[str, object] | None = None
            try:
                from personal_alpha_terminal.application.market_state import (
                    build_market_state_snapshot,
                )

                with self._factory.begin() as session:
                    snapshot = build_market_state_snapshot(session, as_of=as_of)
                if snapshot is not None:
                    market_state_doc = snapshot.document()
            except (OSError, SQLAlchemyError, ValueError):
                market_state_doc = None
            news_doc: dict[str, object] | None = None
            news_network_seconds = 0.0
            try:
                from personal_alpha_terminal.intelligence.macro_news import (
                    OfficialMacroAcquisition,
                )

                news_started = perf_counter()
                macro = OfficialMacroAcquisition().acquire()
                news_network_seconds = perf_counter() - news_started
                raw_macro_items = macro.get("items")
                macro_rows = raw_macro_items if isinstance(raw_macro_items, list) else []
                macro_items = tuple(
                    item
                    for row in macro_rows
                    if isinstance(row, dict)
                    for item in [news_item_from_document(row)]
                    if item is not None
                )
                ledger = NewsLedger()
                ledger.append_items(macro_items)
                general = NewsIntelligenceService().acquire(
                    decision_as_of=as_of,
                    providers={},
                ).document()
                formal_symbols = tuple(
                    str(item.get("symbol"))
                    for item in (facts.get("formal_actions") or [])
                    if isinstance(item, dict) and item.get("symbol")
                )
                news_facts = materialize_news_facts(
                    rows=ledger.load_items(),
                    decision_as_of=as_of,
                    formal_symbols=formal_symbols,
                )
                news_doc = {
                    "macro_news": [item.document() for item in macro_items],
                    "general_status": general.get("status"),
                    **news_facts,
                    "provider_statuses": macro.get("provider_statuses"),
                    "fabricated": False,
                }
            except (OSError, ValueError, TimeoutError):
                news_doc = {
                    "clusters": [],
                    "status": "OFFICIAL_MACRO_NEWS_UNAVAILABLE",
                    "fabricated": False,
                }
            from personal_alpha_terminal.ai_advisory.action_commentary import (
                build_deterministic_action_commentaries,
                build_deterministic_devils_advocate,
                build_deterministic_portfolio_review,
            )
            from personal_alpha_terminal.intelligence.company_dossier import (
                build_company_dossiers,
            )

            dossiers = build_company_dossiers(
                symbols=tuple(
                    str(item.get("symbol"))
                    for item in (facts.get("formal_actions") or [])
                    if isinstance(item, dict) and item.get("symbol")
                ),
                current_exposure=current_exposure,
                as_of=as_of,
            )
            dossier_map = {item.ticker: item.document() for item in dossiers}
            facts["company_dossiers"] = dossier_map
            facts["action_commentaries"] = build_deterministic_action_commentaries(
                facts=facts,
                dossiers=dossier_map,
                news=news_doc,
            )
            facts["portfolio_review"] = build_deterministic_portfolio_review(
                facts=facts,
                dossiers=dossier_map,
            )
            facts["devils_advocate"] = build_deterministic_devils_advocate(
                facts=facts,
                news=news_doc,
            )
            from personal_alpha_terminal.ai_advisory.brief_v2 import AiBriefV2Service

            v2_service = AiBriefV2Service()
            # ROUND26 P0: the decision manifest hash does not exist yet at AI
            # brief time (two-phase identity); the brief cites only run:/
            # decision: identities which already exist.  The sealed manifest
            # is attached to the final certificate.
            brief_result = v2_service.generate(
                run_id=run_id,
                facts=facts,
                model=model,
                provider_factory=provider_factory,
                market_state=market_state_doc,
                news=news_doc,
                decision_manifest=None,
            )
            stages["AI_BRIEF"] = StageResult(
                "AI_BRIEF",
                (
                    StageStatus.PASS
                    if brief_result.llm_status == "PASS"
                    else StageStatus.PASS_DEGRADED
                ),
                perf_counter() - duration_started,
                f"AI Chinese brief v2 {brief_result.source}",
                {
                    "enabled": True,
                    "provider": provider,
                    "model": model,
                    "connectivity": connectivity,
                    "schema_version": "ai-brief-zh-v2",
                    "llm_status": brief_result.llm_status,
                    "source": brief_result.source,
                    "cache_hit": False,
                    "llm_calls": brief_result.usage.get("total_calls", 0),
                    "prompt_tokens": brief_result.usage.get("prompt_tokens", 0),
                    "completion_tokens": brief_result.usage.get("completion_tokens", 0),
                    "semantic_grounding_status": (
                        brief_result.semantic_grounding_status
                    ),
                    "section_report": brief_result.section_report,
                    "ai_status": brief_result.ai_status,
                    "deepseek_sections_used": brief_result.document().get(
                        "deepseek_sections_used", 0
                    ),
                    "deepseek_sections_total": brief_result.document().get(
                        "deepseek_sections_total", 5
                    ),
                    "fallback_sections": brief_result.document().get(
                        "fallback_sections", []
                    ),
                    "news": {
                        key: (news_doc or {}).get(key, 0)
                        for key in (
                            "raw_news_rows",
                            "normalized_news_rows",
                            "cluster_count",
                            "pre_decision_news_count",
                            "post_decision_pre_execution_count",
                            "post_execution_count",
                            "unknown_timestamp_count",
                            "ai_used_rows",
                            "terminal_displayed_rows",
                        )
                    },
                    "news_network_seconds": round(news_network_seconds, 4),
                    "llm_network_seconds": round(
                        float(brief_result.usage.get("latency_ms", 0)) / 1000.0,
                        4,
                    ),
                    "production_influence": PRODUCTION_INFLUENCE,
                    "trade_authority": "NONE",
                    "target_weight_authority": "NONE",
                    "buy_sell_authority": "NONE",
                    "output_row_count": (
                        len(brief_result.brief.get("formal_action_explanations", []))
                    ),
                },
            )
            return brief_result.document()
        except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
            stages["AI_BRIEF"] = StageResult(
                "AI_BRIEF",
                StageStatus.PASS_DEGRADED,
                perf_counter() - duration_started,
                f"AI Chinese brief degraded ({type(error).__name__}); Classical pipeline unchanged",
                {
                    "enabled": True,
                    "provider": provider,
                    "model": model,
                    "llm_status": "PASS_DEGRADED",
                    "production_influence": PRODUCTION_INFLUENCE,
                    "error": str(error),
                    "output_row_count": 0,
                },
            )
            return None

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

    def _agentic_evidence_origin(
        self,
        hybrid_document: dict[str, object],
    ) -> EvidenceOrigin:
        status = hybrid_document.get("status")
        status_payload = status if isinstance(status, dict) else {}
        provider = str(status_payload.get("provider", "UNAVAILABLE")).casefold()
        if provider == "mock":
            return "MOCK"
        if self._settings.app_env == "test" or self._settings.runtime_profile == "TEST":
            return "TEST"
        if (
            self._settings.app_env != "production"
            or self._settings.runtime_profile != "PRODUCTION_DESKTOP"
        ):
            return "NON_PRODUCTION"
        if provider not in {"openai", "deepseek", "anthropic", "custom"}:
            return "NON_PRODUCTION"
        return "REAL_FORWARD"

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

    def _analysis_date(self, market: MarketSessionState) -> date:
        return self._calendar.completed_session_date(market.timestamp_utc)

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
        etf_universe: dict[str, object] | None = None,
        etf_targets: tuple[dict[str, object], ...] = (),
        etf_composition: dict[str, object] | None = None,
        ai_brief: dict[str, object] | None = None,
        pre_execution: dict[str, object] | None = None,
        run_identity: RunIdentity | None = None,
        current_exposure: dict[str, object] | None = None,
        hybrid_intelligence: dict[str, object] | None = None,
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
        size_diagnostics = (
            build_size_tilt_diagnostic(
                workflow.risk,
                candidate_symbols=self._candidate_symbols(workflow.universe_evidence),
                target_weights=target_weights,
                portfolio_value=(
                    workflow.portfolio_value
                    if workflow.portfolio_value is not None
                    and workflow.portfolio_value > 0
                    else 0.0
                ),
                transaction_cost=self._effective_config.transaction_cost,
                expected_transaction_cost=(
                    target.estimated_transaction_cost if target is not None else 0.0
                ),
            )
            if workflow.risk is not None
            else {}
        )
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
            size_diagnostics,
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
                confidence_source=item.confidence_source,
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
        candidate_count = int(
            str(
                workflow.universe_evidence.get("candidate_count", 0)
                or 0
            )
        )
        optimizer_input_count = int(
            str(workflow.universe_evidence.get("optimizer_input", 0))
        )
        cardinality_trace = {
            "factor_eligible": len(factors),
            "alpha_positive": int(
                str(workflow.universe_evidence.get("alpha_positive", 0))
            ),
            "candidate_pool": candidate_count,
            "optimizer_input": optimizer_input_count,
            "risk_engine_securities": (
                len(workflow.risk.symbols) if workflow.risk is not None else 0
            ),
            "maximum_allowed_holdings": None,
            "optimized_target_holdings": len(target_weights),
            "final_decision_holdings": len(decisions),
            "pre_optimizer_top10_truncation": False,
            "optimizer_received_alpha_top10": False,
            "display_candidates_limited_to": 10,
            "holding_cap_policy": "NO_FIXED_CARDINALITY_CAP",
        }

        identity_hashes = workflow.identity_hashes or {}
        decision_manifest: dict[str, object] | None = None
        if run_identity is not None:
            try:
                import scipy as _scipy

                manifest = seal_decision_manifest(
                    identity=run_identity,
                    decision_cutoff=data_cutoff if data_cutoff is not None else now,
                    analysis_date=analysis_date,
                    trade_date=trade_date,
                    market_data_snapshot_id=snapshot_id,
                    market_data_hash=snapshot_hash,
                    universe_snapshot_id=str(workflow.universe_snapshot_id),
                    universe_hash=str(
                        identity_hashes.get("universe_definition_hash", "UNAVAILABLE")
                    ),
                    portfolio_snapshot_id=str(workflow.portfolio_snapshot_id),
                    portfolio_hash=str(
                        identity_hashes.get("portfolio_constraint_hash", "UNAVAILABLE")
                    ),
                    config_hash=self._effective_config.canonical_run_config_hash,
                    feature_version=str(workflow.strategy_version),
                    factor_model_id=str(workflow.strategy_version),
                    alpha_model_id=str(workflow.strategy_version),
                    probability_model_id=str(workflow.probability_artifact_id),
                    portfolio_model_id=str(workflow.portfolio_validation_artifact_id),
                    risk_model_id=str(identity_hashes.get("risk_model_hash", "UNAVAILABLE")),
                    cost_model_id=str(identity_hashes.get("cost_model_hash", "UNAVAILABLE")),
                    strategy_approval_id=str(workflow.strategy_approval_id),
                    operational_policy_id=str(workflow.operational_policy_id),
                    random_seed=0,
                    solver_name="SLSQP",
                    solver_version=str(getattr(_scipy, "__version__", "UNAVAILABLE")),
                    formal_action_ids=tuple(
                        item.recommendation_id for item in decisions
                    ),
                    execution_plan_id=f"manual-plan-{run_id}",
                )
                decision_manifest = manifest.document()
            except (AttributeError, ImportError, ValueError):
                decision_manifest = None
        decision_provenance = self._decision_provenance(
            run_id=run_id,
            workflow=workflow,
            factors=factors,
            decisions=decisions,
            target_weights=target_weights,
            current_weights=current,
            current_exposure=current_exposure,
            decision_manifest=decision_manifest,
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
                "cardinality_trace": cardinality_trace,
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
            etf_universe=etf_universe or {},
            etf_targets=etf_targets,
            etf_composition=etf_composition,
            ai_brief=ai_brief,
            pre_execution=pre_execution,
            decision_manifest=decision_manifest,
            current_exposure=current_exposure,
            decision_provenance=decision_provenance,
            hybrid_intelligence=hybrid_intelligence,
        )

    def _decision_provenance(
        self,
        *,
        run_id: str,
        workflow: TodayResult,
        factors: tuple[FactorRow, ...],
        decisions: tuple[DecisionRow, ...],
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        current_exposure: dict[str, object] | None,
        decision_manifest: dict[str, object] | None,
    ) -> dict[str, object]:
        """ROUND28 P0: immutable per-decision provenance for the exact run.

        Every field is copied from already-computed deterministic evidence.
        Nothing here recomputes a target or changes an action.
        """
        decision_by_symbol = {item.symbol: item for item in decisions}
        probability_by_symbol = {
            item.symbol: item for item in workflow.probability_overlay_effects
        }
        risk = workflow.risk
        optimizer_provenance = (
            workflow.target.optimizer_provenance if workflow.target is not None else None
        )
        raw_targets = (
            workflow.target.raw_target_weights if workflow.target is not None else None
        )
        size_observations = {}
        sector_statuses = {}
        if isinstance(current_exposure, dict):
            observations = current_exposure.get("market_cap_observations")
            if isinstance(observations, dict):
                size_observations = observations
            acquisition = current_exposure.get("sector_acquisition")
            if isinstance(acquisition, dict) and isinstance(
                acquisition.get("symbol_status"), dict
            ):
                sector_statuses = acquisition["symbol_status"]
        manifest_hash = (
            str(decision_manifest.get("semantic_hash") or "UNAVAILABLE")
            if isinstance(decision_manifest, dict)
            else "UNAVAILABLE"
        )
        records: dict[str, object] = {}
        for factor in factors:
            symbol = factor.symbol
            decision = decision_by_symbol.get(symbol)
            probability = probability_by_symbol.get(symbol)
            risk_specific: dict[str, object] = {}
            if risk is not None:
                risk_specific = {
                    "annualized_volatility": risk.annualized_volatility.get(symbol),
                    "beta": risk.beta.get(symbol),
                    "sector": risk.sectors.get(symbol),
                    "average_daily_dollar_volume": (
                        risk.average_daily_dollar_volume.get(symbol)
                    ),
                    "size_score": risk.size_scores.get(symbol),
                    "market_cap": risk.market_caps.get(symbol),
                    "covariance_contribution": (
                        decision.risk_contribution if decision is not None else None
                    ),
                }
            liquidity_cap = None
            position_cap = None
            if risk is not None and workflow.portfolio_value:
                adv = risk.average_daily_dollar_volume.get(symbol)
                if adv is not None:
                    liquidity_cap = (
                        adv
                        * self._effective_config.transaction_cost.maximum_adv_participation
                        / workflow.portfolio_value
                    )
                position_cap = (
                    self._effective_config.portfolio_constraints.maximum_position_weight
                )
            records[symbol] = {
                "ticker": symbol,
                "security_identity": (
                    decision.recommendation_id if decision is not None else symbol
                ),
                "factor_inputs": {
                    "raw_values": factor.raw_values,
                    "winsorized_values": factor.winsorized_values,
                    "normalized_values": factor.neutralized_values or factor.components,
                    "neutralized_values": factor.neutralized_values,
                    "components": factor.components,
                    "composite": factor.composite,
                    "factor_rank": factor.rank,
                    "factor_status": factor.status,
                },
                "raw_expected_alpha": factor.expected_alpha,
                "alpha_model_identity": workflow.strategy_version,
                "signal_eligibility": {
                    "factor_status": factor.status,
                    "signal_authorization_class": workflow.signal_authorization_class,
                    "research_certification_state": workflow.research_certification_state,
                },
                "probability": {
                    "model_identity": workflow.probability_artifact_id,
                    "state": workflow.probability_overlay_state,
                    "reason": workflow.probability_overlay_reason,
                    "estimate": (
                        probability.posterior_probability
                        if probability is not None
                        else None
                    ),
                    "adjustment": (
                        probability.probability_adjustment
                        if probability is not None
                        else 0.0
                    ),
                    "production_weight": 0.0,
                },
                "risk": risk_specific,
                "liquidity_and_cost": {
                    "adv": risk_specific.get("average_daily_dollar_volume"),
                    "liquidity_cap_weight": liquidity_cap,
                    "position_cap_weight": position_cap,
                    "estimated_spread_bps": (
                        self._effective_config.transaction_cost.spread_bps
                    ),
                    "estimated_impact_bps": (
                        self._effective_config.transaction_cost.impact_coefficient_bps
                    ),
                    "estimated_cost_usd": (
                        decision.estimated_cost if decision is not None else None
                    ),
                    "turnover_penalty": (
                        self._effective_config.portfolio_constraints.turnover_penalty
                    ),
                },
                "current_only_exposure": {
                    "size": size_observations.get(symbol, "UNAVAILABLE"),
                    "sector_status": sector_statuses.get(symbol, "UNAVAILABLE"),
                    "boundary": "CURRENT_ONLY_NEVER_HISTORICAL_PIT",
                },
                "optimizer": {
                    "raw_target_weight": (
                        raw_targets.get(symbol) if raw_targets is not None else None
                    ),
                    "constrained_target_weight": target_weights.get(symbol),
                    "final_target_weight": (
                        decision.target_weight if decision is not None else None
                    ),
                    "current_weight": current_weights.get(symbol, 0.0),
                    "delta_weight": (
                        decision.delta_weight if decision is not None else None
                    ),
                    "portfolio_expected_alpha": (
                        workflow.target.expected_alpha
                        if workflow.target is not None
                        else None
                    ),
                    "portfolio_expected_volatility": (
                        workflow.target.expected_volatility
                        if workflow.target is not None
                        else None
                    ),
                    "portfolio_turnover": (
                        workflow.target.turnover if workflow.target is not None else None
                    ),
                    "portfolio_estimated_transaction_cost": (
                        workflow.target.estimated_transaction_cost
                        if workflow.target is not None
                        else None
                    ),
                    "portfolio_gross_weight": (
                        sum(workflow.target.target_weights.values())
                        if workflow.target is not None
                        else None
                    ),
                    "portfolio_cash_weight": (
                        workflow.target.cash_weight
                        if workflow.target is not None
                        else None
                    ),
                    "portfolio_provenance": optimizer_provenance,
                },
                "execution": {
                    "final_action": decision.action if decision is not None else "NO_ACTION",
                    "estimated_notional": (
                        decision.estimated_value if decision is not None else None
                    ),
                    "estimated_quantity": (
                        decision.estimated_quantity if decision is not None else None
                    ),
                    "rounding": "floor_to_whole_share",
                },
                "decision_reasons": (
                    [decision.reason]
                    if decision is not None and decision.reason
                    else ["UNAVAILABLE"]
                ),
                "vetoes_considered": {
                    "risk_reductions": (
                        list(workflow.target.risk_reductions)
                        if workflow.target is not None
                        else []
                    ),
                    "blockers": list(workflow.blockers),
                    "warnings": list(workflow.warnings),
                },
                "active_gates": {
                    "automatic_execution": "DISABLED",
                    "broker_api": "DISABLED",
                    "manual_confirmation_required": True,
                    "operational_policy_id": workflow.operational_policy_id,
                    "operational_policy_decision": workflow.operational_policy_decision,
                    "probability_overlay_state": workflow.probability_overlay_state,
                },
                "hashes": {
                    "decision_manifest_semantic_hash": manifest_hash,
                    "config_hash": workflow.config_hash,
                    "data_hash": workflow.data_hash,
                    "model_hash": workflow.model_hash,
                    "strategy_version": workflow.strategy_version,
                    "data_snapshot_id": workflow.data_hash,
                    "universe_snapshot_id": workflow.universe_snapshot_id,
                    "portfolio_snapshot_id": workflow.portfolio_snapshot_id,
                    "probability_model_id": workflow.probability_artifact_id,
                    "operational_policy_id": workflow.operational_policy_id,
                    "identity_hashes": dict(workflow.identity_hashes or {}),
                },
            }
        return {
            "schema_version": "round28-decision-provenance-v1",
            "run_id": run_id,
            "decision_id": f"decision-{run_id}",
            "optimizer_provenance": optimizer_provenance,
            "decisions": records,
        }

    @staticmethod
    def _candidate_symbols(universe_evidence: dict[str, object]) -> tuple[str, ...]:
        compression = universe_evidence.get("candidate_compression")
        if not isinstance(compression, dict):
            return ()
        symbols = compression.get("candidate_symbols")
        if not isinstance(symbols, list):
            return ()
        return tuple(str(item) for item in symbols)

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
                status="BLOCKED",
                manual_execution_required=True,
                broker="Charles Schwab",
                estimated_cash_before=None,
                estimated_proceeds=0.0,
                estimated_buys=0.0,
                estimated_cash_after=None,
                turnover=None,
                estimated_cost=0.0,
                legs=(),
                execution_plan_generated=False,
                broker_order_submitted=False,
                broker_api="DISABLED",
                execution_mode="MANUAL_ONLY",
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
            status="READY" if legs else "NO_ACTION",
            manual_execution_required=True,
            broker="Charles Schwab",
            estimated_cash_before=cash_before,
            estimated_proceeds=proceeds,
            estimated_buys=buys,
            estimated_cash_after=cash_after,
            turnover=workflow.target.turnover if workflow.target else 0.0,
            estimated_cost=costs,
            legs=legs,
            execution_plan_generated=bool(legs),
            broker_order_submitted=False,
            broker_api="DISABLED",
            execution_mode="MANUAL_ONLY",
        )

    def _add_pre_execution_stage(
        self,
        stages: dict[str, StageResult],
        *,
        as_of: datetime,
        duration_started: float,
    ) -> dict[str, object] | None:
        """ROUND25 PHASE 7: overnight / pre-execution risk assessment.

        Compares the previous actionable run against what happened between its
        close and now (news, gaps, price freshness).  Advisory only: the worst
        status is PRE_EXECUTION_REVIEW_REQUIRED (HUMAN REVIEW).  This layer
        never retrains models, never recomputes yesterday's alpha and never
        cancels an order by itself.
        """

        now = datetime.now(UTC)
        try:
            previous = self._latest_previous_run_certificate()
            if previous is None:
                stages["PRE_EXECUTION"] = StageResult(
                    "PRE_EXECUTION",
                    StageStatus.OPTIONAL_UNAVAILABLE,
                    perf_counter() - duration_started,
                    "no previous actionable run to guard",
                    {"enabled": True, "status": "PRE_EXECUTION_DATA_UNAVAILABLE"},
                )
                return None
            decision_as_of_raw = previous.get("data_cutoff") or previous.get("finished_at")
            decision_as_of = datetime.fromisoformat(str(decision_as_of_raw))
            if decision_as_of.tzinfo is None:
                decision_as_of = decision_as_of.replace(tzinfo=UTC)
            decision_as_of = decision_as_of.astimezone(UTC)
            raw_recommendations = previous.get("decision_recommendations")
            recommendations = (
                raw_recommendations if isinstance(raw_recommendations, list) else []
            )
            formal_symbols = frozenset(
                str(item.get("symbol"))
                for item in recommendations
                if isinstance(item, dict) and item.get("symbol")
            )
            news_service = NewsIntelligenceService()
            checks: list[PreExecutionCheck] = []
            try:
                checks.append(
                    check_overnight_news(
                        news_service,
                        decision_as_of=decision_as_of,
                        now=now,
                        material_symbols=formal_symbols or None,
                    )
                )
            except (OSError, ValueError):
                checks.append(
                    PreExecutionCheck(
                        "overnight_news", "UNAVAILABLE", "news ledger unreadable"
                    )
                )
            checks.append(self._pre_execution_price_checks(previous, formal_symbols, now))
            checks.append(
                check_halts_and_corporate_events(
                    halted_symbols=frozenset(
                        str(item.get("symbol"))
                        for item in recommendations
                        if isinstance(item, dict)
                        and str(item.get("data_quality", "")).upper() in {"HALTED", "DELISTED"}
                    ),
                )
            )
            assessment = build_assessment(
                decision_as_of=decision_as_of,
                now=now,
                checks=tuple(checks),
            )
            stages["PRE_EXECUTION"] = StageResult(
                "PRE_EXECUTION",
                StageStatus.PASS,
                perf_counter() - duration_started,
                f"pre-execution assessment: {assessment.status}",
                {
                    "enabled": True,
                    "status": assessment.status,
                    "manual_review_required": assessment.manual_review_required,
                    "llm_authority": "NONE",
                },
            )
            return assessment.document()
        except (OSError, ValueError, SQLAlchemyError) as error:
            stages["PRE_EXECUTION"] = StageResult(
                "PRE_EXECUTION",
                StageStatus.PASS_DEGRADED,
                perf_counter() - duration_started,
                f"pre-execution assessment degraded: {type(error).__name__}",
                {"enabled": True, "status": "PRE_EXECUTION_DATA_UNAVAILABLE"},
            )
            return {
                "status": "PRE_EXECUTION_DATA_UNAVAILABLE",
                "detail": str(error),
                "manual_review_required": True,
                "llm_authority": "NONE",
                "auto_cancel": False,
                "alpha_recomputation": False,
            }

    def _latest_previous_run_certificate(self) -> dict[str, object] | None:
        """Latest persisted run certificate with formal recommendations."""

        root = self._snapshot_root
        candidates = sorted(
            root.glob("*/run_certificate.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                payload = _json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("decision_recommendations"):
                return cast("dict[str, object]", payload)
        return None

    def _pre_execution_price_checks(
        self,
        previous: dict[str, object],
        formal_symbols: frozenset[str],
        now: datetime,
    ) -> PreExecutionCheck:
        """Gap + freshness evidence from verified local price bars."""

        decision_as_of_raw = previous.get("data_cutoff") or previous.get("finished_at")
        try:
            decision_as_of = datetime.fromisoformat(str(decision_as_of_raw))
        except ValueError:
            decision_as_of = None
        if decision_as_of is not None and decision_as_of.tzinfo is None:
            decision_as_of = decision_as_of.replace(tzinfo=UTC)
        with self._factory.begin() as session:
            spy_prices = session.execute(
                select(Price.trade_date, Price.close, Price.available_time)
                .join(SecurityMaster, Price.stock_id == SecurityMaster.id)
                .where(
                    SecurityMaster.symbol == "SPY",
                    Price.price_type == "unadjusted_ohlcv",
                )
                .order_by(Price.trade_date.desc())
                .limit(2)
            ).all()
            freshness_rows = session.execute(
                select(func.max(Price.available_time))
                .join(SecurityMaster, Price.stock_id == SecurityMaster.id)
                .where(
                    SecurityMaster.symbol.in_(sorted(formal_symbols)),
                    Price.price_type == "unadjusted_ohlcv",
                )
            ).scalar()
        decision_close: float | None = None
        latest_close: float | None = None
        if len(spy_prices) >= 2 and decision_as_of is not None:
            before = [
                row for row in spy_prices
                if row[0] <= decision_as_of.date()
            ]
            if before:
                decision_close = float(before[0][1])
                latest_close = (
                    float(spy_prices[0][1])
                    if spy_prices[0][0] > decision_as_of.date()
                    else decision_close
                )
        gap_check = check_market_gap(
            decision_close=decision_close,
            latest_close=latest_close,
        )
        freshness = check_stale_market_data(
            latest_available_at=freshness_rows,
            decision_as_of=decision_as_of or now,
            now=now,
        )
        if gap_check.status == "UNAVAILABLE" and freshness.status == "PASS":
            return PreExecutionCheck(
                "market_gap_and_freshness",
                freshness.status,
                freshness.detail + "; gap: " + gap_check.detail,
            )
        if gap_check.status in {"PASS", "WARN"} and freshness.status == "PASS":
            return PreExecutionCheck(
                "market_gap_and_freshness",
                "PASS",
                freshness.detail + "; " + gap_check.detail,
                gap_check.evidence,
            )
        if gap_check.status == "REVIEW_REQUIRED" or freshness.status == "REVIEW_REQUIRED":
            return PreExecutionCheck(
                "market_gap_and_freshness",
                "REVIEW_REQUIRED",
                freshness.detail + "; " + gap_check.detail,
                gap_check.evidence,
            )
        return PreExecutionCheck(
            "market_gap_and_freshness",
            "UNAVAILABLE",
            freshness.detail + "; " + gap_check.detail,
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
            if updated.ai_brief is not None:
                run_directory = self._snapshot_root / updated.run_id
                brief_path = run_directory / "ai_brief.json"
                temporary = brief_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        updated.ai_brief,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(brief_path)
            if updated.hybrid_intelligence is not None:
                run_directory = self._snapshot_root / updated.run_id
                hybrid_path = run_directory / "hybrid_intelligence.json"
                temporary = hybrid_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        updated.hybrid_intelligence,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(hybrid_path)
            if updated.etf_targets:
                run_directory = self._snapshot_root / updated.run_id
                etf_path = run_directory / "etf_sleeve_evidence.json"
                temporary = etf_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        {
                            "run_id": updated.run_id,
                            "analysis_date": updated.analysis_date.isoformat(),
                            "universe": updated.etf_universe,
                            "targets": list(updated.etf_targets),
                            "composition": updated.etf_composition,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(etf_path)
            if updated.current_exposure is not None:
                run_directory = self._snapshot_root / updated.run_id
                exposure_path = run_directory / "current_exposure.json"
                temporary = exposure_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        updated.current_exposure,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(exposure_path)
            if updated.decision_manifest is not None:
                run_directory = self._snapshot_root / updated.run_id
                manifest_path = run_directory / "decision_manifest.json"
                temporary = manifest_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        updated.decision_manifest,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(manifest_path)
            if updated.pre_execution is not None:
                run_directory = self._snapshot_root / updated.run_id
                pre_path = run_directory / "pre_execution.json"
                temporary = pre_path.with_suffix(".json.tmp")
                temporary.write_text(
                    _json.dumps(
                        updated.pre_execution,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(pre_path)
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
