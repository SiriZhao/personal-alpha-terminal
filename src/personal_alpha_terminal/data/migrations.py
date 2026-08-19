import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.type_api import TypeEngine

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.data.database import build_engine

MIGRATION_ADVISORY_LOCK_ID = 1_347_176_768


def migration_root() -> Path:
    """Resolve migration assets in source and PyInstaller distributions."""

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root is not None:
        return Path(str(bundled_root))
    return Path(__file__).resolve().parents[3]


def _migration_target(database_url: str) -> str:
    """Return a useful target without exposing database credentials."""

    parsed = make_url(database_url)
    if parsed.get_backend_name() == "sqlite":
        if parsed.database is None:
            return "sqlite://"
        return str(Path(parsed.database).resolve())
    host = parsed.host or "local"
    database = parsed.database or "unknown"
    return f"{parsed.get_backend_name()}://{host}/{database}"


def upgrade_database(settings: Settings | None = None) -> None:
    # PyInstaller's SQLAlchemy hook can omit this public re-export even though
    # historical Alembic revisions legitimately reference ``sa.TypeEngine`` in
    # annotations.  Restore the public alias without mutating those immutable
    # revisions.
    if getattr(sa, "TypeEngine", None) is None:
        setattr(sa, "TypeEngine", TypeEngine)  # noqa: B010 - compatibility export
    resolved = settings or get_settings()
    root = migration_root()
    configuration = Config(str(root / "alembic.ini"))
    # Product bootstrap owns logging.  Alembic must not replace the terminal's
    # bounded/redacted handlers or print migration internals to end users.
    configuration.attributes["configure_logger"] = False
    configuration.set_main_option("script_location", str(root / "migrations"))
    configuration.set_main_option(
        "sqlalchemy.url",
        resolved.database_url.replace("%", "%%"),
    )
    target = _migration_target(resolved.database_url)
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
    except SQLAlchemyError as error:
        reason = str(error).splitlines()[0]
        raise RuntimeError(
            "database migration failed "
            f"operation=alembic-upgrade target={target} "
            f"error={type(error).__name__}: {reason}"
        ) from error
    finally:
        engine.dispose()
