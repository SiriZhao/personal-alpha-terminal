import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.postgres_backup import (
    BackupError,
    PostgresBackupManager,
    _restrict_permissions,
)


def _settings(tmp_path: Path) -> Settings:
    pg_dump = tmp_path / "pg_dump.exe"
    pg_restore = tmp_path / "pg_restore.exe"
    pg_dump.write_bytes(b"fake")
    pg_restore.write_bytes(b"fake")
    return Settings(
        _env_file=None,
        database_url=(
            "postgresql+psycopg://pat_user:top-secret@localhost:5432/personal_alpha"
        ),
        database_sslmode="require",
        database_backup_dir=tmp_path / "backups",
        database_backup_retention_days=30,
        database_pg_dump_path=str(pg_dump),
        database_pg_restore_path=str(pg_restore),
    )


def test_backup_is_atomic_verified_and_does_not_put_password_on_command_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PostgresBackupManager(_settings(tmp_path))
    commands: list[list[str]] = []

    monkeypatch.setattr(manager, "_current_revision", lambda _url: "f3c8a1d7e5b2")
    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup.expected_migration_head",
        lambda: "f3c8a1d7e5b2",
    )

    def fake_run(
        arguments: list[str],
        environment: dict[str, str],
        *,
        operation: str,
    ) -> None:
        commands.append(arguments)
        assert environment["PGPASSWORD"] == "top-secret"
        assert "top-secret" not in " ".join(arguments)
        if operation == "pg_dump":
            output = next(item.split("=", 1)[1] for item in arguments if item.startswith("--file="))
            Path(output).write_bytes(b"verified-custom-archive")

    monkeypatch.setattr(manager, "_run", fake_run)
    result = manager.create_backup(now=datetime(2026, 7, 31, 2, 0, tzinfo=UTC))

    assert result.archive_path.read_bytes() == b"verified-custom-archive"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == result.sha256
    assert manifest["alembic_revision"] == "f3c8a1d7e5b2"
    assert len(commands) == 2
    assert not list(result.archive_path.parent.glob("*.partial"))


def test_checksum_detects_corrupted_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PostgresBackupManager(_settings(tmp_path))
    monkeypatch.setattr(manager, "_current_revision", lambda _url: "f3c8a1d7e5b2")
    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup.expected_migration_head",
        lambda: "f3c8a1d7e5b2",
    )

    def fake_run(
        arguments: list[str],
        _environment: dict[str, str],
        *,
        operation: str,
    ) -> None:
        if operation == "pg_dump":
            output = next(item.split("=", 1)[1] for item in arguments if item.startswith("--file="))
            Path(output).write_bytes(b"original")

    monkeypatch.setattr(manager, "_run", fake_run)
    result = manager.create_backup(now=datetime(2026, 7, 31, 2, 0, tzinfo=UTC))
    result.archive_path.write_bytes(b"corrupt!")

    with pytest.raises(BackupError, match="SHA256"):
        manager.validate_backup(result.archive_path)


def test_retention_removes_only_expired_managed_backups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PostgresBackupManager(_settings(tmp_path))
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old_archive = backup_dir / "pat-20260101T020000Z.dump"
    old_manifest = Path(f"{old_archive}.json")
    old_archive.write_bytes(b"old")
    old_manifest.write_text(
        json.dumps(
            {
                "created_at": (datetime(2026, 7, 31, tzinfo=UTC) - timedelta(days=31)).isoformat(),
                "archive_name": old_archive.name,
            }
        ),
        encoding="utf-8",
    )
    unrelated = backup_dir / "manual.dump"
    unrelated.write_bytes(b"keep")
    monkeypatch.setattr(manager, "_current_revision", lambda _url: "f3c8a1d7e5b2")
    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup.expected_migration_head",
        lambda: "f3c8a1d7e5b2",
    )

    def fake_run(
        arguments: list[str],
        _environment: dict[str, str],
        *,
        operation: str,
    ) -> None:
        if operation == "pg_dump":
            output = next(item.split("=", 1)[1] for item in arguments if item.startswith("--file="))
            Path(output).write_bytes(b"new")

    monkeypatch.setattr(manager, "_run", fake_run)
    result = manager.create_backup(now=datetime(2026, 7, 31, 2, 0, tzinfo=UTC))

    assert old_archive in result.removed_archives
    assert not old_archive.exists()
    assert unrelated.exists()


