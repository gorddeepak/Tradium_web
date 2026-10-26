"""PostgreSQL-backed tests for GET /api/market/overview.

Phase 3B2 moved the persisted market cache from MongoDB's ``marketquotes`` to
PostgreSQL. These run only when TEST_DATABASE_URL points at a disposable
PostgreSQL database; there is no SQLite fallback. Authentication behaviour is
shared with the holdings suite and not repeated.
"""

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.postgres.session import get_session

EARLIER = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 2, 4, 0, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").strip(),
    reason="TEST_DATABASE_URL is not set; PostgreSQL market tests skipped",
)


@pytest.fixture
def client(postgres_session_factory):
    app = create_app()

    def override_get_session():
        with postgres_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_indices_follow_seed_order_and_stocks_are_split_out(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(symbol="^BSESN", name="SENSEX", kind="index")
    market_instrument_factory(symbol="^NSEI", name="NIFTY 50", kind="index")
    market_instrument_factory(symbol="^NSEBANK", name="BANK NIFTY", kind="index")
    market_instrument_factory(symbol="INFY", name="Infosys", kind="stock")
    # A book-only instrument must not leak into the visible market universe.
    market_instrument_factory(
        symbol="TCS", name="Tata Consultancy Services", in_market_universe=False
    )

    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert [row["symbol"] for row in body["indices"]] == ["^NSEI", "^NSEBANK", "^BSESN"]
    assert [row["symbol"] for row in body["stocks"]] == ["INFY"]


def test_cold_cache_returns_nulls_and_empty_lists(client, make_token, user_id):
    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert body == {"asOf": None, "indices": [], "stocks": []}


def test_as_of_is_the_freshest_quote_and_rows_keep_the_legacy_keys(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(
        symbol="INFY", name="Infosys", updated_at=EARLIER, ltp=1500.0
    )
    market_instrument_factory(symbol="TCS", name="TCS", updated_at=LATER, ltp=3200.0)

    body = client.get("/api/market/overview", cookies={"token": make_token(user_id)}).json()

    assert body["asOf"] == "2026-09-02T04:00:00.000Z"
    row = body["stocks"][0]
    assert set(row) == {
        "_id",
        "symbol",
        "name",
        "kind",
        "ltp",
        "dayChange",
        "dayChangePct",
        "prevClose",
        "volume",
        "marketCap",
        "sector",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert row["symbol"] == "INFY"
    assert row["ltp"] == 1500
    assert row["dayChange"] == 12
    assert row["dayChangePct"] == 0.8
    assert row["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert row["updatedAt"] == "2026-09-01T04:00:00.000Z"


def test_sector_backfill_does_not_move_as_of(
    client, make_token, user_id, market_instrument_factory, postgres_session_factory
):
    import api.market_store as market_store

    market_instrument_factory(
        symbol="INFY", name="Infosys", sector="", updated_at=EARLIER
    )
    initial = client.get(
        "/api/market/overview", cookies={"token": make_token(user_id)}
    ).json()

    market_store.backfill_sectors(
        postgres_session_factory, lambda symbol: "Technology"
    )
    after = client.get(
        "/api/market/overview", cookies={"token": make_token(user_id)}
    ).json()

    assert initial["stocks"][0]["sector"] == ""
    assert after["stocks"][0]["sector"] == "Technology"
    assert after["asOf"] == initial["asOf"] == "2026-09-01T04:00:00.000Z"
