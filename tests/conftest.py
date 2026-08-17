from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.database import build_engine, build_session_factory
from personal_alpha_terminal.models import Base

_TEST_TEMP_ROOT = Path.cwd() / f".pytest-tmp-{uuid4().hex}"


@pytest.fixture
def tmp_path() -> Path:
    """Windows-safe replacement for pytest's Python 3.14 temp fixture.

    Python 3.14 applies mode 0700 to pytest's numbered directories on Windows.
    In the managed Codex workspace that can create a directory the current
    process cannot subsequently enumerate.  A repository-local ignored root
    preserves per-test isolation without changing product behavior.
    """

    _TEST_TEMP_ROOT.mkdir(exist_ok=True)
    path = _TEST_TEMP_ROOT / uuid4().hex
    path.mkdir()
    return path


@pytest.fixture
def engine() -> Engine:
    test_engine = build_engine("sqlite://")
    Base.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        # Every test owns a fresh in-memory SQLite engine. Dropping the complete
        # production schema here repeats hundreds of DDL statements without
        # improving isolation; disposing the engine discards the database.
        test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)
