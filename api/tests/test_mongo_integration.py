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


def test_orders_and_watchlist_read_real_mongo_documents(scratch_database, monkeypatch):
    # Confirms the collection names the routes rely on (`orders`, `watchlists`)
    # exist in a real MongoDB; mongomock would accept any name.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    user_id = ObjectId()
    other_user = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    scratch_database["orders"].insert_many(
        [
            {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "status": "OPEN",
             "createdAt": created, "updatedAt": created, "__v": 0},
            {"_id": ObjectId(), "user": other_user, "symbol": "TCS", "status": "OPEN",
             "createdAt": created, "updatedAt": created, "__v": 0},
        ]
    )
    scratch_database["watchlists"].insert_many(
        [
            {"_id": ObjectId(), "user": user_id, "symbol": "INFY",
             "createdAt": created, "updatedAt": created, "__v": 0},
            {"_id": ObjectId(), "user": other_user, "symbol": "TCS",
             "createdAt": created, "updatedAt": created, "__v": 0},
        ]
    )

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        orders = client.get("/api/orders", cookies={"token": token})
        watchlist = client.get("/api/watchlist", cookies={"token": token})

    assert orders.status_code == 200
    assert [order["symbol"] for order in orders.json()] == ["INFY"]
    assert orders.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert watchlist.status_code == 200
    assert [item["symbol"] for item in watchlist.json()] == ["INFY"]
    assert watchlist.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_positions_and_funds_read_real_mongo_documents(scratch_database, monkeypatch):
    # Confirms the collections the positions/funds routes use exist in a real
    # MongoDB, and that the derived funds maths reads real BSON documents.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    user_id = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    scratch_database["positions"].insert_one(
        {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "name": "Infosys",
         "exchange": "NSE", "side": "LONG", "product": "MIS", "qty": 5, "entry": 1500.0,
         "ltp": 1520.0, "createdAt": created, "updatedAt": created, "__v": 0}
    )
    scratch_database["funds"].insert_one(
        {"_id": ObjectId(), "user": user_id, "available": 50000,
         "createdAt": created, "updatedAt": created, "__v": 0}
    )
    scratch_database["transactions"].insert_one(
        {"_id": ObjectId(), "user": user_id, "kind": "SETTLEMENT",
         "method": "INFY MIS square-off", "amount": -250.5, "symbol": "INFY",
         "status": "COMPLETED", "createdAt": created, "updatedAt": created, "__v": 0}
    )

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        positions = client.get("/api/positions", cookies={"token": token})
        funds = client.get("/api/funds", cookies={"token": token})

    assert positions.status_code == 200
    assert [position["symbol"] for position in positions.json()] == ["INFY"]
    assert positions.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert funds.status_code == 200
    body = funds.json()
    assert body["available"] == 50000
    assert body["misMargin"] == 7500.0  # 1500 * 5
    assert body["usedMargin"] == 7500.0  # no open orders
    assert body["realizedPnl"] == -250.5


def test_portfolio_market_search_and_transactions_read_real_mongo_documents(
    scratch_database, monkeypatch
):
    # Confirms the newly used collection names (`portfoliosnapshots`,
    # `marketquotes`, `transactions`) resolve against a real MongoDB.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    user_id = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    scratch_database["holdings"].insert_one(
        {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "name": "Infosys",
         "exchange": "NSE", "qty": 2, "avgPrice": 100.0, "ltp": 110.0,
         "dayChangePct": 0.0, "sector": "", "createdAt": created, "updatedAt": created, "__v": 0}
    )
    scratch_database["portfoliosnapshots"].insert_one(
        {"_id": ObjectId(), "user": user_id, "date": datetime(2026, 9, 1, tzinfo=timezone.utc),
         "value": 200.0, "invested": 180.0, "misInvested": 0.0, "misValue": 0.0,
         "createdAt": created, "updatedAt": created, "__v": 0}
    )
    scratch_database["marketquotes"].insert_many(
        [
            {"_id": ObjectId(), "symbol": "^NSEI", "name": "NIFTY 50", "kind": "index",
             "ltp": 1.0, "dayChange": 0.0, "dayChangePct": 0.0, "prevClose": 0.0, "volume": 0,
             "marketCap": 0, "sector": "", "createdAt": created, "updatedAt": created, "__v": 0},
            {"_id": ObjectId(), "symbol": "INFY", "name": "Infosys", "kind": "stock",
             "ltp": 110.0, "dayChange": 0.0, "dayChangePct": 0.0, "prevClose": 0.0, "volume": 0,
             "marketCap": 0, "sector": "", "createdAt": created, "updatedAt": created, "__v": 0},
        ]
    )
    scratch_database["transactions"].insert_one(
        {"_id": ObjectId(), "user": user_id, "kind": "DEPOSIT", "method": "UPI",
         "amount": 5000.0, "symbol": "", "status": "COMPLETED",
         "createdAt": created, "updatedAt": created, "__v": 0}
    )

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        transactions = client.get("/api/funds/transactions", cookies={"token": token})
        history = client.get("/api/portfolio/history", params={"range": "ALL"}, cookies={"token": token})
        overview = client.get("/api/market/overview", cookies={"token": token})
        search = client.get("/api/instruments/search", params={"q": "INF"}, cookies={"token": token})

    assert transactions.status_code == 200
    assert [row["kind"] for row in transactions.json()] == ["DEPOSIT"]
    assert transactions.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert history.status_code == 200
    labels = [point["label"] for point in history.json()]
    assert "2026-09-01" in labels

    assert overview.status_code == 200
    assert [row["symbol"] for row in overview.json()["indices"]] == ["^NSEI"]
    assert [row["symbol"] for row in overview.json()["stocks"]] == ["INFY"]
    assert overview.json()["asOf"] == "2026-09-01T04:15:30.123Z"

    assert search.status_code == 200
    assert [row["symbol"] for row in search.json()] == ["INFY"]


