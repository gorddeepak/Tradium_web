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

import bcrypt
import jwt
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from sqlalchemy import select

from api.main import create_app
from api.jobs.portfolio_snapshot import record_daily_snapshot, snapshot_date
from api.jobs.price_sync import run_sync
from api.postgres.models import User
from api.postgres.session import get_session

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


def test_orders_read_real_mongo_documents(scratch_database, monkeypatch):
    # Confirms the collection name the route relies on (`orders`) exists in a
    # real MongoDB; mongomock would accept any name. Watchlists moved to
    # PostgreSQL in Phase 3B3 and are covered by the PostgreSQL suite.
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

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        orders = client.get("/api/orders", cookies={"token": token})

    assert orders.status_code == 200
    assert [order["symbol"] for order in orders.json()] == ["INFY"]
    assert orders.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"


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


def test_portfolio_and_transactions_read_real_mongo_documents(
    scratch_database, monkeypatch
):
    # Confirms the newly used collection names (`portfoliosnapshots`,
    # `transactions`) resolve against a real MongoDB. Market data moved to
    # PostgreSQL in Phase 3B2 and is covered by the PostgreSQL suite.
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

    assert transactions.status_code == 200
    assert [row["kind"] for row in transactions.json()] == ["DEPOSIT"]
    assert transactions.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert history.status_code == 200
    labels = [point["label"] for point in history.json()]
    assert "2026-09-01" in labels



def test_write_routes_against_real_mongo(scratch_database, monkeypatch):
    # Confirms the write routes run against a real MongoDB, including the
    # server-side aggregation pipeline that merges a second MIS fill.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote",
        lambda symbol: {"ltp": 1600.0, "dayChangePct": 0.0},
    )
    # Square-off takes the stored-ltp branch, so this test stays offline.
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)

    user_id = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)
    scratch_database["funds"].insert_one(
        {"_id": ObjectId(), "user": user_id, "available": 100000,
         "createdAt": created, "updatedAt": created, "__v": 0}
    )

    token = jwt.encode({"id": str(user_id)}, "test-secret-not-a-real-key", algorithm="HS256")
    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        cookie = {"token": token}

        deposit = client.post("/api/funds/transactions",
                              json={"kind": "DEPOSIT", "amount": 5000}, cookies=cookie)

        market_order = {"symbol": "INFY", "name": "Infosys", "exchange": "NSE", "side": "BUY",
                        "type": "MARKET", "product": "MIS", "qty": 10, "price": 0}
        first_fill = client.post("/api/orders", json=market_order, cookies=cookie)
        second_fill = client.post("/api/orders", json=market_order, cookies=cookie)

        position = scratch_database["positions"].find_one({"user": user_id})
        squared = client.post(f"/api/positions/{position['_id']}/square-off", cookies=cookie)

        limit = client.post("/api/orders",
                            json={"symbol": "TCS", "name": "TCS", "exchange": "NSE", "side": "BUY",
                                  "type": "LIMIT", "product": "CNC", "qty": 1, "price": 100},
                            cookies=cookie)
        cancelled = client.delete(f"/api/orders/{limit.json()['_id']}", cookies=cookie)

    assert deposit.status_code == 201
    assert deposit.json()["funds"]["available"] == 105000

    assert first_fill.status_code == 201 and first_fill.json()["status"] == "EXECUTED"
    assert second_fill.status_code == 201
    # Both fills merged into a single position, which square-off then removed.
    assert squared.status_code == 200
    assert squared.json() == {"message": "Squared off INFY", "pnl": 0}
    assert scratch_database["positions"].count_documents({"user": user_id}) == 0

    # 100000 + 5000 - 16000 - 16000 + (1600*20) - 100 + 100 = 105000
    assert scratch_database["funds"].find_one({"user": user_id})["available"] == 105000
    assert cancelled.status_code == 200
    assert scratch_database["orders"].find_one({"_id": ObjectId(limit.json()["_id"])})["status"] == "CANCELLED"


