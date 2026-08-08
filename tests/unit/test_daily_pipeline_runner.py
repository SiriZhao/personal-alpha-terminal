import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from personal_alpha_terminal.automation.runner import (
    DailyPipelineLock,
    DailyPipelineRunner,
    TaskFailure,
    TaskOutcome,
    TaskSpec,
)
from personal_alpha_terminal.automation.tasks import (
    _daily_report_task,
    _hard_market_update_failures,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import (
    build_engine,
    build_session_factory,
    session_scope,
)
from personal_alpha_terminal.data.market_data.schemas import (
    DailyUpdateReport,
    InstrumentUpdateResult,
    QualityIssue,
    QualitySeverity,
)
from personal_alpha_terminal.models import Base, DailyPipelineRun, DailyTaskRun


def _runner(tmp_path: Path) -> tuple[DailyPipelineRunner, object, Settings]:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        daily_pipeline_lock_path=tmp_path / "pipeline.lock",
        daily_pipeline_retry_backoff_seconds=0,
    )
    return DailyPipelineRunner(factory, settings, sleep=lambda _delay: None), factory, settings


def test_task_failure_isolated_retry_recorded_and_report_written(tmp_path: Path) -> None:
    runner, factory, _settings = _runner(tmp_path)
    flaky_calls = 0
    downstream_calls = 0
    report_path = tmp_path / "DAILY_PIPELINE_REPORT.md"

    def flaky(_context: object) -> TaskOutcome:
        nonlocal flaky_calls
        flaky_calls += 1
        if flaky_calls == 1:
            raise TaskFailure("temporary provider outage", retryable=True)
        return TaskOutcome({"provider": "test"})

    def permanent_failure(_context: object) -> TaskOutcome:
        raise ValueError("invalid saved analysis configuration")

    def downstream(_context: object) -> TaskOutcome:
        nonlocal downstream_calls
        downstream_calls += 1
        return TaskOutcome({"continued": True})

    result = runner.run(
        (
            TaskSpec("market_data_update", flaky),
            TaskSpec("data_quality", lambda _context: TaskOutcome({"status": "passed"})),
            TaskSpec("event_study", permanent_failure, requires_quality_gate=True),
            TaskSpec("factor_analysis", downstream, requires_quality_gate=True),
            TaskSpec("daily_report", _daily_report_task(factory, report_path)),
        ),
        as_of_date=date(2026, 7, 31),
        trigger="manual",
        max_attempts=3,
    )

    assert result.status == "partial"
    assert flaky_calls == 2
    assert downstream_calls == 1
    assert report_path.exists()
    assert "invalid saved analysis configuration" in report_path.read_text(encoding="utf-8")
    with session_scope(factory) as session:
        tasks = {
            item.task_name: item
            for item in session.scalars(
                select(DailyTaskRun).where(DailyTaskRun.pipeline_run_id == result.run_id)
            )
        }
        pipeline = session.get(DailyPipelineRun, result.run_id)
        assert pipeline is not None
        assert pipeline.status == "partial"
        assert tasks["market_data_update"].attempt_count == 2
        assert tasks["event_study"].status == "failed"
        assert tasks["factor_analysis"].status == "completed"
        assert tasks["daily_report"].status == "completed"


def test_failed_quality_gate_skips_analysis_but_still_generates_report(tmp_path: Path) -> None:
    runner, factory, _settings = _runner(tmp_path)
    analysis_calls = 0
    report_path = tmp_path / "blocked.md"

    def quality_failure(_context: object) -> TaskOutcome:
        raise TaskFailure(
            "quality gate blocked",
            retryable=False,
            details={"blockers": ["missing A-share universe snapshot"]},
        )

    def analysis(_context: object) -> TaskOutcome:
        nonlocal analysis_calls
        analysis_calls += 1
        return TaskOutcome({})

    result = runner.run(
        (
            TaskSpec("market_data_update", lambda _context: TaskOutcome({})),
            TaskSpec("data_quality", quality_failure),
            TaskSpec("event_study", analysis, requires_quality_gate=True),
            TaskSpec("daily_report", _daily_report_task(factory, report_path)),
        ),
        as_of_date=date(2026, 7, 31),
        trigger="scheduler",
        max_attempts=2,
    )

    assert result.status == "failed"
    assert analysis_calls == 0
    assert result.task_statuses["event_study"] == "skipped"
    report = report_path.read_text(encoding="utf-8")
    assert "missing A-share universe snapshot" in report
    assert "contains no price forecast" in report


def test_pipeline_lock_rejects_overlap_and_recovers_stale_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "pipeline.lock"
    now = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    first = DailyPipelineLock(
        lock_path,
        stale_after=timedelta(hours=12),
        now=lambda: now,
    )
    with first:
        with pytest.raises(RuntimeError, match="already running"):
            with DailyPipelineLock(
                lock_path,
                stale_after=timedelta(hours=12),
                now=lambda: now,
            ):
                pass

    lock_path.write_text("stale", encoding="utf-8")
    old_timestamp = (now - timedelta(hours=13)).timestamp()
    lock_path.touch()
    os.utime(lock_path, (old_timestamp, old_timestamp))
    with DailyPipelineLock(
        lock_path,
        stale_after=timedelta(hours=12),
        now=lambda: now,
    ):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_clean_market_holiday_is_warning_but_provider_or_quality_error_is_failure() -> None:
    clean_no_data = InstrumentUpdateResult(
        symbol="AAPL",
        market="US",
        source="yahoo",
        provider="yfinance",
        status="no_data",
        start_date=date(2026, 7, 31),
        end_date=date(2026, 7, 31),
    )
    failed = InstrumentUpdateResult(
        symbol="000001",
        market="A",
        source="akshare",
        provider="akshare",
        status="failed",
        start_date=date(2026, 7, 31),
        end_date=date(2026, 7, 31),
        error="upstream unavailable",
    )
    invalid = InstrumentUpdateResult(
        symbol="0700",
        market="HK",
        source="yahoo",
        provider="yfinance",
        status="no_data",
        start_date=date(2026, 7, 31),
        end_date=date(2026, 7, 31),
        quality_issues=(
            QualityIssue(
                code="invalid_ohlc",
                message="high below close",
                severity=QualitySeverity.ERROR,
            ),
        ),
    )

    assert not _hard_market_update_failures(
        DailyUpdateReport(started_on=date(2026, 7, 31), results=(clean_no_data,))
    )
    failures = _hard_market_update_failures(
        DailyUpdateReport(started_on=date(2026, 7, 31), results=(failed, invalid))
    )
    assert len(failures) == 2


def test_pipeline_state_operations_retry_transient_database_failure(tmp_path: Path) -> None:
    runner, _factory, _settings = _runner(tmp_path)
    calls = 0

    def transient_operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("database temporarily unavailable")
        return "persisted"

    assert runner._state_operation("test state", transient_operation) == "persisted"
    assert calls == 2
