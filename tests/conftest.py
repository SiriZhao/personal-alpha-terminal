import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.data.database import build_engine, build_session_factory
from personal_alpha_terminal.models import Base


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
