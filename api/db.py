"""MongoDB connection management.

One MongoClient is created when the app starts and closed when it stops.
FastAPI runs plain `def` endpoints in a worker thread, so the synchronous
PyMongo driver is safe here without adding an async driver.
"""

from pymongo import MongoClient
from pymongo.database import Database
from fastapi import Request

from .config import get_settings

_client: MongoClient | None = None


def connect() -> Database:
    """Open the shared client and return the database named in MONGO_URL."""
    global _client
    settings = get_settings()
    if not settings.mongo_url:
        raise RuntimeError("MONGO_URL is not set")

    # PyMongo returns the database named in the connection string, matching
    # how mongoose.connect(url) picks its database.
    _client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000)
    return _client.get_default_database()


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_database(request: Request) -> Database:
    """FastAPI dependency; tests override this with a fake database."""
    return request.app.state.db
