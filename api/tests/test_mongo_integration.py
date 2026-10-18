"""Optional integration test against a real, dedicated scratch MongoDB.

Skipped unless TEST_MONGO_URL is set. Example:

    TEST_MONGO_URL=mongodb://127.0.0.1:27017/tradium_fastapi_phase1_test \
        python -m pytest api/tests/test_mongo_integration.py

The database name must end with "_test" so this can never touch the live
`zerodha` database. The test writes only to its own database and drops it
afterwards.
"""

import os
from datetime import datetime, timezone

import jwt
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

from api.main import create_app

TEST_MONGO_URL = os.getenv("TEST_MONGO_URL")

pytestmark = pytest.mark.skipif(
    not TEST_MONGO_URL, reason="set TEST_MONGO_URL to run the real-MongoDB test"
)


@pytest.fixture
def scratch_database():
    if not TEST_MONGO_URL:
        pytest.skip("TEST_MONGO_URL is not set")

    client = MongoClient(TEST_MONGO_URL, serverSelectionTimeoutMS=5000)
    database = client.get_default_database()
    if not database.name.endswith("_test"):
        pytest.fail(f"refusing to run against database {database.name!r}")

    client.drop_database(database.name)
    try:
        yield database
    finally:
        client.drop_database(database.name)
        client.close()


def test_holdings_reads_real_mongo_documents(scratch_database, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    user_id = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)
    scratch_database["holdings"].insert_many(
        [
            {
                "_id": ObjectId(),
                "user": user_id,
                "symbol": "RELIANCE",
                "name": "Reliance Industries",
                "exchange": "NSE",
                "qty": 10,
                "avgPrice": 2400.5,
                "ltp": 2500.0,
                "dayChangePct": 1.25,
                "sector": "Energy",
                "createdAt": created,
                "updatedAt": created,
                "__v": 0,
            },
            {
                "_id": ObjectId(),
                "user": ObjectId(),
                "symbol": "TCS",
                "name": "Tata Consultancy",
                "exchange": "NSE",
                "qty": 5,
                "avgPrice": 3800.0,
                "ltp": 3900.0,
                "dayChangePct": 0.5,
                "sector": "IT",
                "createdAt": created,
                "updatedAt": created,
                "__v": 0,
            },
        ]
    )

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        response = client.get("/api/holdings", cookies={"token": token})

    assert response.status_code == 200
    body = response.json()
    assert [holding["symbol"] for holding in body] == ["RELIANCE"]
    holding = body[0]
    assert holding["user"] == str(user_id)
    assert type(holding["_id"]) is str and len(holding["_id"]) == 24
    # Real MongoDB stores BSON dates to the millisecond.
    assert holding["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert holding["__v"] == 0