def test_restore_test_requires_disposable_suffix(
    tmp_path: Path,
) -> None:
    manager = PostgresBackupManager(_settings(tmp_path))

    with pytest.raises(BackupError, match="_restore_test"):
        manager.run_restore_test(
            tmp_path / "missing.dump",
            target_database_url=(
                "postgresql+psycopg://pat_restore:secret@localhost/personal_alpha"
            ),
        )


def test_corruption_recovery_orchestration_requires_exact_fingerprint_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PostgresBackupManager(_settings(tmp_path))
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    fingerprints: list[dict[str, Any]] = [
        {
            "fingerprint": "healthy",
            "alembic_revision": "f3c8a1d7e5b2",
            "table_count": 40,
            "foreign_key_count": 60,
        },
        {
            "fingerprint": "corrupted",
            "alembic_revision": "corrupted",
            "table_count": 40,
            "foreign_key_count": 60,
        },
        {
            "fingerprint": "healthy",
            "alembic_revision": "f3c8a1d7e5b2",
            "table_count": 40,
            "foreign_key_count": 60,
        },
    ]

    class FakeEngine:
        def dispose(self) -> None:
            pass

    monkeypatch.setattr(
        manager,
        "validate_backup",
        lambda _path: {"alembic_revision": "f3c8a1d7e5b2"},
    )
    monkeypatch.setattr(manager, "_restore_archive", lambda _path, _environment: None)
    monkeypatch.setattr(manager, "_target_engine", lambda _url: FakeEngine())
    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup._database_fingerprint",
        lambda _engine: fingerprints.pop(0),
    )
    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup._inject_disposable_corruption",
        lambda _engine: None,
    )

    result = manager.run_restore_test(
        archive,
        target_database_url=(
            "postgresql+psycopg://pat_restore:secret@localhost/personal_alpha_restore_test"
        ),
    )

    assert result.passed
    assert result.initial_fingerprint == result.recovered_fingerprint
    assert result.corrupted_fingerprint != result.recovered_fingerprint
    assert result.initial_restore_seconds >= 0
    assert result.recovery_seconds >= 0


def test_windows_backup_acl_removes_inheritance_and_grants_only_current_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "backup.dump"
    target.write_bytes(b"backup")
    calls: list[list[str]] = []

    monkeypatch.setattr("personal_alpha_terminal.data.postgres_backup.os.name", "nt")
    monkeypatch.setenv("USERNAME", "Research User")
    monkeypatch.setenv("USERDOMAIN", "WORKSTATION")

    def fake_run(arguments: list[str], **_kwargs: Any) -> Any:
        calls.append(arguments)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup.subprocess.run",
        fake_run,
    )

    _restrict_permissions(target)

    assert calls == [
        [
            "icacls.exe",
            str(target),
            "/inheritance:r",
            "/grant:r",
            "WORKSTATION\\Research User:(R,W)",
        ]
    ]


def test_windows_backup_acl_failure_is_not_silenced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "backup.dump"
    target.write_bytes(b"backup")
    monkeypatch.setattr("personal_alpha_terminal.data.postgres_backup.os.name", "nt")
    monkeypatch.setenv("USERNAME", "Research User")
    monkeypatch.setenv("USERDOMAIN", "WORKSTATION")

    def fake_run(_arguments: list[str], **_kwargs: Any) -> Any:
        return type(
            "Completed",
            (),
            {"returncode": 5, "stdout": "", "stderr": "access denied"},
        )()

    monkeypatch.setattr(
        "personal_alpha_terminal.data.postgres_backup.subprocess.run",
        fake_run,
    )

    with pytest.raises(BackupError, match="access denied"):
        _restrict_permissions(target)
