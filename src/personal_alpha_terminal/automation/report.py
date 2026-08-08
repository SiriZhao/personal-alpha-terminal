from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import DailyPipelineRun, DailyTaskRun, Price


def render_daily_pipeline_report(
    session: Session,
    pipeline_run_id: int,
    *,
    assume_report_completed: bool = False,
) -> str:
    """Render an operational report without generating investment conclusions."""

    pipeline = session.get(DailyPipelineRun, pipeline_run_id)
    if pipeline is None:
        raise ValueError("daily pipeline run does not exist")
    tasks = list(
        session.scalars(
            select(DailyTaskRun)
            .where(DailyTaskRun.pipeline_run_id == pipeline_run_id)
            .order_by(DailyTaskRun.sequence)
        )
    )
    projected = {
        task.task_name: (
            "completed"
            if assume_report_completed
            and task.task_name == "daily_report"
            and task.status == "running"
            else task.status
        )
        for task in tasks
    }
    projected_status = _pipeline_status(projected)
    latest_trade_date, latest_ingested = session.execute(
        select(func.max(Price.trade_date), func.max(Price.ingested_at)).where(
            Price.trade_date <= pipeline.run_date
        )
    ).one()
    latest_rows = 0
    if latest_trade_date is not None:
        latest_rows = int(
            session.scalar(
                select(func.count()).select_from(Price).where(
                    Price.trade_date == latest_trade_date
                )
            )
            or 0
        )

    lines = [
        "# Personal Alpha Terminal Daily Pipeline Report",
        "",
        f"- Pipeline run ID: `{pipeline.id}`",
        f"- Research date: `{pipeline.run_date.isoformat()}`",
        f"- Trigger: `{pipeline.trigger}`",
        f"- Projected final status: **{projected_status}**",
        f"- Started: `{_time(pipeline.start_time)}`",
        f"- Report generated: `{datetime.now(UTC).isoformat()}`",
        "",
        "> This is an operational and data-quality report. It contains no price forecast, "
        "trade instruction, or unsupported investment recommendation.",
        "",
        "## Execution Status",
        "",
        "| Task | Status | Attempts | Start | End | Error |",
        "|---|---:|---:|---|---|---|",
    ]
    for task in tasks:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(task.task_name),
                    _cell(projected[task.task_name]),
                    str(task.attempt_count),
                    _cell(_time(task.start_time)),
                    _cell(_time(task.end_time)),
                    _cell(task.error or ""),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Data Freshness",
            "",
            f"- Latest persisted trading date: `{latest_trade_date or 'N/A'}`",
            f"- Latest ingestion timestamp: `{_time(latest_ingested)}`",
            f"- Rows on latest trading date: `{latest_rows}`",
            "- Freshness is reported from persisted `prices`; it does not prove every market "
            "or instrument is complete.",
            "",
            "## Failed or Blocked Tasks",
            "",
        ]
    )
    problems = [task for task in tasks if projected[task.task_name] in {"failed", "skipped"}]
    if problems:
        lines.extend(
            f"- **{task.task_name}** [{projected[task.task_name]}]: "
            f"{task.error or 'No error detail recorded.'}"
            for task in problems
        )
    else:
        lines.append("- None.")

    lines.extend(["", "## Exceptions and Anomalies", ""])
    anomaly_lines: list[str] = []
    for task in tasks:
        warnings = task.details.get("warnings", [])
        failures = task.details.get("failures", [])
        blockers = task.details.get("blockers", [])
        for label, values in (
            ("warning", warnings),
            ("failure", failures),
            ("quality blocker", blockers),
        ):
            if isinstance(values, list):
                anomaly_lines.extend(
                    f"- **{task.task_name} / {label}:** {item}" for item in values[:20]
                )
    lines.extend(anomaly_lines or ["- No structured anomaly was recorded."])

    lines.extend(
        [
            "",
            "## Data Sources and Logic",
            "",
            "- Task status: `daily_pipeline_runs`, `daily_task_runs`.",
            "- Data freshness: `prices.trade_date`, `prices.ingested_at`.",
            "- Market-data validation: latest persisted quality run produced by the fail-closed "
            "Market Data Quality System.",
            "- Analysis tasks use only persisted point-in-time data up to the research date.",
            "- Event, conditional-probability, and portfolio tasks reuse explicit parameters "
            "from their latest successful run; missing configurations are never guessed.",
            "",
            "## Known Limitations",
            "",
            "- A completed task means its code path and configured safeguards succeeded; it is "
            "not evidence that a statistical result will remain stable.",
            "- A skipped analysis is not silently treated as success.",
            "- Retries provide at-least-once execution. Persisted analytical runs remain "
            "auditable and may include multiple attempts after transient failures.",
            "- Data-source outages, exchange holidays, late data, and incomplete corporate "
            "actions can reduce freshness or block analysis.",
        ]
    )
    return "\n".join(lines)


def _pipeline_status(statuses: dict[str, str]) -> str:
    if any(statuses.get(name) != "completed" for name in ("market_data_update", "data_quality")):
        return "failed"
    if any(status in {"failed", "skipped"} for status in statuses.values()):
        return "partial"
    return "completed"


def _time(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return "N/A"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
