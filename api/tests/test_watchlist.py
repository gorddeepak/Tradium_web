"""PostgreSQL-backed tests for /api/watchlist.

Phase 3B3 moved the watchlist collection to PostgreSQL, so these replace the
previous mongomock assertions. They run only when TEST_DATABASE_URL points at
a disposable PostgreSQL database whose name ends in "_test"; there is no
SQLite fallback. The read joins `instruments` / `latest_quotes`, so the tests
seed those rows explicitly.

The rest of the API still reads MongoDB, so the client fixture pairs the real
PostgreSQL session with an in-memory mongomock database.
"""

import os
import secrets
from datetime import datetime, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from api.main import create_app
from api.postgres.models import User, Watchlist
from api.postgres.session import get_session
from api.routes import watchlist as watchlist_routes

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").strip()

NOW = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 2, 4, 15, 30, 456000, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; PostgreSQL watchlist tests skipped",
)


@pytest.fixture
def session_factory(postgres_session_factory):
    """Reuse the shared PostgreSQL session factory from conftest."""
    return postgres_session_factory


@pytest.fixture(autouse=True)
def empty_users(postgres_schema):
    """Give every test fresh users, and cascade away their watchlist rows."""
    with postgres_schema.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users CASCADE"))
    yield


@pytest.fixture
def client(postgres_session_factory):
    """The API with PostgreSQL sessions and mongomock for the remaining routes."""
    app = create_app(database=mongomock.MongoClient()["tradium_test"])

    def override_get_session():
        with postgres_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def insert_user(session_factory, username="deepak", email="deepak@example.com"):
    """Insert a user row the way the signup route stores one."""
    user = User(
        id=secrets.token_hex(12),
        username=username,
        email=email,
        password_hash="not-used-in-watchlist-tests",
        created_at=NOW,
        updated_at=NOW,
        version=0,
    )
    with session_factory() as session:
        session.add(user)
        session.commit()
    return user


def insert_watchlist(
    session_factory,
    user_id,
    symbol="INFY",
    name="Infosys",
    watchlist_id=None,
    created_at=NOW,
):
    """Insert a watchlist row directly, bypassing the route."""
    item = Watchlist(
        id=watchlist_id or secrets.token_hex(12),
        user_id=user_id,
        symbol=symbol,
        name=name,
        exchange="NSE",
        created_at=created_at,
        updated_at=created_at,
        version=0,
    )
    with session_factory() as session:
        session.add(item)
        session.commit()
    return item.id


def count_watchlist(session_factory, user_id):
    with session_factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(Watchlist)
            .where(Watchlist.user_id == user_id)
        )


def test_returns_only_the_users_watchlist_in_deterministic_order(
    client, session_factory, make_token, market_instrument_factory
):
    user = insert_user(session_factory)
    other = insert_user(session_factory, username="other", email="other@example.com")

    market_instrument_factory(symbol="INFY", ltp=1500.0, day_change_pct=0.75)
    market_instrument_factory(symbol="RELIANCE", ltp=2400.5, day_change_pct=-1.25)

    insert_watchlist(
        session_factory,
        user.id,
        symbol="RELIANCE",
        name="Reliance Industries",
        created_at=LATER,
    )
    insert_watchlist(session_factory, user.id, symbol="INFY", created_at=NOW)
    insert_watchlist(session_factory, other.id, symbol="TCS", name="Tata Consultancy")

    response = client.get(
        "/api/watchlist", cookies={"token": make_token(user.id)}
    )

    assert response.status_code == 200
    items = response.json()
    assert [item["symbol"] for item in items] == ["INFY", "RELIANCE"]
    assert [item["ltp"] for item in items] == [1500, 2400.5]
    assert [item["dayChangePct"] for item in items] == [0.75, -1.25]
    assert all(item["user"] == user.id for item in items)


