from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select
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
from personal_alpha_terminal.models import Portfolio
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSession,
    MarketSessionCalendar,
)

_STAGE_ORDER = (
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
    ) -> None:
        self._factory = session_factory
        if isinstance(effective_config, Settings):
            effective_config = effective_config_from_settings(effective_config)
        self._effective_config = effective_config
        self._settings = effective_config.settings
        self._snapshot_root = snapshot_root or (
            effective_config.report_dir / "daily-runs"
        )
        self._sync_runner = sync_runner
        self._calendar = MarketSessionCalendar(
            nasdaq_23h_enabled=effective_config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=effective_config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
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
                        start_date=data_service.refresh_start_date(
                            analysis_date=analysis_date
                        ),
                        end_date=analysis_date,
                    )
                    if sync.status == "BLOCKED":
                        data_failure_reasons.append(
                            "required provider refresh failed: "
                            + ", ".join(sync.failed_symbols)
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
        except (OSError, RuntimeError, ValueError) as error:
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

    def _resolve_portfolio(self, requested: int | None) -> int | None:
        with self._factory() as session:
            if requested is not None:
                return requested if session.get(Portfolio, requested) is not None else None
            ids = tuple(session.scalars(select(Portfolio.id).order_by(Portfolio.id).limit(2)))
        return ids[0] if len(ids) == 1 else None

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
        return "multiple portfolios exist; select portfolio_id explicitly"

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
            "Point-in-Time Inputs": "PIT",
            "Feature Engine": "FEATURE",
            "Factor Engine": "FACTOR",
            "Alpha Signals": "SIGNAL",
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
            status = (
                StageStatus.FAIL_BLOCKING
                if item.status == "BLOCKED"
                else StageStatus.PASS
            )
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
                StageStatus.PASS_DEGRADED,
                0.0,
                "no calibrated PIT conditional overlay; deterministic base alpha is unchanged",
                {"position_influence": 0.0, "output_row_count": 1},
            ),
        )
        first_quant = next(
            (
                name
                for name in _STAGE_ORDER
                if name in stages and name != "CALENDAR"
            ),
            None,
        )
        if first_quant is not None:
            stage_result = stages[first_quant]
            stages[first_quant] = replace(
                stage_result, duration_seconds=duration
            )

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
            )
            for item in workflow.factors
        )
        probability = (
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
                workflow.probability_calibration_status,
                "PASS_DEGRADED",
            ),
        )
        target_weights = workflow.target.target_weights if workflow.target else {}
        current = workflow.current_weights or {}
        input_positions = {
            item.symbol: item for item in workflow.portfolio_positions
        }
        positions = tuple(
            PortfolioPositionRow(
                symbol,
                (
                    input_positions[symbol].quantity
                    if symbol in input_positions
                    else None
                ),
                (
                    input_positions[symbol].reference_price
                    if symbol in input_positions
                    else None
                ),
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
        portfolio = PortfolioSummary(
            workflow.portfolio_status,
            workflow.portfolio_value,
            workflow.cash_balance,
            workflow.cash_target,
            workflow.gross_target,
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
            RejectedSignalRow("ALL", self._failed_stage(stages), reason)
            for reason in blockers
        ]
        if target is not None:
            rejected.extend(
                RejectedSignalRow("PORTFOLIO", "RISK", reason)
                for reason in target.risk_reductions
            )
        execution = self._execution_plan(workflow, decisions, actionable)
        benchmark = BenchmarkSummary(
            workflow.benchmark_symbol,
            "PIT PROXY" if workflow.benchmark_observations else "UNAVAILABLE",
            workflow.benchmark_observations,
            workflow.benchmark_period_return,
            workflow.benchmark_annualized_volatility,
            "Same PIT return dataset; no unsupported long-horizon annualization is shown.",
        )
        pit_status = (
            StageStatus.PASS
            if workflow.data_certification == "APPROVED"
            else StageStatus.FAIL
        )
        strategy_data_health = (
            *data_health,
            DataHealthItem(
                "POINT_IN_TIME_TOTAL_RETURN",
                analysis_date,
                workflow.data_cutoff.date() if workflow.data_cutoff else None,
                (
                    (analysis_date - workflow.data_cutoff.date()).days
                    if workflow.data_cutoff
                    else None
                ),
                None,
                None,
                ",".join(workflow.source_ids) or "UNAVAILABLE",
                pit_status,
                f"data_version={workflow.data_hash}",
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
            workflow.data_cutoff,
            DecisionReadiness.READY if actionable else DecisionReadiness.NOT_ACTIONABLE,
            "OPTIONAL/OFFLINE" if self._settings.llm_provider == "disabled" else "OPTIONAL",
            self._ordered_stages(stages),
            strategy_data_health,
            workflow.risk_regime,
            "Regime probability is unavailable; no uncalibrated score changes alpha.",
            factors,
            probability,
            tuple(sorted(factors, key=lambda item: item.rank)[:10]),
            portfolio,
            risk,
            decisions if actionable else (),
            tuple(rejected),
            execution,
            (benchmark,),
            blockers,
            warnings,
            {
                "database_run_id": workflow.run_id,
                "data_hash": workflow.data_hash,
                "model_hash": workflow.model_hash,
                "build_identifier": build.build_id,
                "git_commit": build.git_commit,
                "build_time": build.build_time,
                "dependency_lock_hash": build.dependency_lock_hash,
                "randomness": "NOT_USED",
                "source_ids": workflow.source_ids,
                "universe_count": workflow.universe_count,
                "manual_broker": "Charles Schwab",
                "automatic_execution": False,
                "identity_hashes": {
                    **(workflow.identity_hashes or {}),
                    "model_approval_hash": workflow.model_approval_hash,
                },
                "probability_calibration_status": workflow.probability_calibration_status,
            },
            self._effective_config.canonical_run_config_hash,
            tuple(
                sorted(
                    {
                        item.model_version
                        for item in decisions
                        if item.model_version != "UNAVAILABLE"
                    }
                )
            ),
            self._decision_traces(factors, decisions, target_weights, current),
        )

    @staticmethod
    def _decision_traces(
        factors: tuple[FactorRow, ...],
        decisions: tuple[DecisionRow, ...],
        target_weights: dict[str, float],
        current_weights: dict[str, float],
    ) -> dict[str, dict[str, object]]:
        decision_by_symbol = {item.symbol: item for item in decisions}
        traces: dict[str, dict[str, object]] = {}
        for factor in factors:
            decision = decision_by_symbol.get(factor.symbol)
            traces[factor.symbol] = {
                "data_quality": decision.data_quality if decision else "NOT_CAPTURED",
                "factor_raw_values": factor.raw_values or "NOT_CAPTURED",
                "factor_winsorized_values": (
                    factor.winsorized_values or "NOT_CAPTURED"
                ),
                "factor_normalized_values": "NOT_CAPTURED",
                "factor_neutralized_values": (
                    factor.neutralized_values or factor.components
                ),
                "cross_sectional_rank": factor.rank,
                "composite_alpha": factor.composite,
                "expected_alpha": factor.expected_alpha,
                "evidence_coverage": factor.evidence_coverage,
                "calibrated_probability": "NOT_CAPTURED",
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
            }
        return traces

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
            item.estimated_value
            for item in ordered
            if item.action in {"SELL", "REDUCE"}
        )
        buys = sum(
            item.estimated_value
            for item in ordered
            if item.action in {"BUY", "ADD", "INCREASE"}
        )
        costs = sum(item.estimated_cost for item in ordered)
        cash_before = workflow.cash_balance
        cash_after = (
            cash_before + proceeds - buys - costs if cash_before is not None else None
        )
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
                stages=(*result.stages, StageResult(
                    "PERSISTENCE", StageStatus.FAIL, perf_counter() - started, blocker, {}
                )),
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
            "OPTIONAL/OFFLINE" if self._settings.llm_provider == "disabled" else "OPTIONAL",
            self._ordered_stages(stages),
            data_health,
            "UNAVAILABLE",
            "quant stages did not reach a calibrated regime input",
            (),
            (ProbabilityRow(
                "Validated conditional overlay", "base alpha confidence / position cap", 0,
                None, None, None, None, None, None, None, None,
                "INSUFFICIENT EVIDENCE", "NOT CALIBRATED OOS", "NOT_RUN"
            ),),
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
                    (
                        "PORTFOLIO"
                        if item.startswith("PORTFOLIO ")
                        else self._failed_stage(stages)
                    ),
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
        stages[failed_stage] = StageResult(
            failed_stage, StageStatus.FAIL, 0.0, reason, {}
        )
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
