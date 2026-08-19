"""ROUND80 migration failures must fail fast with a precise safe target."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data import migrations


def test_migration_failure_includes_operation_and_sqlite_path(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "authority.db"
    settings = Settings(database_url=f"sqlite:///{database}")

    def fail(*_args, **_kwargs) -> None:
        raise OperationalError("CREATE TABLE", {}, Exception("readonly database"))

    monkeypatch.setattr(migrations.command, "upgrade", fail)
    with pytest.raises(RuntimeError, match="operation=alembic-upgrade") as captured:
        migrations.upgrade_database(settings)
    message = str(captured.value)
    assert str(database.resolve()) in message
    assert "OperationalError" in message
    assert "CREATE TABLE" not in message


def test_migration_target_redacts_postgresql_credentials() -> None:
    target = migrations._migration_target("postgresql://user:secret@db.example/alpha")
    assert target == "postgresql://db.example/alpha"
    assert "secret" not in target
