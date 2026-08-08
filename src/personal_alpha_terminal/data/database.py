from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.models import Base

SessionFactory = sessionmaker[Session]

_engine: Engine | None = None
_session_factory: SessionFactory | None = None


def _prepare_sqlite_directory(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def build_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
    statement_timeout_ms: int = 120_000,
    lock_timeout_ms: int = 10_000,
    sslmode: str = "prefer",
    application_name: str = "personal-alpha-terminal",
) -> Engine:
    """Build a portable SQLAlchemy engine for SQLite or PostgreSQL."""

    _prepare_sqlite_directory(database_url)
    url = make_url(database_url)
    options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}

    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False}
        if not url.database or url.database == ":memory:":
            options["poolclass"] = StaticPool
    elif url.get_backend_name() == "postgresql":
        options.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout_seconds,
                "pool_recycle": pool_recycle_seconds,
                "isolation_level": "READ COMMITTED",
                "connect_args": {
                    "application_name": application_name,
                    "sslmode": sslmode,
                    "options": (
                        f"-c statement_timeout={statement_timeout_ms} "
                        f"-c lock_timeout={lock_timeout_ms}"
                    ),
                },
            }
        )

    engine = create_engine(database_url, **options)
    if url.get_backend_name() == "sqlite":
        _configure_sqlite_integrity(engine, file_database=bool(url.database))
    return engine


def _configure_sqlite_integrity(engine: Engine, *, file_database: bool) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if file_database:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def build_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_database(settings: Settings | None = None) -> tuple[Engine, SessionFactory]:
    global _engine, _session_factory

    resolved = settings or get_settings()
    _engine = build_engine(
        resolved.database_url,
        echo=resolved.sql_echo,
        pool_size=resolved.database_pool_size,
        max_overflow=resolved.database_max_overflow,
        pool_timeout_seconds=resolved.database_pool_timeout_seconds,
        pool_recycle_seconds=resolved.database_pool_recycle_seconds,
        statement_timeout_ms=resolved.database_statement_timeout_ms,
        lock_timeout_ms=resolved.database_lock_timeout_ms,
        sslmode=resolved.database_sslmode,
        application_name=resolved.database_application_name,
    )
    _session_factory = build_session_factory(_engine)
    return _engine, _session_factory


def get_engine() -> Engine:
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def get_session_factory() -> SessionFactory:
    if _session_factory is None:
        configure_database()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope(factory: SessionFactory | None = None) -> Generator[Session, None, None]:
    """Provide a transaction boundary with commit/rollback/close semantics."""

    session = (factory or get_session_factory())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database(engine: Engine | None = None) -> None:
    """Create tables for local development and tests.

    Production deployments should use Alembic migrations.
    """

    Base.metadata.create_all(engine or get_engine())
