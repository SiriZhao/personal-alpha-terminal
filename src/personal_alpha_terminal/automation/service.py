import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from personal_alpha_terminal.automation.runner import DailyPipelineRunner, PipelineExecution
from personal_alpha_terminal.automation.tasks import default_daily_tasks
from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.data.database import configure_database
from personal_alpha_terminal.data.migrations import upgrade_database

logger = logging.getLogger(__name__)


def run_daily_pipeline(
    *,
    settings: Settings | None = None,
    as_of_date: date | None = None,
    trigger: str = "manual",
    report_path: Path | None = None,
    max_attempts: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PipelineExecution:
    """Migrate, initialize, and run the local daily pipeline once."""

    resolved = settings or get_settings()
    local_today = datetime.now(ZoneInfo(resolved.daily_pipeline_timezone)).date()
    research_date = as_of_date or local_today
    if research_date > local_today:
        raise ValueError("daily pipeline cannot run for a future research date")
    attempts = max_attempts or resolved.daily_pipeline_max_attempts
    _upgrade_with_retry(resolved, attempts=attempts, sleep=sleep)
    _engine, session_factory = configure_database(resolved)
    runner = DailyPipelineRunner(
        session_factory,
        resolved,
        sleep=sleep,
    )
    return runner.run(
        default_daily_tasks(
            session_factory,
            resolved,
            report_path=report_path,
        ),
        as_of_date=research_date,
        trigger=trigger,
        max_attempts=attempts,
    )


def _upgrade_with_retry(
    settings: Settings,
    *,
    attempts: int,
    sleep: Callable[[float], None],
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            upgrade_database(settings)
            return
        except Exception:
            if attempt >= attempts:
                raise
            delay = min(settings.daily_pipeline_retry_backoff_seconds * (2 ** (attempt - 1)), 60)
            logger.exception(
                "Database migration/connectivity failed before daily pipeline; retrying in %ss",
                delay,
            )
            sleep(delay)
