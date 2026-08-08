import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, text
from sqlalchemy.engine import make_url

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.database_health import expected_migration_head
from personal_alpha_terminal.models import Base


class DatabaseTransferError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TableTransferResult:
    table_name: str
    row_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DatabaseTransferResult:
    source_revision: str
    target_revision: str
    total_rows: int
    tables: tuple[TableTransferResult, ...]


def migrate_sqlite_to_postgresql(
    source_database_url: str,
    settings: Settings,
    *,
    batch_size: int = 1000,
) -> DatabaseTransferResult:
    source_url = make_url(source_database_url)
    target_url = make_url(settings.database_url)
    if source_url.get_backend_name() != "sqlite":
        raise DatabaseTransferError("source database must be SQLite")
    if target_url.get_backend_name() != "postgresql":
        raise DatabaseTransferError("target database must be PostgreSQL")
    source_engine = build_engine(source_database_url)
    target_engine = build_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        statement_timeout_ms=settings.database_statement_timeout_ms,
        lock_timeout_ms=settings.database_lock_timeout_ms,
        sslmode=settings.database_sslmode,
        application_name=f"{settings.database_application_name}-transfer",
    )
    try:
        source_revision = _revision(source_engine)
        target_revision = _revision(target_engine)
        expected = expected_migration_head()
        if source_revision != expected or target_revision != expected:
            raise DatabaseTransferError(
                "source and target must both be migrated to the current Alembic head"
            )
        result = copy_database_contents(
            source_engine,
            target_engine,
            batch_size=batch_size,
        )
        return DatabaseTransferResult(
            source_revision=source_revision,
            target_revision=target_revision,
            total_rows=result.total_rows,
            tables=result.tables,
        )
    finally:
        source_engine.dispose()
        target_engine.dispose()


def copy_database_contents(
    source_engine: Engine,
    target_engine: Engine,
    *,
    batch_size: int = 1000,
) -> DatabaseTransferResult:
    """Copy all ORM tables atomically; intended for testing and one-time migration."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    with source_engine.connect() as source, target_engine.begin() as target:
        populated = [
            table.name
            for table in Base.metadata.sorted_tables
            if target.scalar(select(func.count()).select_from(table))
        ]
        if populated:
            raise DatabaseTransferError(
                "target database must be empty; populated tables: " + ", ".join(populated[:10])
            )

        source_digests: dict[str, tuple[int, str]] = {}
        for table in Base.metadata.sorted_tables:
            source_digests[table.name] = _table_digest(source, table)
            result = source.execute(select(table).order_by(*table.primary_key.columns))
            for partition in result.mappings().partitions(batch_size):
                if partition:
                    target.execute(insert(table), [dict(row) for row in partition])

        transferred: list[TableTransferResult] = []
        for table in Base.metadata.sorted_tables:
            source_count, source_digest = source_digests[table.name]
            target_count, target_digest = _table_digest(target, table)
            if target_count != source_count or target_digest != source_digest:
                raise DatabaseTransferError(
                    f"transfer validation failed for {table.name}: "
                    f"source={source_count}/{source_digest} "
                    f"target={target_count}/{target_digest}"
                )
            transferred.append(
                TableTransferResult(
                    table_name=table.name,
                    row_count=source_count,
                    sha256=source_digest,
                )
            )
        if target.dialect.name == "postgresql":
            _reset_postgresql_sequences(target)

    return DatabaseTransferResult(
        source_revision="not_checked",
        target_revision="not_checked",
        total_rows=sum(item.row_count for item in transferred),
        tables=tuple(transferred),
    )


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    if not isinstance(revision, str) or not revision:
        raise DatabaseTransferError("database has no Alembic revision")
    return revision


def _table_digest(connection: Connection, table: Any) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    result = connection.execute(select(table).order_by(*table.primary_key.columns)).mappings()
    for row in result:
        encoded = json.dumps(
            {column.name: _canonical_value(row[column.name]) for column in table.columns},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return {"type": "datetime", "value": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    return value


def _reset_postgresql_sequences(connection: Connection) -> None:
    preparer = connection.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            continue
        column = primary_keys[0]
        if not column.autoincrement:
            continue
        quoted_table = preparer.quote(table.name)
        quoted_column = preparer.quote(column.name)
        connection.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
                f"COALESCE(MAX({quoted_column}), 1), MAX({quoted_column}) IS NOT NULL) "
                f"FROM {quoted_table}"
            ),
            {"table_name": table.name, "column_name": column.name},
        )
