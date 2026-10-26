"""PostgreSQL engine and session management.

Authentication calls this module at request time (Phase 3B1); nothing
connects during application startup. The engine is created on first use so
importing the schema never requires a database.
"""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the shared engine, creating it from DATABASE_URL on first use."""
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    with get_session_factory()() as session:
        yield session


def dispose() -> None:
    """Close pooled connections, e.g. on app shutdown or between tests."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