def test_scheduled_jobs_against_real_mongo(scratch_database, monkeypatch):
    # Confirms the per-minute fill path and the daily upsert outside mongomock:
    # a real $inc, a real delete, and a real findOneAndUpdate upsert.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")
    monkeypatch.setattr("api.jobs.price_sync.is_market_open", lambda: True)
    monkeypatch.setattr(
        "api.jobs.price_sync.fetch_quotes",
        lambda tickers: {
            ticker: {
                "regularMarketPrice": 1600.0,
                "regularMarketChangePercent": 0.5,
            }
            for ticker in tickers
        },
    )

    user_id = ObjectId()
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)

    scratch_database["users"].insert_one({"_id": user_id})
    scratch_database["holdings"].insert_one(
        {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "name": "Infosys",
         "exchange": "NSE", "qty": 10, "avgPrice": 1500.0, "ltp": 1500.0,
         "dayChangePct": 0.0, "sector": "", "createdAt": created,
         "updatedAt": created, "__v": 0}
    )
    scratch_database["positions"].insert_one(
        {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "name": "Infosys",
         "exchange": "NSE", "side": "LONG", "product": "MIS", "qty": 5,
         "entry": 1500.0, "ltp": 1500.0, "createdAt": created,
         "updatedAt": created, "__v": 0}
    )
    scratch_database["funds"].insert_one(
        {"_id": ObjectId(), "user": user_id, "available": 1000.0,
         "createdAt": created, "updatedAt": created, "__v": 0}
    )
    scratch_database["orders"].insert_one(
        {"_id": ObjectId(), "user": user_id, "symbol": "INFY", "name": "Infosys",
         "exchange": "NSE", "side": "SELL", "type": "LIMIT", "product": "MIS",
         "qty": 5, "filled": 0, "price": 1600.0, "triggerPrice": 0.0,
         "slTrigger": 0.0, "tpPrice": 0.0, "groupId": "group-1", "isExit": True,
         "status": "OPEN", "createdAt": created, "updatedAt": created, "__v": 0}
    )

    run_sync(scratch_database)

    holding = scratch_database["holdings"].find_one({"user": user_id})
    assert holding["ltp"] == 1600.0
    assert holding["dayChangePct"] == 0.5
    # Sector metadata moved to PostgreSQL instruments in Phase 3B2; this
    # Mongo-only run has no session factory, so the stored sector is untouched.
    assert holding["sector"] == ""

    # The MIS exit settled: position gone, cash and ledger written.
    assert scratch_database["positions"].count_documents({"user": user_id}) == 0
    assert scratch_database["funds"].find_one({"user": user_id})["available"] == 9000.0
    settlement = scratch_database["transactions"].find_one({"user": user_id})
    assert settlement["method"] == "INFY MIS exit"
    assert settlement["amount"] == 500.0

    record_daily_snapshot(scratch_database)

    snapshot = scratch_database["portfoliosnapshots"].find_one({"user": user_id})
    assert snapshot["value"] == 16000.0
    assert snapshot["invested"] == 15000.0
    assert snapshot["misValue"] == 0.0
    assert snapshot["misInvested"] == 0.0
    assert snapshot["__v"] == 0
    assert snapshot["date"].replace(tzinfo=timezone.utc) == snapshot_date()
    # Idempotent per IST day: a second run updates the same row.
    record_daily_snapshot(scratch_database)
    assert scratch_database["portfoliosnapshots"].count_documents({"user": user_id}) == 1


def test_auth_uses_postgres_while_mongo_routes_stay_real(
    scratch_database, postgres_session_factory, monkeypatch
):
    # Authentication moved to PostgreSQL in Phase 3B1; the remaining routes
    # still read a real MongoDB. This test only needs a real MongoDB for those
    # routes and checks that auth writes nothing into the `users` collection.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    suffix = str(ObjectId())
    email = f"deepak-{suffix}@example.com"
    username = f"deepak{suffix}"

    app = create_app(database=scratch_database)

    def override_get_session():
        with postgres_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"username": username, "email": email, "password": "hunter2hunter2"},
        )
        user_id = signup.json()["user"]["id"]

        scratch_database["holdings"].insert_one(
            {
                "_id": ObjectId(),
                "user": ObjectId(user_id),
                "symbol": "INFY",
                "name": "Infosys",
                "exchange": "NSE",
                "qty": 1,
                "avgPrice": 100.0,
                "ltp": 110.0,
                "dayChangePct": 0.0,
                "sector": "IT",
                "createdAt": datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc),
                "updatedAt": datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc),
                "__v": 0,
            }
        )
        along_with_signup_cookie = client.get("/api/holdings")
        login = client.post(
            "/api/auth/login",
            json={"email": email, "password": "hunter2hunter2"},
        )
        me = client.get("/api/auth/me")

    assert signup.status_code == 201
    assert login.status_code == 200
    assert login.json()["user"] == signup.json()["user"]
    # The cookie a signup sets is already enough for the Mongo-backed route.
    assert along_with_signup_cookie.status_code == 200
    assert [row["symbol"] for row in along_with_signup_cookie.json()] == ["INFY"]

    assert me.status_code == 200
    returned = me.json()["user"]
    assert set(returned) == {"_id", "username", "email", "createdAt", "updatedAt", "__v"}
    assert returned["createdAt"].endswith("Z")

    # Auth must no longer write users to MongoDB.
    assert scratch_database["users"].count_documents({}) == 0

    with postgres_session_factory() as session:
        stored = session.scalar(select(User).where(User.email == email))
    assert stored.password_hash.startswith("$2b$10$")
    assert bcrypt.checkpw(b"hunter2hunter2", stored.password_hash.encode())
