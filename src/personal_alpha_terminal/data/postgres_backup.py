import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import URL, make_url

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.database_health import expected_migration_head


class BackupError(RuntimeError):
    """A safe, user-facing backup or restore failure without credentials."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive_path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    alembic_revision: str
    removed_archives: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RestoreTestResult:
    archive_path: Path
    target_database: str
    initial_fingerprint: str
    corrupted_fingerprint: str
    recovered_fingerprint: str
    table_count: int
    foreign_key_count: int
    initial_restore_seconds: float
    recovery_seconds: float
    passed: bool


class PostgresBackupManager:
    """Create verified pg_dump archives and test recovery in an isolated database."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._source_url = _require_postgresql(settings.database_url, purpose="backup source")
        self._pg_dump = _resolve_executable(settings.database_pg_dump_path)
        self._pg_restore = _resolve_executable(settings.database_pg_restore_path)
        self._backup_dir = settings.database_backup_dir.expanduser().resolve()

    def create_backup(self, *, now: datetime | None = None) -> BackupResult:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"pat-{timestamp:%Y%m%dT%H%M%SZ}.dump"
        archive_path = self._backup_dir / archive_name
        partial_path = self._backup_dir / f".{archive_name}.partial"
        manifest_path = Path(f"{archive_path}.json")
        partial_manifest = Path(f"{manifest_path}.partial")
        if archive_path.exists() or manifest_path.exists():
            raise BackupError(f"backup already exists for timestamp: {timestamp.isoformat()}")

        revision = self._current_revision(self._source_url)
        if revision != expected_migration_head():
            raise BackupError(
                f"database revision {revision!r} is not at the expected Alembic head"
            )
        environment = _libpq_environment(
            self._source_url,
            sslmode=self._settings.database_sslmode,
        )
        try:
            self._run(
                [
                    self._pg_dump,
                    "--format=custom",
                    "--compress=9",
                    "--no-owner",
                    "--no-acl",
                    "--no-password",
                    "--serializable-deferrable",
                    f"--file={partial_path}",
                ],
                environment,
                operation="pg_dump",
            )
            if not partial_path.is_file() or partial_path.stat().st_size <= 0:
                raise BackupError("pg_dump completed without producing a non-empty archive")
            self._run(
                [self._pg_restore, "--list", str(partial_path)],
                environment,
                operation="pg_restore archive validation",
            )
            os.replace(partial_path, archive_path)
            _restrict_permissions(archive_path)
            digest = _sha256_file(archive_path)
            manifest = {
                "schema_version": 1,
                "created_at": timestamp.isoformat(),
                "archive_name": archive_path.name,
                "size_bytes": archive_path.stat().st_size,
                "sha256": digest,
                "database": _database_identity(self._source_url),
                "alembic_revision": revision,
                "dump_format": "postgresql_custom",
                "owner_acl_restored": False,
            }
            partial_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(partial_manifest, manifest_path)
            _restrict_permissions(manifest_path)
            removed = self._purge_expired(timestamp)
            return BackupResult(
                archive_path=archive_path,
                manifest_path=manifest_path,
                sha256=digest,
                size_bytes=archive_path.stat().st_size,
                alembic_revision=revision,
                removed_archives=removed,
            )
        except Exception:
            partial_path.unlink(missing_ok=True)
            partial_manifest.unlink(missing_ok=True)
            raise

    def validate_backup(self, archive_path: Path) -> dict[str, Any]:
        resolved = archive_path.expanduser().resolve()
        manifest_path = Path(f"{resolved}.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
            raise BackupError("backup manifest is missing or invalid") from error
        if not isinstance(manifest, dict):
            raise BackupError("backup manifest must be a JSON object")
        if manifest.get("archive_name") != resolved.name:
            raise BackupError("backup manifest archive name does not match")
        if not resolved.is_file():
            raise BackupError("backup archive does not exist")
        if manifest.get("size_bytes") != resolved.stat().st_size:
            raise BackupError("backup archive size does not match manifest")
        if manifest.get("sha256") != _sha256_file(resolved):
            raise BackupError("backup archive SHA256 does not match manifest")
        self._run(
            [self._pg_restore, "--list", str(resolved)],
            _libpq_environment(self._source_url, sslmode=self._settings.database_sslmode),
            operation="pg_restore archive validation",
        )
        return manifest

    def run_restore_test(
        self,
        archive_path: Path,
        *,
        target_database_url: str | None = None,
    ) -> RestoreTestResult:
        target_raw = target_database_url or self._settings.database_restore_test_url
        if not target_raw:
            raise BackupError("a disposable restore-test database URL is required")
        target_url = _require_postgresql(target_raw, purpose="restore-test target")
        target_database = target_url.database or ""
        if not target_database.endswith("_restore_test"):
            raise BackupError("restore-test database name must end with '_restore_test'")
        if _database_identity(target_url) == _database_identity(self._source_url):
            raise BackupError("restore-test target must not be the production database")

        resolved_archive = archive_path.expanduser().resolve()
        manifest = self.validate_backup(resolved_archive)
        environment = _libpq_environment(
            target_url,
            sslmode=self._settings.database_sslmode,
        )
        initial_restore_started = time.perf_counter()
        self._restore_archive(resolved_archive, environment)
        initial_restore_seconds = time.perf_counter() - initial_restore_started
        engine = self._target_engine(target_raw)
        try:
            initial = _database_fingerprint(engine)
            if initial["alembic_revision"] != manifest.get("alembic_revision"):
                raise BackupError("restored Alembic revision does not match backup manifest")
            _inject_disposable_corruption(engine)
            corrupted = _database_fingerprint(engine)
            if corrupted["fingerprint"] == initial["fingerprint"]:
                raise BackupError("corruption probe did not change the disposable database")
            recovery_started = time.perf_counter()
            self._restore_archive(resolved_archive, environment)
            recovered = _database_fingerprint(engine)
            recovery_seconds = time.perf_counter() - recovery_started
            passed = recovered["fingerprint"] == initial["fingerprint"]
            if not passed:
                raise BackupError("restored database fingerprint did not recover after corruption")
            return RestoreTestResult(
                archive_path=resolved_archive,
                target_database=target_database,
                initial_fingerprint=str(initial["fingerprint"]),
                corrupted_fingerprint=str(corrupted["fingerprint"]),
                recovered_fingerprint=str(recovered["fingerprint"]),
                table_count=_required_int(recovered, "table_count"),
                foreign_key_count=_required_int(recovered, "foreign_key_count"),
                initial_restore_seconds=initial_restore_seconds,
                recovery_seconds=recovery_seconds,
                passed=True,
            )
        finally:
            engine.dispose()

    @staticmethod
    def result_as_json(result: RestoreTestResult) -> str:
        payload = asdict(result)
        payload["archive_path"] = str(result.archive_path)
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _restore_archive(self, archive_path: Path, environment: dict[str, str]) -> None:
        self._run(
            [
                self._pg_restore,
                "--clean",
                "--if-exists",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--no-password",
                "--dbname",
                environment["PGDATABASE"],
                str(archive_path),
            ],
            environment,
            operation="pg_restore recovery test",
        )

    def _current_revision(self, url: URL) -> str:
        engine = self._target_engine(url.render_as_string(hide_password=False))
        try:
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        finally:
            engine.dispose()
        if not isinstance(revision, str) or not revision:
            raise BackupError("database has no Alembic revision")
        return revision

    def _target_engine(self, database_url: str) -> Engine:
        return build_engine(
            database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout_seconds=self._settings.database_pool_timeout_seconds,
            pool_recycle_seconds=self._settings.database_pool_recycle_seconds,
            statement_timeout_ms=self._settings.database_statement_timeout_ms,
            lock_timeout_ms=self._settings.database_lock_timeout_ms,
            sslmode=self._settings.database_sslmode,
            application_name=f"{self._settings.database_application_name}-backup",
        )

    def _purge_expired(self, now: datetime) -> tuple[Path, ...]:
        cutoff = now - timedelta(days=self._settings.database_backup_retention_days)
        removed: list[Path] = []
        for manifest_path in self._backup_dir.glob("pat-*.dump.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(str(payload["created_at"]))
                archive_path = self._backup_dir / str(payload["archive_name"])
            except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if created_at.astimezone(UTC) >= cutoff:
                continue
            if archive_path.parent != self._backup_dir or not archive_path.name.startswith("pat-"):
                continue
            archive_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            removed.append(archive_path)
        return tuple(removed)

    @staticmethod
    def _run(arguments: list[str], environment: dict[str, str], *, operation: str) -> None:
        try:
            completed = subprocess.run(
                arguments,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BackupError(f"{operation} could not be executed") from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise BackupError(f"{operation} failed: {detail[-1000:]}")


def _require_postgresql(database_url: str, *, purpose: str) -> URL:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not url.database or not url.username:
        raise BackupError(f"{purpose} requires a PostgreSQL URL with user and database")
    return url


def _resolve_executable(configured: str) -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(configured)
    if resolved:
        return resolved
    raise BackupError(f"PostgreSQL executable is unavailable: {configured}")


def _libpq_environment(url: URL, *, sslmode: str) -> dict[str, str]:
    environment = dict(os.environ)
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port or 5432),
        "PGDATABASE": url.database,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGSSLMODE": sslmode,
    }
    for key, value in values.items():
        if value is not None:
            environment[key] = value
    return environment


def _database_identity(url: URL) -> str:
    return f"{url.host or 'localhost'}:{url.port or 5432}/{url.database}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restrict_permissions(path: Path) -> None:
    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if not username:
            raise BackupError("cannot restrict Windows backup ACL without USERNAME")
        domain = os.environ.get("USERDOMAIN")
        identity = f"{domain}\\{username}" if domain else username
        completed = subprocess.run(
            [
                "icacls.exe",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{identity}:(R,W)",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise BackupError(f"failed to restrict Windows backup ACL: {detail}")
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise BackupError("failed to restrict backup file permissions") from error
    if mode != stat.S_IRUSR | stat.S_IWUSR:
        raise BackupError(f"backup file permissions are not owner-only: {oct(mode)}")


def _database_fingerprint(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        tables = list(
            connection.scalars(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() ORDER BY tablename"
                )
            )
        )
        counts: dict[str, int] = {}
        content_hashes: dict[str, str] = {}
        preparer = connection.dialect.identifier_preparer
        for table_name in tables:
            quoted = preparer.quote(str(table_name))
            counts[str(table_name)] = int(
                connection.execute(text(f"SELECT count(*) FROM {quoted}")).scalar_one()
            )
            table_digest = hashlib.sha256()
            row_hashes = connection.execution_options(stream_results=True).scalars(
                text(
                    f"SELECT md5(row_to_json(source_row)::text) FROM {quoted} AS source_row "
                    "ORDER BY md5(row_to_json(source_row)::text)"
                )
            )
            for row_hash in row_hashes:
                table_digest.update(str(row_hash).encode("ascii"))
                table_digest.update(b"\n")
            content_hashes[str(table_name)] = table_digest.hexdigest()
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
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
    if int(unvalidated_foreign_keys):
        raise BackupError("restored database contains unvalidated foreign keys")
    if invalid_indexes:
        raise BackupError("restored database contains invalid indexes")
    serialized = json.dumps(
        {
            "revision": revision,
            "counts": counts,
            "content_hashes": content_hashes,
            "foreign_keys": int(foreign_key_count),
            "unvalidated_foreign_keys": int(unvalidated_foreign_keys),
            "invalid_indexes": invalid_indexes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "fingerprint": hashlib.sha256(serialized).hexdigest(),
        "alembic_revision": revision,
        "table_count": len(tables),
        "foreign_key_count": int(foreign_key_count),
    }


def _inject_disposable_corruption(engine: Engine) -> None:
    with engine.begin() as connection:
        candidates = list(
            connection.scalars(
                text(
                "SELECT table_class.relname FROM pg_class AS table_class "
                "JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace "
                "WHERE namespace.nspname = current_schema() "
                "AND table_class.relkind = 'r' "
                "AND table_class.relname <> 'alembic_version' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM pg_constraint AS foreign_key "
                "  WHERE foreign_key.contype = 'f' "
                "  AND foreign_key.confrelid = table_class.oid"
                ") ORDER BY table_class.relname"
                )
            )
        )
        deleted = False
        for candidate in candidates:
            quoted = connection.dialect.identifier_preparer.quote(str(candidate))
            result = connection.execute(
                text(
                    f"DELETE FROM {quoted} "
                    f"WHERE ctid IN (SELECT ctid FROM {quoted} LIMIT 1)"
                )
            )
            if result.rowcount:
                deleted = True
                break
        if not deleted:
            raise BackupError(
                "restore-test database has no deletable business row; "
                "data-corruption recovery cannot be proven"
            )
        connection.execute(text("UPDATE alembic_version SET version_num = 'corrupted'"))


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackupError(f"database fingerprint has invalid {key}")
    return value
