import os
from collections.abc import Callable
from datetime import date, timedelta
from functools import partial
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.conditional_probability.repository import (
    ConditionalProbabilityRepository,
)
from personal_alpha_terminal.analysis.conditional_probability.service import (
    ConditionalProbabilityService,
)
from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.analysis.factors.repository import FactorResearchRepository
from personal_alpha_terminal.analysis.factors.service import FactorResearchService
from personal_alpha_terminal.analysis.relationships.repository import RelationshipRepository
from personal_alpha_terminal.analysis.relationships.service import RelationshipAnalysisService
from personal_alpha_terminal.automation.report import render_daily_pipeline_report
from personal_alpha_terminal.automation.runner import (
    PipelineContext,
    TaskFailure,
    TaskOutcome,
    TaskSkipped,
    TaskSpec,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.data.market_data import build_market_data_engine
from personal_alpha_terminal.data.market_data.schemas import DailyUpdateReport, QualitySeverity
from personal_alpha_terminal.data.market_data_quality.report import render_markdown
from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.service import (
    MarketDataQualityService,
)
from personal_alpha_terminal.models import (
    ConditionalProbabilityRun,
    EventStudyRun,
    PortfolioRiskRun,
)
from personal_alpha_terminal.portfolio.repository import PortfolioRiskRepository
from personal_alpha_terminal.portfolio.service import PortfolioRiskService

Job = Callable[[], dict[str, object]]


def default_daily_tasks(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    report_path: Path | None = None,
) -> tuple[TaskSpec, ...]:
    """Build the fixed, explainable daily pipeline without notification side effects."""

    return (
        TaskSpec("market_data_update", _market_data_task(session_factory)),
        TaskSpec(
            "data_quality",
            _data_quality_task(
                session_factory,
                settings.daily_pipeline_quality_report_path,
            ),
        ),
        TaskSpec(
            "event_study",
            _event_study_task(session_factory, settings),
            requires_quality_gate=True,
        ),
        TaskSpec(
            "conditional_probability",
            _conditional_probability_task(session_factory, settings),
            requires_quality_gate=True,
        ),
        TaskSpec(
            "market_relationships",
            _relationship_task(session_factory, settings),
            requires_quality_gate=True,
        ),
        TaskSpec(
            "factor_analysis",
            _factor_task(session_factory, settings),
            requires_quality_gate=True,
        ),
        TaskSpec(
            "portfolio_risk",
            _portfolio_risk_task(session_factory, settings),
            requires_quality_gate=True,
        ),
        TaskSpec(
            "daily_report",
            _daily_report_task(
                session_factory,
                report_path or settings.daily_pipeline_report_path,
            ),
        ),
    )


def _market_data_task(
    session_factory: sessionmaker[Session],
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            report = build_market_data_engine(session).update_daily_data(
                end_date=context.as_of_date
            )
        details: dict[str, object] = {
            "success_count": report.success_count,
            "no_data_count": report.no_data_count,
            "failure_count": report.failure_count,
            "inserted_count": report.inserted_count,
            "updated_count": report.updated_count,
            "warnings": [
                f"{item.market}:{item.symbol}: {item.error or item.status}"
                for item in report.results
                if item.status != "success"
            ],
        }
        if not report.results:
            raise TaskFailure(
                "no active registered instruments were available for daily update",
                retryable=False,
                details=details,
            )
        hard_failures = _hard_market_update_failures(report)
        if hard_failures:
            details["failures"] = hard_failures
            raise TaskFailure(
                "market-data update is not safe for downstream analysis",
                retryable=report.failure_count > 0,
                details=details,
            )
        return TaskOutcome(details)

    return execute


def _data_quality_task(
    session_factory: sessionmaker[Session],
    quality_report_path: Path,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            run_id, report = MarketDataQualityService(
                MarketDataQualityRepository(session)
            ).run(history_end=context.as_of_date)
            content = render_markdown(report, run_id=run_id)
        quality_path = quality_report_path.expanduser().resolve()
        _atomic_write(quality_path, content)
        details: dict[str, object] = {
            "quality_run_id": run_id,
            "quality_status": report.status.value,
            "sample_size": len(report.instrument_results),
            "blockers": list(report.blockers),
            "failed_instruments": sum(not item.passed for item in report.instrument_results),
            "quality_report_path": str(quality_path),
        }
        if report.status.value != "passed":
            raise TaskFailure(
                f"market-data quality gate returned {report.status.value}",
                retryable=False,
                details=details,
            )
        return TaskOutcome(details)

    return execute


def _event_study_task(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            configurations = _event_configurations(
                session,
                limit=settings.daily_pipeline_max_event_jobs,
            )
        if not configurations:
            raise TaskSkipped("no successful event-study configuration is available")
        jobs: list[Job] = []
        for configuration in configurations:
            jobs.append(
                partial(
                    _run_event_configuration,
                    session_factory,
                    settings,
                    configuration,
                    context.as_of_date,
                )
            )
        return _execute_jobs("event study", jobs)

    return execute


def _conditional_probability_task(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            configurations = _probability_configurations(
                session,
                limit=settings.daily_pipeline_max_probability_jobs,
            )
        if not configurations:
            raise TaskSkipped("no successful conditional-probability configuration is available")
        jobs: list[Job] = []
        for configuration in configurations:
            jobs.append(
                partial(
                    _run_probability_configuration,
                    session_factory,
                    settings,
                    configuration,
                    context.as_of_date,
                )
            )
        return _execute_jobs("conditional probability", jobs)

    return execute


def _relationship_task(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        jobs: list[Job] = []
        warnings: list[str] = []
        start_date = context.as_of_date - timedelta(
            days=settings.daily_pipeline_analysis_lookback_days
        )
        for universe in ("stock", "etf", "industry"):
            with session_scope(session_factory) as session:
                service = RelationshipAnalysisService(
                    RelationshipRepository(session),
                    settings,
                )
                entity_ids = tuple(
                    item.id
                    for item in service.list_entities(universe)[
                        : settings.relationship_max_entities
                    ]
                )
            if len(entity_ids) < 2:
                warnings.append(f"{universe}: fewer than two configured entities")
                continue
            for method in ("pearson", "spearman"):
                jobs.append(
                    partial(
                        _run_relationship_configuration,
                        session_factory,
                        settings,
                        universe,
                        method,
                        entity_ids,
                        start_date,
                        context.as_of_date,
                    )
                )
        if not jobs:
            raise TaskSkipped("fewer than two entities are available for relationship analysis")
        outcome = _execute_jobs("market relationship", jobs)
        outcome.details["warnings"] = warnings
        return outcome

    return execute


def _factor_task(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        jobs: list[Job] = []
        for market in ("A", "HK", "US"):
            jobs.append(
                partial(
                    _run_factor_market,
                    session_factory,
                    settings,
                    market,
                    context.as_of_date,
                )
            )
        return _execute_jobs("factor analysis", jobs)

    return execute


def _portfolio_risk_task(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            configurations = _portfolio_configurations(session)
        if not configurations:
            raise TaskSkipped(
                "no successful portfolio-risk configuration is available; benchmark is not guessed"
            )
        start_date = context.as_of_date - timedelta(
            days=settings.daily_pipeline_analysis_lookback_days
        )
        jobs: list[Job] = []
        for portfolio_id, benchmark_id in configurations:
            jobs.append(
                partial(
                    _run_portfolio_configuration,
                    session_factory,
                    settings,
                    portfolio_id,
                    benchmark_id,
                    start_date,
                    context.as_of_date,
                )
            )
        return _execute_jobs("portfolio risk", jobs)

    return execute


def _daily_report_task(
    session_factory: sessionmaker[Session],
    report_path: Path,
) -> Callable[[PipelineContext], TaskOutcome]:
    def execute(context: PipelineContext) -> TaskOutcome:
        with session_scope(session_factory) as session:
            content = render_daily_pipeline_report(
                session,
                context.pipeline_run_id,
                assume_report_completed=True,
            )
        resolved = report_path.expanduser().resolve()
        _atomic_write(resolved, content)
        return TaskOutcome(
            {
                "report_path": str(resolved),
                "report_bytes": resolved.stat().st_size,
            }
        )

    return execute


def _event_configurations(session: Session, *, limit: int) -> list[dict[str, object]]:
    rows = list(
        session.scalars(
            select(EventStudyRun)
            .where(EventStudyRun.status == "completed")
            .order_by(EventStudyRun.created_at.desc(), EventStudyRun.id.desc())
            .limit(500)
        )
    )
    configurations: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for run in rows:
        targets = _int_tuple(run.parameters.get("target_stock_ids"))
        key = (run.definition_id, run.trigger_stock_id, targets)
        if not targets or key in seen:
            continue
        seen.add(key)
        configurations.append(
            {
                "definition_id": run.definition_id,
                "trigger_stock_id": run.trigger_stock_id,
                "target_stock_ids": targets,
                "start_date": run.start_date,
                "horizons": tuple(run.horizons),
                "cooldown_days": _optional_int(run.parameters.get("cooldown_days")),
                "win_threshold": _optional_float(run.parameters.get("win_threshold")),
            }
        )
        if len(configurations) >= limit:
            break
    return configurations


def _probability_configurations(session: Session, *, limit: int) -> list[dict[str, object]]:
    rows = list(
        session.scalars(
            select(ConditionalProbabilityRun)
            .where(ConditionalProbabilityRun.status == "completed")
            .order_by(
                ConditionalProbabilityRun.created_at.desc(),
                ConditionalProbabilityRun.id.desc(),
            )
            .limit(500)
        )
    )
    configurations: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for run in rows:
        event_run = session.get(EventStudyRun, run.event_study_run_id)
        parameters = run.parameters
        if event_run is None:
            continue
        targets = _int_tuple(parameters.get("target_stock_ids"))
        horizons = _int_tuple(parameters.get("horizons"))
        definition_id = _optional_int(parameters.get("condition_definition_id"))
        trigger_id = _optional_int(parameters.get("trigger_stock_id"))
        if not targets or not horizons or definition_id is None or trigger_id is None:
            continue
        key = (
            definition_id,
            trigger_id,
            targets,
            run.outcome_direction,
            float(run.outcome_threshold),
        )
        if key in seen:
            continue
        seen.add(key)
        configurations.append(
            {
                "definition_id": definition_id,
                "trigger_stock_id": trigger_id,
                "target_stock_ids": targets,
                "start_date": event_run.start_date,
                "horizons": horizons,
                "outcome_direction": run.outcome_direction,
                "outcome_threshold": float(run.outcome_threshold),
                "minimum_sample_size": run.minimum_sample_size,
                "confidence_level": float(run.confidence_level),
                "cooldown_days": _optional_int(parameters.get("effective_cooldown_days")),
            }
        )
        if len(configurations) >= limit:
            break
    return configurations


def _portfolio_configurations(session: Session) -> list[tuple[int, int]]:
    rows = list(
        session.scalars(
            select(PortfolioRiskRun)
            .where(PortfolioRiskRun.status == "completed")
            .order_by(PortfolioRiskRun.created_at.desc(), PortfolioRiskRun.id.desc())
            .limit(500)
        )
    )
    configurations: list[tuple[int, int]] = []
    seen: set[int] = set()
    for row in rows:
        if row.portfolio_id in seen:
            continue
        seen.add(row.portfolio_id)
        configurations.append((row.portfolio_id, row.benchmark_stock_id))
    return configurations


def _run_event_configuration(
    session_factory: sessionmaker[Session],
    settings: Settings,
    configuration: dict[str, object],
    end_date: date,
) -> dict[str, object]:
    start_date = _date(configuration["start_date"])
    if start_date >= end_date:
        raise ValueError("event-study start date is not before pipeline date")
    with session_scope(session_factory) as session:
        result = EventStudyService(EventStudyRepository(session), settings).run(
            definition_id=_int(configuration["definition_id"]),
            trigger_stock_id=_int(configuration["trigger_stock_id"]),
            target_stock_ids=_int_tuple(configuration["target_stock_ids"]),
            start_date=start_date,
            end_date=end_date,
            horizons=_int_tuple(configuration["horizons"]),
            cooldown_days=_optional_int(configuration.get("cooldown_days")),
            win_threshold=_optional_float(configuration.get("win_threshold")),
        )
        return {
            "run_id": result.run_id,
            "trigger": result.trigger.symbol,
            "events": len(result.occurrences),
            "statistics": len(result.statistics),
        }


def _run_probability_configuration(
    session_factory: sessionmaker[Session],
    settings: Settings,
    configuration: dict[str, object],
    end_date: date,
) -> dict[str, object]:
    start_date = _date(configuration["start_date"])
    if start_date >= end_date:
        raise ValueError("conditional-probability start date is not before pipeline date")
    with session_scope(session_factory) as session:
        result = ConditionalProbabilityService(
            ConditionalProbabilityRepository(session), settings
        ).run(
            definition_id=_int(configuration["definition_id"]),
            trigger_stock_id=_int(configuration["trigger_stock_id"]),
            target_stock_ids=_int_tuple(configuration["target_stock_ids"]),
            start_date=start_date,
            end_date=end_date,
            outcome_direction=str(configuration["outcome_direction"]),
            outcome_threshold=_float(configuration["outcome_threshold"]),
            horizons=_int_tuple(configuration["horizons"]),
            minimum_sample_size=_int(configuration["minimum_sample_size"]),
            confidence_level=_float(configuration["confidence_level"]),
            cooldown_days=_optional_int(configuration.get("cooldown_days")),
        )
        return {
            "run_id": result.run_id,
            "trigger": result.trigger.symbol,
            "events": result.event_count,
            "results": len(result.results),
        }


def _run_relationship_configuration(
    session_factory: sessionmaker[Session],
    settings: Settings,
    universe: str,
    method: str,
    entity_ids: tuple[int, ...],
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    with session_scope(session_factory) as session:
        result = RelationshipAnalysisService(
            RelationshipRepository(session), settings
        ).run(
            universe_type=universe,
            entity_ids=entity_ids,
            method=method,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "run_id": result.run_id,
            "universe": universe,
            "method": method,
            "pairs": len(result.matrix),
            "anomalies": len(result.anomalies),
        }


def _run_factor_market(
    session_factory: sessionmaker[Session],
    settings: Settings,
    market: str,
    as_of_date: date,
) -> dict[str, object]:
    with session_scope(session_factory) as session:
        result = FactorResearchService(FactorResearchRepository(session), settings).run_snapshot(
            market=market,
            as_of_date=as_of_date,
        )
        return {"run_id": result.run_id, "market": market, "stocks": len(result.scores)}


def _run_portfolio_configuration(
    session_factory: sessionmaker[Session],
    settings: Settings,
    portfolio_id: int,
    benchmark_id: int,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    with session_scope(session_factory) as session:
        result = PortfolioRiskService(PortfolioRiskRepository(session), settings).run(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_id,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "run_id": result.risk.run_id,
            "portfolio_id": portfolio_id,
            "benchmark_id": benchmark_id,
            "value": result.risk.total_value,
        }


def _execute_jobs(label: str, jobs: list[Job]) -> TaskOutcome:
    successes: list[dict[str, object]] = []
    failures: list[str] = []
    retryable_failures = 0
    for job in jobs:
        try:
            successes.append(job())
        except Exception as error:
            failures.append(f"{type(error).__name__}: {error}")
            if not isinstance(error, (ValueError, TypeError)):
                retryable_failures += 1
    details: dict[str, object] = {
        "configured_jobs": len(jobs),
        "completed_jobs": len(successes),
        "failed_jobs": len(failures),
        "results": successes,
        "failures": failures,
    }
    if failures:
        raise TaskFailure(
            f"{label} completed with {len(failures)} failed workload(s)",
            retryable=not successes and retryable_failures == len(failures),
            details=details,
        )
    return TaskOutcome(details)


def _hard_market_update_failures(report: DailyUpdateReport) -> list[str]:
    """Treat clean no-data responses as warnings; the calendar-aware gate decides freshness."""

    failures: list[str] = []
    for result in report.results:
        has_error_issue = any(
            issue.severity == QualitySeverity.ERROR for issue in result.quality_issues
        )
        if result.status == "failed" or has_error_issue:
            failures.append(
                f"{result.market}:{result.symbol}: {result.error or 'quality validation failed'}"
            )
    return failures


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    try:
        partial.write_text(content, encoding="utf-8")
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("configuration value is not an integer")
    return int(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_int(item) for item in value)


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("configuration value is not numeric")
    return float(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else _float(value)


def _date(value: object) -> date:
    if not isinstance(value, date):
        raise ValueError("configuration value is not a date")
    return value
