import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from types import TracebackType
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.models import DailyPipelineRun, DailyTaskRun, Price

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    details: dict[str, object]


class TaskSkipped(RuntimeError):
    def __init__(self, reason: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(reason)
        self.details = details or {}


class TaskFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class PipelineContext:
    pipeline_run_id: int
    as_of_date: date
    trigger: str


TaskCallable = Callable[[PipelineContext], TaskOutcome]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    name: str
    execute: TaskCallable
    requires_quality_gate: bool = False


@dataclass(frozen=True, slots=True)
class PipelineExecution:
    run_id: int
    run_date: date
    status: str
    report_path: Path | None
    task_statuses: dict[str, str]


class DailyPipelineRunner:
    """Execute isolated tasks with durable state, retry, and fail-closed dependencies."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sleep = sleep
        self._now = now

    def run(
        self,
        tasks: tuple[TaskSpec, ...],
        *,
        as_of_date: date,
        trigger: str,
        max_attempts: int | None = None,
    ) -> PipelineExecution:
        if not tasks:
            raise ValueError("daily pipeline requires at least one task")
        names = [task.name for task in tasks]
        if len(set(names)) != len(names):
            raise ValueError("daily pipeline task names must be unique")
        attempts = max_attempts or self._settings.daily_pipeline_max_attempts
        if attempts < 1:
            raise ValueError("max_attempts must be positive")

        with DailyPipelineLock(
            self._settings.daily_pipeline_lock_path,
            stale_after=timedelta(hours=self._settings.daily_pipeline_lock_stale_hours),
            now=self._now,
        ):
            run_id = self._state_operation(
                "create pipeline run",
                partial(self._create_run, tasks, as_of_date, trigger, attempts),
            )
            context = PipelineContext(run_id, as_of_date, trigger)
            data_update_ready = False
            quality_ready = False
            for task in tasks:
                if task.requires_quality_gate and not (data_update_ready and quality_ready):
                    self._state_operation(
                        f"skip {task.name}",
                        partial(
                            self._mark_skipped,
                            run_id,
                            task.name,
                            "blocked because market-data update or quality gate did not pass",
                        ),
                    )
                    continue
                status = self._execute_task(run_id, task, context, attempts)
                if task.name == "market_data_update":
                    data_update_ready = status == "completed"
                elif task.name == "data_quality":
                    quality_ready = status == "completed"

            status, task_statuses, report_path = self._state_operation(
                "finalize pipeline run",
                partial(self._finalize_run, run_id),
            )
            return PipelineExecution(
                run_id=run_id,
                run_date=as_of_date,
                status=status,
                report_path=report_path,
                task_statuses=task_statuses,
            )

    def _create_run(
        self,
        tasks: tuple[TaskSpec, ...],
        as_of_date: date,
        trigger: str,
        max_attempts: int,
    ) -> int:
        with session_scope(self._session_factory) as session:
            pipeline = DailyPipelineRun(
                run_date=as_of_date,
                trigger=trigger,
                start_time=self._now(),
                status="running",
                summary={},
            )
            session.add(pipeline)
            session.flush()
            session.add_all(
                [
                    DailyTaskRun(
                        pipeline_run_id=pipeline.id,
                        task_name=task.name,
                        sequence=sequence,
                        status="pending",
                        attempt_count=0,
                        max_attempts=max_attempts,
                        details={},
                    )
                    for sequence, task in enumerate(tasks, start=1)
                ]
            )
            return pipeline.id

    def _execute_task(
        self,
        run_id: int,
        task: TaskSpec,
        context: PipelineContext,
        max_attempts: int,
    ) -> str:
        for attempt in range(1, max_attempts + 1):
            self._state_operation(
                f"mark {task.name} running",
                partial(self._mark_running, run_id, task.name, attempt),
            )
            try:
                outcome = task.execute(context)
            except TaskSkipped as error:
                self._state_operation(
                    f"mark {task.name} skipped",
                    partial(
                        self._mark_skipped,
                        run_id,
                        task.name,
                        str(error),
                        error.details,
                    ),
                )
                logger.warning("Daily task skipped: task=%s reason=%s", task.name, error)
                return "skipped"
            except Exception as error:
                retryable, details = _failure_metadata(error)
                will_retry = retryable and attempt < max_attempts
                logger.exception(
                    "Daily task failed: task=%s attempt=%s/%s retry=%s",
                    task.name,
                    attempt,
                    max_attempts,
                    will_retry,
                )
                if will_retry:
                    self._state_operation(
                        f"record {task.name} retry",
                        partial(self._mark_retry, run_id, task.name, error, details),
                    )
                    delay = self._settings.daily_pipeline_retry_backoff_seconds * (
                        2 ** (attempt - 1)
                    )
                    self._sleep(min(delay, 60.0))
                    continue
                self._state_operation(
                    f"mark {task.name} failed",
                    partial(self._mark_failed, run_id, task.name, error, details),
                )
                return "failed"
            self._state_operation(
                f"mark {task.name} completed",
                partial(self._mark_completed, run_id, task.name, outcome),
            )
            logger.info("Daily task completed: task=%s attempt=%s", task.name, attempt)
            return "completed"
        raise AssertionError("unreachable retry loop")

    def _state_operation(self, description: str, operation: Callable[[], T]) -> T:
        attempts = self._settings.daily_pipeline_max_attempts
        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except Exception:
                if attempt >= attempts:
                    raise
                delay = min(
                    self._settings.daily_pipeline_retry_backoff_seconds
                    * (2 ** (attempt - 1)),
                    60.0,
                )
                logger.exception(
                    "Daily pipeline state operation failed: operation=%s attempt=%s/%s; "
                    "retrying in %ss",
                    description,
                    attempt,
                    attempts,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable database state retry loop")

    def _mark_running(self, run_id: int, name: str, attempt: int) -> None:
        with session_scope(self._session_factory) as session:
            task = _task(session, run_id, name)
            task.status = "running"
            task.attempt_count = attempt
            task.error = None
            task.start_time = task.start_time or self._now()

    def _mark_retry(
        self,
        run_id: int,
        name: str,
        error: Exception,
        details: dict[str, object],
    ) -> None:
        with session_scope(self._session_factory) as session:
            task = _task(session, run_id, name)
            task.status = "pending"
            task.error = _safe_error(error)
            task.details = details

    def _mark_completed(self, run_id: int, name: str, outcome: TaskOutcome) -> None:
        with session_scope(self._session_factory) as session:
            task = _task(session, run_id, name)
            task.status = "completed"
            task.end_time = self._now()
            task.error = None
            task.details = outcome.details
            report_path = outcome.details.get("report_path")
            if name == "daily_report" and isinstance(report_path, str):
                pipeline = session.get(DailyPipelineRun, run_id)
                if pipeline is not None:
                    pipeline.report_path = report_path

    def _mark_failed(
        self,
        run_id: int,
        name: str,
        error: Exception,
        details: dict[str, object],
    ) -> None:
        with session_scope(self._session_factory) as session:
            task = _task(session, run_id, name)
            task.status = "failed"
            task.end_time = self._now()
            task.error = _safe_error(error)
            task.details = details

    def _mark_skipped(
        self,
        run_id: int,
        name: str,
        reason: str,
        details: dict[str, object] | None = None,
    ) -> None:
        with session_scope(self._session_factory) as session:
            task = _task(session, run_id, name)
            task.status = "skipped"
            task.end_time = self._now()
            task.error = reason[:4000]
            task.details = details or {}

    def _finalize_run(self, run_id: int) -> tuple[str, dict[str, str], Path | None]:
        with session_scope(self._session_factory) as session:
            pipeline = session.get(DailyPipelineRun, run_id)
            if pipeline is None:
                raise RuntimeError("daily pipeline run disappeared")
            tasks = list(
                session.scalars(
                    select(DailyTaskRun)
                    .where(DailyTaskRun.pipeline_run_id == run_id)
                    .order_by(DailyTaskRun.sequence)
                )
            )
            statuses = {task.task_name: task.status for task in tasks}
            critical_failed = any(
                statuses.get(name) != "completed"
                for name in ("market_data_update", "data_quality")
            )
            if critical_failed:
                status = "failed"
            elif any(value in {"failed", "skipped"} for value in statuses.values()):
                status = "partial"
            else:
                status = "completed"
            pipeline.status = status
            pipeline.end_time = self._now()
            pipeline.data_as_of = session.scalar(
                select(func.max(Price.trade_date)).where(Price.trade_date <= pipeline.run_date)
            )
            pipeline.summary = {
                "completed": sum(value == "completed" for value in statuses.values()),
                "failed": sum(value == "failed" for value in statuses.values()),
                "skipped": sum(value == "skipped" for value in statuses.values()),
                "total": len(statuses),
            }
            report_path = Path(pipeline.report_path) if pipeline.report_path else None
            return status, statuses, report_path


class DailyPipelineLock(AbstractContextManager["DailyPipelineLock"]):
    """A local exclusive lock that prevents overlapping scheduled/manual runs."""

    def __init__(
        self,
        path: Path,
        *,
        stale_after: timedelta,
        now: Callable[[], datetime],
    ) -> None:
        self._path = path.expanduser().resolve()
        self._stale_after = stale_after
        self._now = now
        self._token = uuid.uuid4().hex

    def __enter__(self) -> "DailyPipelineLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if attempt == 0 and self._is_stale():
                    if self._path.is_symlink():
                        raise RuntimeError(
                            "daily pipeline lock must not be a symbolic link"
                        ) from None
                    self._path.unlink(missing_ok=True)
                    continue
                raise RuntimeError(f"daily pipeline is already running: {self._path}") from None
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "token": self._token,
                        "pid": os.getpid(),
                        "created_at": self._now().isoformat(),
                    },
                    stream,
                )
            return self
        raise RuntimeError("could not acquire daily pipeline lock")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        if payload.get("token") == self._token and not self._path.is_symlink():
            self._path.unlink(missing_ok=True)

    def _is_stale(self) -> bool:
        try:
            modified = datetime.fromtimestamp(self._path.stat().st_mtime, UTC)
        except FileNotFoundError:
            return True
        return self._now() - modified > self._stale_after


def _task(session: Session, run_id: int, name: str) -> DailyTaskRun:
    task = session.scalar(
        select(DailyTaskRun).where(
            DailyTaskRun.pipeline_run_id == run_id,
            DailyTaskRun.task_name == name,
        )
    )
    if task is None:
        raise RuntimeError(f"daily task record disappeared: {name}")
    return task


def _failure_metadata(error: Exception) -> tuple[bool, dict[str, object]]:
    if isinstance(error, TaskFailure):
        return error.retryable, error.details
    return not isinstance(error, (ValueError, TypeError)), {
        "error_type": type(error).__name__,
    }


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:4000]
