"""Alembic environment.

Migrations use DIRECT_DATABASE_URL (the unpooled connection). Keeping the URL
out of alembic.ini prevents credentials from reaching source control.
"""

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import get_direct_database_url  # noqa: E402
from api.postgres.base import Base  # noqa: E402
from api.postgres import models  # noqa: E402,F401  (register tables on Base.metadata)

config = context.config


def _database_url() -> str:
    url = get_direct_database_url()
    if not url:
        url = config.get_main_option("sqlalchemy.url", "").strip()
    if not url:
        raise RuntimeError(
            "DIRECT_DATABASE_URL is not set. Alembic needs the direct "
            "(non-pooled) PostgreSQL connection string."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
