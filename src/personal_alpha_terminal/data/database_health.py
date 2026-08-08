from dataclasses import dataclass

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from personal_alpha_terminal.data.migrations import migration_root


@dataclass(frozen=True, slots=True)
class DatabaseHealthReport:
    ready: bool
    dialect: str
    server_version: str | None
    current_revision: str | None
    expected_revision: str
    foreign_key_count: int
    unvalidated_foreign_keys: int
    invalid_indexes: int
    transaction_isolation: str | None
    blockers: tuple[str, ...]


def expected_migration_head() -> str:
    root = migration_root()
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "migrations"))
    heads = ScriptDirectory.from_config(configuration).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found {len(heads)}")
    return heads[0]


def inspect_database_health(engine: Engine) -> DatabaseHealthReport:
    expected = expected_migration_head()
    blockers: list[str] = []
    with engine.connect() as connection:
        dialect = connection.dialect.name
        current_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        if dialect != "postgresql":
            blockers.append("production readiness requires PostgreSQL")
            return DatabaseHealthReport(
                ready=False,
                dialect=dialect,
                server_version=None,
                current_revision=current_revision,
                expected_revision=expected,
                foreign_key_count=0,
                unvalidated_foreign_keys=0,
                invalid_indexes=0,
                transaction_isolation=None,
                blockers=tuple(blockers),
            )

        server_version = str(connection.execute(text("SHOW server_version")).scalar_one())
        transaction_isolation = str(
            connection.execute(text("SHOW transaction_isolation")).scalar_one()
        )
        foreign_key_count, unvalidated_foreign_keys = connection.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE NOT convalidated) "
                "FROM pg_constraint "
                "WHERE contype = 'f' AND connamespace = current_schema()::regnamespace"
            )
        ).one()
        invalid_indexes = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND NOT i.indisvalid"
                )
            ).scalar_one()
        )

    if current_revision != expected:
        blockers.append(
            f"database revision {current_revision!r} does not match expected {expected!r}"
        )
    if int(foreign_key_count) == 0:
        blockers.append("no PostgreSQL foreign keys were detected")
    if int(unvalidated_foreign_keys):
        blockers.append(f"{unvalidated_foreign_keys} foreign keys are not validated")
    if invalid_indexes:
        blockers.append(f"{invalid_indexes} indexes are invalid")
    if transaction_isolation.lower() != "read committed":
        blockers.append(f"unexpected transaction isolation: {transaction_isolation}")
    return DatabaseHealthReport(
        ready=not blockers,
        dialect="postgresql",
        server_version=server_version,
        current_revision=current_revision,
        expected_revision=expected,
        foreign_key_count=int(foreign_key_count),
        unvalidated_foreign_keys=int(unvalidated_foreign_keys),
        invalid_indexes=invalid_indexes,
        transaction_isolation=transaction_isolation,
        blockers=tuple(blockers),
    )
