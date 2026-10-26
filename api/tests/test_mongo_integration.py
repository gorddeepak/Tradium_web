"""Optional integration tests against real PostgreSQL and MongoDB.

Skipped unless TEST_MONGO_URL is set. Example:

    TEST_MONGO_URL=mongodb://127.0.0.1:27017/tradium_fastapi_phase1_test \
    TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/tradium_phase3c2_test \
        python -m pytest api/tests/test_mongo_integration.py

The MongoDB database name must end with "_test" so this can never touch the
live database. It is dropped afterwards.

Phase 3C2 moved the trading book (holdings, positions, orders, funds,
transactions) to PostgreSQL, and Phase 3C2B moved the last readers —
``/api/portfolio/history``'s live point, the daily snapshot and Nova's
trading-book tools — with it. No FastAPI route or job reads a MongoDB
trading-book collection any more; the scratch MongoDB is still created so the
real-database run proves the retired collections are left untouched.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import bcrypt
import jwt
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from sqlalchemy import select

from api.jobs.portfolio_snapshot import record_daily_snapshot, snapshot_date
from api.jobs.price_sync import run_sync
from api.main import create_app
from api.postgres.models import (
    Fund,
    Holding,
    Order,
    PortfolioSnapshot,
    Position,
    Transaction,
    User,
)
from api.postgres.session import get_session
from api.tests.conftest import TEST_SECRET

TEST_MONGO_URL = os.getenv("TEST_MONGO_URL")
NOW = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not TEST_MONGO_URL, reason="set TEST_MONGO_URL to run the real-database tests"
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


def _token(user_id):
    return jwt.encode({"id": str(user_id)}, TEST_SECRET, algorithm="HS256")


def _cookie(user_id):
    return {"token": _token(user_id)}


# --------------------------------------------------------------------------
# Book reads against real PostgreSQL
# --------------------------------------------------------------------------


def test_holdings_read_real_postgres_rows(
    book_client, book_user, book_holding_factory, market_instrument_factory
):
    book_holding_factory(book_user, symbol="RELIANCE", name="Reliance Industries")
    book_holding_factory(
        book_user,
        symbol="TCS",
        name="Tata Consultancy",
        created_at=datetime(2026, 9, 2, 4, 15, 30, 123000, tzinfo=timezone.utc),
    )
    market_instrument_factory(
        symbol="RELIANCE",
        name="Reliance Industries",
        sector="Energy",
        ltp=2500.0,
        day_change_pct=1.25,
    )

    response = book_client.get("/api/holdings", cookies=_cookie(book_user))

    assert response.status_code == 200
    body = response.json()
    assert [holding["symbol"] for holding in body] == ["RELIANCE", "TCS"]
    holding = body[0]
    assert holding["user"] == book_user
    assert type(holding["_id"]) is str and len(holding["_id"]) == 24
    assert holding["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert holding["ltp"] == 2500
    assert holding["dayChangePct"] == 1.25
    assert holding["sector"] == "Energy"
    assert holding["__v"] == 0


def test_orders_read_real_postgres_rows(
    book_client, book_user, book_user_factory, book_order_factory
):
    other = book_user_factory()
    book_order_factory(book_user, symbol="INFY")
    book_order_factory(other, symbol="TCS")

    response = book_client.get("/api/orders", cookies=_cookie(book_user))

    assert response.status_code == 200
    body = response.json()
    assert [order["symbol"] for order in body] == ["INFY"]
    assert body[0]["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_positions_and_funds_read_real_postgres_rows(
    book_client,
    book_user,
    book_position_factory,
    book_funds_factory,
    book_transaction_factory,
):
    book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=5, entry=Decimal("1500")
    )
    book_funds_factory(book_user, available=50000)
    book_transaction_factory(
        book_user, kind="SETTLEMENT", amount=Decimal("-250.5")
    )

    positions = book_client.get("/api/positions", cookies=_cookie(book_user))
    funds = book_client.get("/api/funds", cookies=_cookie(book_user))

    assert positions.status_code == 200
    assert [position["symbol"] for position in positions.json()] == ["INFY"]
    assert positions.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert funds.status_code == 200
    body = funds.json()
    assert body["available"] == 50000
    assert body["misMargin"] == 7500  # 1500 * 5
    assert body["usedMargin"] == 7500  # no open orders
    assert body["realizedPnl"] == -250.5


def test_transactions_and_portfolio_history_read_postgres(
    book_client, book_user, book_transaction_factory, book_session_factory
):
    created = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)
    book_transaction_factory(book_user, kind="DEPOSIT", amount=Decimal("5000"))
    with book_session_factory() as session:
        session.add(
            PortfolioSnapshot(
                id=secrets.token_hex(12),
                user_id=book_user,
                snapshot_date=datetime(2026, 9, 1, tzinfo=timezone.utc).date(),
                value=Decimal("200"),
                invested=Decimal("180"),
                mis_value=Decimal("0"),
                mis_invested=Decimal("0"),
                created_at=created,
                updated_at=created,
                version=0,
            )
        )
        session.commit()

    transactions = book_client.get(
        "/api/funds/transactions", cookies=_cookie(book_user)
    )
    history = book_client.get(
        "/api/portfolio/history", params={"range": "ALL"}, cookies=_cookie(book_user)
    )

    assert transactions.status_code == 200
    assert [row["kind"] for row in transactions.json()] == ["DEPOSIT"]
    assert transactions.json()[0]["createdAt"] == "2026-09-01T04:15:30.123Z"

    assert history.status_code == 200
    labels = [point["label"] for point in history.json()]
    assert "2026-09-01" in labels


# --------------------------------------------------------------------------
# Book writes against real PostgreSQL
# --------------------------------------------------------------------------


def _fresh_quote(ltp):
    return {
        "ltp": ltp,
        "dayChangePct": 0.0,
        "sourceTime": datetime.now(timezone.utc),
    }


def test_write_routes_against_real_postgres(
    book_client, book_user, book_session_factory, book_funds_factory, monkeypatch
):
    book_funds_factory(book_user, available=100000)
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote", lambda symbol: _fresh_quote(1600.0)
    )
    monkeypatch.setattr(
        "api.routes.positions.fetch_quote", lambda symbol: _fresh_quote(1600.0)
    )
    cookie = _cookie(book_user)

    deposit = book_client.post(
        "/api/funds/transactions",
        json={"kind": "DEPOSIT", "amount": 5000},
        cookies=cookie,
    )

    market_order = {
        "symbol": "INFY",
        "name": "Infosys",
        "exchange": "NSE",
        "side": "BUY",
        "type": "MARKET",
        "product": "MIS",
        "qty": 10,
        "price": 0,
    }
    first_fill = book_client.post("/api/orders", json=market_order, cookies=cookie)
    second_fill = book_client.post("/api/orders", json=market_order, cookies=cookie)

    with book_session_factory() as session:
        position = session.scalar(select(Position).where(Position.user_id == book_user))
    squared = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies=cookie
    )

    limit = book_client.post(
        "/api/orders",
        json={
            "symbol": "TCS",
            "name": "TCS",
            "exchange": "NSE",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 1,
            "price": 100,
        },
        cookies=cookie,
    )
    cancelled = book_client.delete(
        f"/api/orders/{limit.json()['_id']}", cookies=cookie
    )

    assert deposit.status_code == 201
    assert deposit.json()["funds"]["available"] == 105000

    assert first_fill.status_code == 201
    assert first_fill.json()["status"] == "EXECUTED"
    assert second_fill.status_code == 201
    # Both fills merged into a single position, which square-off then removed.
    assert squared.status_code == 200
    assert squared.json() == {"message": "Squared off INFY", "pnl": 0}
    with book_session_factory() as session:
        assert (
            session.scalar(select(Position).where(Position.user_id == book_user))
            is None
        )

    # 100000 + 5000 - 16000 - 16000 + (1600*20) - 100 + 100 = 105000
    with book_session_factory() as session:
        assert (
            session.scalar(select(Fund.available).where(Fund.user_id == book_user))
            == Decimal("105000.00")
        )
    assert cancelled.status_code == 200
    with book_session_factory() as session:
        assert session.get(Order, limit.json()["_id"]).status == "CANCELLED"


def test_scheduled_fill_and_snapshot_against_real_databases(
    scratch_database,
    book_session_factory,
    book_user,
    book_holding_factory,
    book_position_factory,
    book_funds_factory,
    book_order_factory,
    monkeypatch,
):
    # The per-minute fill path and the daily snapshot both run entirely in
    # PostgreSQL now; only the provider call is stubbed.
    monkeypatch.setattr(
        "api.jobs.price_sync.fetch_quotes",
        lambda tickers: {
            ticker: {
                "regularMarketPrice": 1600.0,
                "regularMarketChangePercent": 0.5,
                "regularMarketTime": NOW.timestamp(),
            }
            for ticker in tickers
        },
    )
    monkeypatch.setattr("api.jobs.price_sync.fetch_sector", lambda symbol: "")

    book_holding_factory(
        book_user, symbol="INFY", qty=10, avg_price=Decimal("1500")
    )
    book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=5, entry=Decimal("1500")
    )
    book_funds_factory(book_user, available=1000)
    book_order_factory(
        book_user,
        symbol="INFY",
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=5,
        price=1600,
        is_exit=True,
        group_id="group-1",
    )

    run_sync(book_session_factory, now=NOW)

    # The MIS exit settled: position gone, cash and ledger written.
    with book_session_factory() as session:
        from api.postgres.models import Position

        assert (
            session.scalar(select(Position).where(Position.user_id == book_user))
            is None
        )
        settlement = session.scalar(
            select(Transaction).where(Transaction.user_id == book_user)
        )
    with book_session_factory() as session:
        assert (
            session.scalar(select(Fund.available).where(Fund.user_id == book_user))
            == Decimal("9000.00")
        )
    assert settlement.method == "INFY MIS exit"
    assert settlement.amount == Decimal("500.00")

    record_daily_snapshot(book_session_factory)

    with book_session_factory() as session:
        snapshot = session.scalar(
            select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == book_user)
        )
    assert snapshot.value == Decimal("16000")
    assert snapshot.invested == Decimal("15000")
    assert snapshot.mis_value == Decimal("0")
    assert snapshot.mis_invested == Decimal("0")
    assert snapshot.version == 0
    assert snapshot.snapshot_date == snapshot_date().date()
    # Idempotent per IST day: a second run updates the same row.
    record_daily_snapshot(book_session_factory)
    with book_session_factory() as session:
        rows = session.scalars(
            select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == book_user)
        ).all()
    assert len(rows) == 1


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


def test_auth_uses_postgres_while_mongo_stays_real(
    scratch_database, book_session_factory, monkeypatch
):
    # Authentication is canonical in PostgreSQL; the retired Mongo collections
    # stay untouched, and auth must never write a MongoDB `users` document.
    suffix = str(ObjectId())
    email = f"deepak-{suffix}@example.com"
    username = f"deepak{suffix}"

    app = create_app()

    def override_get_session():
        with book_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"username": username, "email": email, "password": "hunter2hunter2"},
        )
        user_id = signup.json()["user"]["id"]

        with book_session_factory() as session:
            created = datetime(2026, 9, 1, 4, 15, 30, tzinfo=timezone.utc)
            session.add(
                Holding(
                    id=secrets.token_hex(12),
                    user_id=user_id,
                    symbol="INFY",
                    name="Infosys",
                    exchange="NSE",
                    qty=1,
                    avg_price=Decimal("100"),
                    created_at=created,
                    updated_at=created,
                    version=0,
                )
            )
            session.commit()

        along_with_signup_cookie = client.get("/api/holdings")
        login = client.post(
            "/api/auth/login",
            json={"email": email, "password": "hunter2hunter2"},
        )
        me = client.get("/api/auth/me")

    assert signup.status_code == 201
    assert login.status_code == 200
    assert login.json()["user"] == signup.json()["user"]
    # The cookie a signup sets is already enough for the holdings route.
    assert along_with_signup_cookie.status_code == 200
    assert [row["symbol"] for row in along_with_signup_cookie.json()] == ["INFY"]

    assert me.status_code == 200
    returned = me.json()["user"]
    assert set(returned) == {"_id", "username", "email", "createdAt", "updatedAt", "__v"}
    assert returned["createdAt"].endswith("Z")

    # Auth must not write users to MongoDB.
    assert scratch_database["users"].count_documents({}) == 0

    with book_session_factory() as session:
        stored = session.scalar(select(User).where(User.email == email))
    assert stored.password_hash.startswith("$2b$10$")
    assert bcrypt.checkpw(b"hunter2hunter2", stored.password_hash.encode())
