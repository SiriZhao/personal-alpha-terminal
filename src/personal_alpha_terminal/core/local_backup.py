from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy.engine import make_url

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME

BACKUP_SCHEMA_VERSION = 1
SECRET_KEY_PATTERN = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


class LocalBackupError(RuntimeError):
    """Safe local-backup error whose message never contains secret values."""


@dataclass(frozen=True, slots=True)
class BackupPreview:
    archive: Path
    created_at: str
    product: str
    database_backend: str
    files: tuple[str, ...]
    valid: bool
    issues: tuple[str, ...]


def create_local_backup(
    settings: Settings,
    *,
    application_root: Path,
    backup_directory: Path,
) -> Path:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        raise LocalBackupError("local preview backup supports SQLite only")
    database = Path(url.database or "")
    if not database.is_absolute():
        database = database.resolve()
    if not database.is_file():
        raise LocalBackupError("SQLite database does not exist")
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = backup_directory / f"PAT-preview-{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="pat-backup-", dir=backup_directory) as raw_temp:
        staging = Path(raw_temp)
        database_copy = staging / "personal_alpha.db"
        _copy_sqlite_database(database, database_copy)
        config_source = application_root / "config.env"
        if config_source.is_file():
            (staging / "config.env").write_text(
                sanitize_env_text(config_source.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
        preferences = application_root / "user-preferences.json"
        if preferences.is_file():
            shutil.copy2(preferences, staging / preferences.name)
        report_index = tuple(
            sorted(
                str(path.relative_to(application_root))
                for path in (application_root / "reports").glob("*.md")
                if path.is_file()
            )
        )
        (staging / "report-index.json").write_text(
            json.dumps(report_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload_files = tuple(
            sorted(path for path in staging.iterdir() if path.name != "manifest.json")
        )
        manifest = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "product": PRODUCT_DISPLAY_NAME,
            "created_at": datetime.now(UTC).isoformat(),
            "database_backend": "sqlite",
            "files": {
                path.name: {
                    "size_bytes": path.stat().st_size,
                    "sha256": _file_hash(path),
                }
                for path in payload_files
            },
            "secrets_included": False,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_archive = archive.with_suffix(".tmp")
        with zipfile.ZipFile(
            temporary_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            for path in sorted(staging.iterdir()):
                bundle.write(path, path.name)
        temporary_archive.replace(archive)
    preview = inspect_backup(archive)
    if not preview.valid:
        archive.unlink(missing_ok=True)
        raise LocalBackupError("backup integrity validation failed")
    return archive


def inspect_backup(archive: Path) -> BackupPreview:
    issues: list[str] = []
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            bad_file = bundle.testzip()
            if bad_file:
                issues.append(f"CRC failure: {bad_file}")
            manifest_raw = json.loads(bundle.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest_raw, dict):
                raise ValueError("manifest is not an object")
            files = manifest_raw.get("files")
            if not isinstance(files, dict):
                raise ValueError("manifest files are invalid")
            for name, metadata in files.items():
                if not isinstance(name, str) or not isinstance(metadata, dict):
                    issues.append("invalid manifest entry")
                    continue
                payload = bundle.read(name)
                actual = sha256(payload).hexdigest()
                if actual != metadata.get("sha256"):
                    issues.append(f"SHA256 mismatch: {name}")
            if manifest_raw.get("secrets_included") is not False:
                issues.append("backup does not explicitly exclude secrets")
            return BackupPreview(
                archive=archive,
                created_at=str(manifest_raw.get("created_at", "unknown")),
                product=str(manifest_raw.get("product", "unknown")),
                database_backend=str(manifest_raw.get("database_backend", "unknown")),
                files=tuple(sorted(str(name) for name in files)),
                valid=not issues,
                issues=tuple(issues),
            )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
        return BackupPreview(
            archive=archive,
            created_at="unknown",
            product="unknown",
            database_backend="unknown",
            files=(),
            valid=False,
            issues=("backup archive or manifest is invalid",),
        )


def stage_restore(archive: Path, *, application_root: Path) -> Path:
    preview = inspect_backup(archive)
    if not preview.valid or preview.database_backend != "sqlite":
        raise LocalBackupError("backup is not a valid SQLite preview backup")
    request = application_root / "restore-request.json"
    temporary = request.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "archive": str(archive.resolve()),
                "requested_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(request)
    return request


def apply_pending_restore(application_root: Path, database: Path) -> bool:
    request = application_root / "restore-request.json"
    if not request.is_file():
        return False
    try:
        payload = json.loads(request.read_text(encoding="utf-8"))
        archive = Path(str(payload["archive"]))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise LocalBackupError("restore request is invalid") from error
    preview = inspect_backup(archive)
    if not preview.valid:
        raise LocalBackupError("restore archive failed integrity validation")
    safety_root = application_root / "backups" / "pre-restore"
    safety_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safety_copy = safety_root / f"personal_alpha-{stamp}.db"
    if database.is_file():
        shutil.copy2(database, safety_copy)
    temporary = database.with_suffix(".restore.tmp")
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            with bundle.open("personal_alpha.db") as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
        _validate_sqlite_file(temporary)
        database.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(database)
        request.unlink(missing_ok=True)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if safety_copy.is_file():
            shutil.copy2(safety_copy, database)
        raise LocalBackupError("restore failed; the pre-restore database was retained") from error
    return True


def list_backups(backup_directory: Path) -> tuple[BackupPreview, ...]:
    if not backup_directory.is_dir():
        return ()
    return tuple(
        inspect_backup(path)
        for path in sorted(backup_directory.glob("PAT-preview-*.zip"), reverse=True)
    )


def ensure_daily_backup(
    settings: Settings,
    *,
    application_root: Path,
    backup_directory: Path,
) -> Path | None:
    today = datetime.now(UTC).date()
    for preview in list_backups(backup_directory):
        try:
            if datetime.fromisoformat(preview.created_at).date() == today and preview.valid:
                return None
        except ValueError:
            continue
    return create_local_backup(
        settings,
        application_root=application_root,
        backup_directory=backup_directory,
    )


def sanitize_env_text(content: str) -> str:
    lines: list[str] = []
    for line in content.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        key, value = line.split("=", 1)
        lines.append(f"{key}=<redacted>" if SECRET_KEY_PATTERN.search(key) else f"{key}={value}")
    return "\n".join(lines) + "\n"


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    _validate_sqlite_file(destination)


def _validate_sqlite_file(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result is None or result[0] != "ok":
        raise LocalBackupError("SQLite integrity check failed")


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
