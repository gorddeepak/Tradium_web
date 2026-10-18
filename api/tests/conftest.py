"""Shared test fixtures.

The fast suite uses mongomock (in memory), so it never contacts a real
database. A separate optional suite can run against a scratch MongoDB
when TEST_MONGO_URL is set; see test_mongo_integration.py.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import mongomock
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
import jwt

# Make the repository root importable so `api.main` resolves.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import create_app  # noqa: E402

TEST_SECRET = "test-secret-not-a-real-key"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


@pytest.fixture
def database():
    return mongomock.MongoClient()["tradium_test"]


@pytest.fixture
def client(database):
    # raise_server_exceptions=False lets the 500 handler run like production.
    with TestClient(create_app(database=database), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def make_token():
    def _make_token(user_id, secret=TEST_SECRET, expires_in=7 * 24 * 60 * 60):
        payload = {"id": str(user_id), "exp": int(datetime.now(timezone.utc).timestamp()) + expires_in}
        return jwt.encode(payload, secret, algorithm="HS256")

    return _make_token


@pytest.fixture
def user_id():
    return ObjectId()


@pytest.fixture
def other_user_id():
    return ObjectId()


@pytest.fixture
def holdings_factory():
    """Build a holdings document shaped like the Mongoose model."""
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    def _make(user, symbol="RELIANCE", qty=10, avg_price=2400.5, **overrides):
        document = {
            "_id": ObjectId(),
            "user": user,
            "symbol": symbol,
            "name": "Reliance Industries",
            "exchange": "NSE",
            "qty": qty,
            "avgPrice": avg_price,
            "ltp": 2500.0,
            "dayChangePct": 1.25,
            "sector": "Energy",
            "createdAt": created,
            "updatedAt": created,
            "__v": 0,
        }
        document.update(overrides)
        return document

    return _make
