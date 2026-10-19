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

from api.main import create_app
from api.jobs.market_sync import backfill_sectors, sync_quotes

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
        added = client.post("/api/watchlist",
                            json={"symbol": "INFY", "name": "Infosys"}, cookies=cookie)
        removed = client.delete(f"/api/watchlist/{added.json()['_id']}", cookies=cookie)

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
    assert added.status_code == 201 and removed.status_code == 204
    assert scratch_database["watchlists"].count_documents({"user": user_id}) == 0

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


def test_market_sync_against_real_mongo(scratch_database, monkeypatch):
    # mongomock cannot run a bulk update with this pymongo version, so the
    # actual cache write is exercised here. The provider is still patched: no
    # test contacts Yahoo.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    quote_rows = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "regularMarketPrice": 1202.8,
            "regularMarketChange": -8.4,
            "regularMarketChangePercent": -0.69,
            "regularMarketPreviousClose": 1211.2,
            "regularMarketVolume": 15138916,
            "marketCap": 16276858601472,
        },
        "^NSEI": {
            "symbol": "^NSEI",
            "regularMarketPrice": 22888.95,
            "regularMarketChange": -257.2,
            "regularMarketChangePercent": -1.11,
            "regularMarketPreviousClose": 23146.15,
            "regularMarketVolume": 0,
            "marketCap": None,  # indices have no market cap
        },
    }
    monkeypatch.setattr("api.jobs.market_sync.fetch_quotes", lambda tickers: quote_rows)
    monkeypatch.setattr("api.jobs.market_sync.fetch_sector", lambda symbol: "Energy")

    sync_quotes(scratch_database)

    reliance = scratch_database["marketquotes"].find_one({"symbol": "RELIANCE"})
    nifty = scratch_database["marketquotes"].find_one({"symbol": "^NSEI"})

    # Nine quote fields plus the Mongoose insert fields.
    assert reliance["ltp"] == 1202.8
    assert reliance["dayChange"] == -8.4
    assert reliance["dayChangePct"] == -0.69
    assert reliance["prevClose"] == 1211.2
    assert reliance["volume"] == 15138916
    assert reliance["marketCap"] == 16276858601472
    assert reliance["name"] == "Reliance Industries"
    assert reliance["kind"] == "stock"
    assert reliance["sector"] == ""  # the backfill owns it
    assert reliance["__v"] == 0
    assert reliance["createdAt"] == reliance["updatedAt"]

    # `?? 0` turns an absent market cap into 0 for an index.
    assert nifty["kind"] == "index"
    assert nifty["marketCap"] == 0
    assert nifty["name"] == "NIFTY 50"

    # A second run updates the price without touching createdAt or the sector.
    backfill_sectors(scratch_database)
    assert scratch_database["marketquotes"].find_one({"symbol": "RELIANCE"})["sector"] == "Energy"

    quote_rows["RELIANCE.NS"]["regularMarketPrice"] = 1210.0
    sync_quotes(scratch_database)

    refreshed = scratch_database["marketquotes"].find_one({"symbol": "RELIANCE"})
    assert refreshed["ltp"] == 1210.0
    assert refreshed["sector"] == "Energy"  # preserved by $setOnInsert
    assert refreshed["createdAt"] == reliance["createdAt"]
    assert refreshed["updatedAt"] > reliance["updatedAt"]

    # One row per symbol, not one per run.
    assert scratch_database["marketquotes"].count_documents({}) == 2


def test_auth_routes_against_real_mongo(scratch_database, monkeypatch):
    # Confirms the `users` collection resolves against a real MongoDB, and that
    # signup -> cookie -> login -> protected route works end to end outside
    # mongomock, including a stored bcrypt hash written by this app.
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-a-real-key")

    app = create_app(database=scratch_database)

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"username": "deepak", "email": "deepak@example.com", "password": "hunter2hunter2"},
        )
        along_with_signup_cookie = client.get("/api/holdings")
        login = client.post(
            "/api/auth/login",
            json={"email": "deepak@example.com", "password": "hunter2hunter2"},
        )
        me = client.get("/api/auth/me")

    assert signup.status_code == 201
    assert login.status_code == 200
    assert login.json()["user"] == signup.json()["user"]
    # The cookie a signup sets is already enough for the protected routes.
    assert along_with_signup_cookie.status_code == 200

    assert me.status_code == 200
    returned = me.json()["user"]
    assert set(returned) == {"_id", "username", "email", "createdAt", "updatedAt", "__v"}
    assert returned["createdAt"].endswith("Z")

    stored = scratch_database["users"].find_one({"email": "deepak@example.com"})
    assert stored["password"].startswith("$2b$10$")
    assert bcrypt.checkpw(b"hunter2hunter2", stored["password"].encode())


