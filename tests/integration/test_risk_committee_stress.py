from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from personal_alpha_terminal.data.database import build_engine


def test_corrupted_sqlite_database_fails_closed_without_overwrite(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupted.db"
    original = b"not-a-sqlite-database\x00risk-committee-fixture"
    database_path.write_bytes(original)

    with pytest.raises(DatabaseError):
        engine = build_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()

    assert database_path.read_bytes() == original
