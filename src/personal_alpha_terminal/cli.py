import argparse
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import inspect, text

from personal_alpha_terminal.automation.service import run_daily_pipeline
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import get_engine, get_session_factory, session_scope
from personal_alpha_terminal.data.database_health import inspect_database_health
from personal_alpha_terminal.data.database_transfer import migrate_sqlite_to_postgresql
from personal_alpha_terminal.data.migrations import upgrade_database
from personal_alpha_terminal.data.postgres_backup import PostgresBackupManager
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)
from personal_alpha_terminal.portfolio.management_service import PortfolioManagementService
from personal_alpha_terminal.reports.service import ResearchReportService

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pat", description="Personal Alpha Terminal CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Initialize or migrate the database")
    subparsers.add_parser("migrate", help="Upgrade the database to the latest revision")
    subparsers.add_parser("doctor", help="Check configuration and database connectivity")
    subparsers.add_parser(
        "intelligence-status",
        help="Print versioned event/intelligence readiness as JSON",
    )
    subparsers.add_parser(
        "opportunities",
        help="Print the latest deterministic opportunity scan as JSON",
    )
    subparsers.add_parser("db-backup", help="Create and verify a PostgreSQL backup")
    restore = subparsers.add_parser(
        "db-restore-test",
        help="Restore a backup twice in a disposable database and verify corruption recovery",
    )
    restore.add_argument("backup", type=Path, help="Path to a .dump backup archive")
    restore.add_argument(
        "--target-url",
        default=None,
        help="Disposable PostgreSQL URL; database name must end with _restore_test",
    )
    subparsers.add_parser("db-check", help="Run PostgreSQL production-readiness checks")
    transfer = subparsers.add_parser(
        "db-import-sqlite",
        help="Atomically copy an upgraded SQLite database into an empty PostgreSQL database",
    )
    transfer.add_argument("--source-url", required=True, help="SQLite SQLAlchemy database URL")
    pipeline = subparsers.add_parser(
        "daily-pipeline",
        help="Run the fail-closed local daily quantitative research pipeline once",
    )
    pipeline.add_argument("--as-of-date", type=date.fromisoformat, default=None)
    pipeline.add_argument("--report", type=Path, default=None)
    pipeline.add_argument("--max-attempts", type=int, default=None)
    pipeline.add_argument(
        "--trigger",
        choices=("manual", "scheduler"),
        default="manual",
    )
    portfolio_report = subparsers.add_parser(
        "portfolio-report",
        help="Rebuild actual ledger performance and write PORTFOLIO_REPORT.md",
    )
    portfolio_report.add_argument("--portfolio-id", required=True, type=int)
    portfolio_report.add_argument("--benchmark-stock-id", required=True, type=int)
    portfolio_report.add_argument("--start-date", required=True, type=date.fromisoformat)
    portfolio_report.add_argument("--end-date", required=True, type=date.fromisoformat)
    portfolio_report.add_argument(
        "--output",
        type=Path,
        default=Path("PORTFOLIO_REPORT.md"),
    )
    return parser


def run_init_db() -> int:
    upgrade_database()
    engine = get_engine()
    table_names = ", ".join(sorted(inspect(engine).get_table_names()))
    logger.info("Database initialized with tables: %s", table_names)
    return 0


def run_doctor() -> int:
    settings = get_settings()
    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    logger.info(
        "Health check passed: env=%s database=%s",
        settings.app_env,
        engine.url.render_as_string(hide_password=True),
    )
    return 0


