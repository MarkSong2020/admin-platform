# isort: skip_file
# Alembic env.py uses a designated "register models" block whose import
# layout is part of the file's contract (the generator inserts side-effect
# imports there). isort's grouping rules conflict with this layout once two
# or more domains are registered. File-level isort skip is the cleanest
# fix; ``# ruff: noqa: I001`` would otherwise trip RUF100 (unused-noqa)
# when only one domain is patched in.
"""Alembic async migration environment.

Loads database URL from ``admin_platform.core.config.Settings`` rather than
``alembic.ini`` so production secrets stay out of the repository.

Add new ORM model modules to the import block below so ``autogenerate`` can
diff them against the live schema.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from admin_platform.core.config import get_settings
from admin_platform.db.base import Base

# --- Register models here for autogenerate ----------------------------------
# Import every module that defines ORM models so Base.metadata is populated.
# Side-effect-only imports（noqa F401）：把 model 类注册进 Base.metadata，
# 供 autogenerate / alembic check 与 live schema 做 diff。
from admin_platform.domains.user.models import User  # noqa: F401

# ----------------------------------------------------------------------------

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # v0.4.12: catch ``server_default=`` drift between models and the
        # migration chain. Default Alembic skips this comparison, which
        # silently lets ``func.now()`` ⇄ ``CURRENT_TIMESTAMP`` and other
        # default-value edits slip past ``alembic check`` / autogenerate.
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
