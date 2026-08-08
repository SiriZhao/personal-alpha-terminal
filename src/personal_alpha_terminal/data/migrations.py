import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.data.database import build_engine

MIGRATION_ADVISORY_LOCK_ID = 1_347_176_768


def migration_root() -> Path:
    """Resolve migration assets in source and PyInstaller distributions."""

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root is not None:
        return Path(str(bundled_root))
    return Path(__file__).resolve().parents[3]


def upgrade_database(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()
    root = migration_root()
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    configuration.set_main_option(
        "sqlalchemy.url",
        resolved.database_url.replace("%", "%%"),
    )
    engine = build_engine(
        resolved.database_url,
        echo=resolved.sql_echo,
        pool_size=resolved.database_pool_size,
        max_overflow=resolved.database_max_overflow,
        pool_timeout_seconds=resolved.database_pool_timeout_seconds,
        pool_recycle_seconds=resolved.database_pool_recycle_seconds,
        statement_timeout_ms=resolved.database_statement_timeout_ms,
        lock_timeout_ms=resolved.database_lock_timeout_ms,
        sslmode=resolved.database_sslmode,
        application_name=f"{resolved.database_application_name}-migration",
    )
    try:
        with engine.connect() as connection:
            is_postgresql = connection.dialect.name == "postgresql"
            if is_postgresql:
                connection.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                )
                connection.commit()
            try:
                configuration.attributes["connection"] = connection
                command.upgrade(configuration, "head")
            finally:
                if is_postgresql:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                    )
                    connection.commit()
    finally:
        engine.dispose()