def run_intelligence_query(*, latest_scan: bool) -> int:
    from personal_alpha_terminal.application.app_service import ApplicationService

    service = ApplicationService(get_session_factory())
    payload = (
        service.get_latest_opportunity_scan()
        if latest_scan
        else service.get_intelligence_status()
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def run_database_check() -> int:
    report = inspect_database_health(get_engine())
    if not report.ready:
        for blocker in report.blockers:
            logger.error("Database readiness blocker: %s", blocker)
        return 1
    logger.info(
        "Database ready: PostgreSQL %s revision=%s foreign_keys=%s isolation=%s",
        report.server_version,
        report.current_revision,
        report.foreign_key_count,
        report.transaction_isolation,
    )
    return 0


def run_database_backup() -> int:
    result = PostgresBackupManager(get_settings()).create_backup()
    logger.info(
        "Verified PostgreSQL backup created: path=%s bytes=%s sha256=%s revision=%s",
        result.archive_path,
        result.size_bytes,
        result.sha256,
        result.alembic_revision,
    )
    return 0


def run_database_restore_test(backup: Path, target_url: str | None) -> int:
    manager = PostgresBackupManager(get_settings())
    result = manager.run_restore_test(backup, target_database_url=target_url)
    logger.info("PostgreSQL corruption recovery test:\n%s", manager.result_as_json(result))
    return 0 if result.passed else 1


def run_database_import(source_url: str) -> int:
    result = migrate_sqlite_to_postgresql(source_url, get_settings())
    logger.info(
        "SQLite data migrated atomically: tables=%s rows=%s source_revision=%s",
        len(result.tables),
        result.total_rows,
        result.source_revision,
    )
    return 0


def run_pipeline(
    *,
    as_of_date: date | None,
    report: Path | None,
    max_attempts: int | None,
    trigger: str,
) -> int:
    result = run_daily_pipeline(
        as_of_date=as_of_date,
        report_path=report,
        max_attempts=max_attempts,
        trigger=trigger,
    )
    logger.info(
        "Daily pipeline finished: run_id=%s date=%s status=%s report=%s tasks=%s",
        result.run_id,
        result.run_date,
        result.status,
        result.report_path,
        result.task_statuses,
    )
    has_task_failure = any(status == "failed" for status in result.task_statuses.values())
    return 2 if result.status == "failed" or has_task_failure else 0


def run_portfolio_report(
    *,
    portfolio_id: int,
    benchmark_stock_id: int,
    start_date: date,
    end_date: date,
    output: Path,
) -> int:
    settings = get_settings()
    with session_scope(get_session_factory()) as session:
        service = PortfolioManagementService(
            PortfolioManagementRepository(session),
            ResearchReportService(session),
            settings,
        )
        result, report = service.generate_report(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_stock_id,
            start_date=start_date,
            end_date=end_date,
            output_path=output.resolve(),
        )
        report_id = report.id
    logger.info(
        "Portfolio report generated: report_id=%s portfolio_id=%s date=%s value=%.2f path=%s",
        report_id,
        portfolio_id,
        result.as_of_date,
        result.total_value,
        output.resolve(),
    )
    return 0


def main() -> None:
    args = build_parser().parse_args()
    configure_logging()
    commands = {
        "init-db": run_init_db,
        "doctor": run_doctor,
        "db-check": run_database_check,
        "db-backup": run_database_backup,
    }
    commands["migrate"] = run_init_db
    if args.command == "db-restore-test":
        raise SystemExit(run_database_restore_test(args.backup, args.target_url))
    if args.command == "db-import-sqlite":
        raise SystemExit(run_database_import(args.source_url))
    if args.command == "daily-pipeline":
        raise SystemExit(
            run_pipeline(
                as_of_date=args.as_of_date,
                report=args.report,
                max_attempts=args.max_attempts,
                trigger=args.trigger,
            )
        )
    if args.command == "portfolio-report":
        raise SystemExit(
            run_portfolio_report(
                portfolio_id=args.portfolio_id,
                benchmark_stock_id=args.benchmark_stock_id,
                start_date=args.start_date,
                end_date=args.end_date,
                output=args.output,
            )
        )
    if args.command == "intelligence-status":
        raise SystemExit(run_intelligence_query(latest_scan=False))
    if args.command == "opportunities":
        raise SystemExit(run_intelligence_query(latest_scan=True))
    raise SystemExit(commands[args.command]())