def test_response_shape_matches_mongoose_serialization(
    client, session_factory, make_token
):
    user = insert_user(session_factory)
    item_id = "0123456789abcdef01234567"
    insert_watchlist(session_factory, user.id, watchlist_id=item_id)

    body = client.get(
        "/api/watchlist", cookies={"token": make_token(user.id)}
    ).json()

    assert len(body) == 1
    item = body[0]
    assert set(item) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "ltp",
        "dayChangePct",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert item["_id"] == item_id
    assert item["user"] == user.id
    assert item["symbol"] == "INFY"
    assert item["name"] == "Infosys"
    assert item["exchange"] == "NSE"
    assert item["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert item["updatedAt"] == "2026-09-01T04:15:30.123Z"
    assert item["__v"] == 0


def test_empty_watchlist_returns_empty_list(client, session_factory, make_token):
    user = insert_user(session_factory)

    response = client.get(
        "/api/watchlist", cookies={"token": make_token(user.id)}
    )

    assert response.status_code == 200
    assert response.json() == []


def test_missing_quote_or_instrument_falls_back_to_zero(
    client, session_factory, make_token, market_instrument_factory
):
    user = insert_user(session_factory)
    # INFY has an instrument but no quote; TCS has no instrument at all.
    market_instrument_factory(symbol="INFY", quote=False)
    insert_watchlist(session_factory, user.id, symbol="INFY", created_at=NOW)
    insert_watchlist(session_factory, user.id, symbol="TCS", created_at=LATER)

    body = client.get(
        "/api/watchlist", cookies={"token": make_token(user.id)}
    ).json()

    assert [(item["symbol"], item["ltp"], item["dayChangePct"]) for item in body] == [
        ("INFY", 0, 0),
        ("TCS", 0, 0),
    ]


def test_add_read_and_delete_round_trip(
    client, session_factory, make_token, market_instrument_factory
):
    user = insert_user(session_factory)
    cookie = {"token": make_token(user.id)}

    created = client.post(
        "/api/watchlist",
        json={"symbol": "INFY", "name": "Infosys", "exchange": "NSE"},
        cookies=cookie,
    )

    assert created.status_code == 201
    item = created.json()
    assert set(item) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "ltp",
        "dayChangePct",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert item["user"] == user.id
    assert item["symbol"] == "INFY"
    assert item["name"] == "Infosys"
    assert item["exchange"] == "NSE"
    # A new row starts at zero until the quote cache knows the symbol.
    assert item["ltp"] == 0
    assert item["dayChangePct"] == 0
    assert item["__v"] == 0
    assert item["createdAt"].endswith("Z")
    assert count_watchlist(session_factory, user.id) == 1

    market_instrument_factory(symbol="INFY", ltp=1500.25, day_change_pct=0.5)

    listed = client.get("/api/watchlist", cookies=cookie).json()
    assert len(listed) == 1
    assert listed[0]["_id"] == item["_id"]
    assert listed[0]["ltp"] == 1500.25
    assert listed[0]["dayChangePct"] == 0.5

    deleted = client.delete(f"/api/watchlist/{item['_id']}", cookies=cookie)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert count_watchlist(session_factory, user.id) == 0
    assert client.get("/api/watchlist", cookies=cookie).json() == []


def test_duplicate_symbol_is_409_for_one_user_but_allowed_for_another(
    client, session_factory, make_token
):
    user = insert_user(session_factory)
    other = insert_user(session_factory, username="other", email="other@example.com")
    cookie = {"token": make_token(user.id)}

    assert (
        client.post("/api/watchlist", json={"symbol": "INFY"}, cookies=cookie).status_code
        == 201
    )

    duplicate = client.post(
        "/api/watchlist", json={"symbol": "INFY", "name": "Other"}, cookies=cookie
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"message": "Already in watchlist"}
    assert count_watchlist(session_factory, user.id) == 1

    # Uniqueness is per user, not global.
    other_add = client.post(
        "/api/watchlist",
        json={"symbol": "INFY"},
        cookies={"token": make_token(other.id)},
    )
    assert other_add.status_code == 201
    assert count_watchlist(session_factory, user.id) == 1
    assert count_watchlist(session_factory, other.id) == 1


def test_add_validates_the_symbol(client, session_factory, make_token):
    user = insert_user(session_factory)
    cookie = {"token": make_token(user.id)}

    bad = client.post(
        "/api/watchlist", json={"symbol": "bad symbol!"}, cookies=cookie
    )
    assert bad.status_code == 400
    assert bad.json() == {"message": "Invalid symbol"}

    missing = client.post("/api/watchlist", json={}, cookies=cookie)
    assert missing.status_code == 400
    assert missing.json() == {"message": "Invalid symbol"}

    # A leading ^ is allowed for index tickers, and exchange defaults to NSE.
    index = client.post(
        "/api/watchlist", json={"symbol": "^NSEI", "name": "NIFTY 50"}, cookies=cookie
    )
    assert index.status_code == 201
    assert index.json()["exchange"] == "NSE"


def test_add_falls_back_to_the_symbol_when_name_is_missing(
    client, session_factory, make_token
):
    user = insert_user(session_factory)
    cookie = {"token": make_token(user.id)}

    body = client.post(
        "/api/watchlist", json={"symbol": "INFY"}, cookies=cookie
    ).json()

    # The column is NOT NULL, so the route stores the symbol (design F10).
    assert body["name"] == "INFY"

    with session_factory() as session:
        stored = session.scalar(select(Watchlist).where(Watchlist.id == body["_id"]))
    assert stored.name == "INFY"


def test_add_rejects_any_exchange_other_than_nse(
    client, session_factory, make_token
):
    user = insert_user(session_factory)
    cookie = {"token": make_token(user.id)}

    for exchange in ("BSE", "nse", "NSE "):
        response = client.post(
            "/api/watchlist",
            json={"symbol": "INFY", "exchange": exchange},
            cookies=cookie,
        )
        assert response.status_code == 400
        assert response.json() == {"message": "Unsupported exchange"}

    assert count_watchlist(session_factory, user.id) == 0


def test_duplicate_race_maps_the_unique_constraint_to_409(
    client, session_factory, make_token, monkeypatch
):
    user = insert_user(session_factory)
    real_new_watchlist_id = watchlist_routes.new_watchlist_id

    def new_watchlist_id_after_competing_add():
        # This commits on another connection, so the route's own INSERT hits
        # the unique constraint rather than its fast-path SELECT.
        insert_watchlist(session_factory, user.id, symbol="INFY")
        return real_new_watchlist_id()

    monkeypatch.setattr(
        watchlist_routes, "new_watchlist_id", new_watchlist_id_after_competing_add
    )

    response = client.post(
        "/api/watchlist",
        json={"symbol": "INFY"},
        cookies={"token": make_token(user.id)},
    )

    assert response.status_code == 409
    assert response.json() == {"message": "Already in watchlist"}
    assert count_watchlist(session_factory, user.id) == 1


def test_delete_is_always_204_and_never_touches_another_users_row(
    client, session_factory, make_token
):
    user = insert_user(session_factory)
    other = insert_user(session_factory, username="other", email="other@example.com")
    mine = "0123456789abcdef01234567"
    theirs = "fedcba9876543210fedcba98"
    insert_watchlist(session_factory, user.id, watchlist_id=mine)
    insert_watchlist(
        session_factory, other.id, symbol="TCS", watchlist_id=theirs
    )
    cookie = {"token": make_token(user.id)}

    first = client.delete(f"/api/watchlist/{mine}", cookies=cookie)
    assert first.status_code == 204
    assert first.content == b""
    assert count_watchlist(session_factory, user.id) == 0

    # Deleting again still 204.
    assert client.delete(f"/api/watchlist/{mine}", cookies=cookie).status_code == 204

    # A non-owned row is a no-op with the same 204.
    assert client.delete(f"/api/watchlist/{theirs}", cookies=cookie).status_code == 204
    assert count_watchlist(session_factory, other.id) == 1

    # A malformed id matches no row instead of raising (design D13).
    malformed = client.delete("/api/watchlist/not-an-object-id", cookies=cookie)
    assert malformed.status_code == 204
    assert malformed.content == b""


def test_watchlist_routes_require_authentication(client):
    assert client.get("/api/watchlist").status_code == 401
    assert client.post("/api/watchlist", json={"symbol": "INFY"}).status_code == 401
    assert (
        client.delete("/api/watchlist/0123456789abcdef01234567").status_code == 401
    )
