import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.type_api import TypeEngine

from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.models import Base

# Historical Alembic revisions legitimately reference ``sa.TypeEngine`` in
# runtime-evaluated annotations.  Some frozen/packaged SQLAlchemy builds omit
# this public re-export, so restore it here (the single place every migration
# run passes through) without mutating the immutable revisions.
if getattr(sa, "TypeEngine", None) is None:
    setattr(sa, "TypeEngine", TypeEngine)  # noqa: B010 - compatibility export

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

if "PAT_DATABASE_URL" in os.environ:
    config.set_main_option(
        "sqlalchemy.url",
        get_settings().database_url.replace("%", "%%"),
    )
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
