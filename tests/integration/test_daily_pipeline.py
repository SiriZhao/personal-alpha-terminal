from datetime import date
from pathlib import Path

from personal_alpha_terminal.automation.service import run_daily_pipeline
from personal_alpha_terminal.core.config import Settings


def test_empty_database_pipeline_fails_closed_but_completes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "DAILY_PIPELINE_REPORT.md"
    quality_path = tmp_path / "DATA_QUALITY_REPORT.md"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'pipeline.db').as_posix()}",
        daily_pipeline_lock_path=tmp_path / "pipeline.lock",
        daily_pipeline_report_path=report_path,
        daily_pipeline_quality_report_path=quality_path,
        daily_pipeline_retry_backoff_seconds=0,
        daily_pipeline_max_attempts=1,
    )

    result = run_daily_pipeline(
        settings=settings,
        as_of_date=date(2026, 7, 31),
        max_attempts=1,
        sleep=lambda _delay: None,
    )

    assert result.status == "failed"
    assert result.task_statuses["market_data_update"] == "failed"
    assert result.task_statuses["data_quality"] == "failed"
    assert result.task_statuses["event_study"] == "skipped"
    assert result.task_statuses["portfolio_risk"] == "skipped"
    assert result.task_statuses["daily_report"] == "completed"
    assert report_path.exists()
    assert quality_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Projected final status: **failed**" in content
    assert "no active registered instruments" in content
