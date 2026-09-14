from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, inspect, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from lab21_bot.config import get_settings
from lab21_bot.models import Base

# bot and admin both run `alembic upgrade head` on start; without a lock a fresh
# database gets migrated twice in parallel and the second run dies on duplicates.
MIGRATION_LOCK_KEY = 218421

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
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


def _is_fresh_database(connection: Connection) -> bool:
    tables = set(inspect(connection).get_table_names())
    return "alembic_version" not in tables and "users" not in tables


def _bootstrap_schema(connection: Connection, head: str) -> None:
    """Build the schema from the models and mark the whole chain as applied.

    Revision 0001 creates tables straight from the live models, so replaying the
    later incremental revisions on an empty database fails on columns that 0001
    already created.
    """
    target_metadata.create_all(bind=connection)
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
        {"revision": head},
    )


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
        head = context.get_head_revision()
        if head is not None and _is_fresh_database(connection):
            _bootstrap_schema(connection, head)
        else:
            context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

