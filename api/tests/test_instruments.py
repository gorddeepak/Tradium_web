"""PostgreSQL-backed tests for GET /api/instruments/search.

The search route reads the persisted market universe, which moved from
MongoDB to PostgreSQL in Phase 3B2. These run only when TEST_DATABASE_URL is
set. Authentication behaviour is shared with the holdings suite.
"""

import os

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.postgres.session import get_session

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").strip(),
    reason="TEST_DATABASE_URL is not set; PostgreSQL search tests skipped",
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


def _search(client, make_token, user_id, query):
    return client.get(
        "/api/instruments/search",
        params={"q": query},
        cookies={"token": make_token(user_id)},
    ).json()


def test_matches_symbol_or_name_case_insensitively(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(symbol="INFY", name="Infosys")
    market_instrument_factory(symbol="RELIANCE", name="Reliance Industries")
    market_instrument_factory(symbol="TCS", name="Tata Consultancy Services")

    body = _search(client, make_token, user_id, "inf")

    assert [row["symbol"] for row in body] == ["INFY"]


def test_renames_fields_for_the_client(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(
        symbol="INFY",
        name="Infosys",
        kind="stock",
        ltp=1500.0,
        day_change_pct=0.8,
    )

    body = _search(client, make_token, user_id, "INFY")

    assert body == [
        {"symbol": "INFY", "name": "Infosys", "kind": "stock", "price": 1500, "changePct": 0.8}
    ]


def test_empty_query_returns_empty_list(client, make_token, user_id):
    token_cookie = {"token": make_token(user_id)}

    assert client.get("/api/instruments/search", cookies=token_cookie).json() == []
    assert client.get("/api/instruments/search", params={"q": "   "}, cookies=token_cookie).json() == []


def test_relevance_order_then_symbol(
    client, make_token, user_id, market_instrument_factory
):
    # Exact symbol, symbol prefix, name prefix, then a name substring.
    market_instrument_factory(symbol="INF", name="Exact Symbol")
    market_instrument_factory(symbol="INFY", name="Infosys")
    market_instrument_factory(symbol="ITC", name="Infosys IT")
    market_instrument_factory(symbol="TCS", name="Tata Infotech")

    body = _search(client, make_token, user_id, "INF")

    assert [row["symbol"] for row in body] == ["INF", "INFY", "ITC", "TCS"]


def test_no_match_returns_empty_list(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(symbol="INFY", name="Infosys")

    assert _search(client, make_token, user_id, "ZZZ") == []


def test_book_only_instruments_are_excluded(
    client, make_token, user_id, market_instrument_factory
):
    market_instrument_factory(symbol="INFY", name="Infosys")
    market_instrument_factory(
        symbol="PRIVATE", name="Private Holding", in_market_universe=False
    )

    body = _search(client, make_token, user_id, "private")

    assert body == []


def test_limits_to_ten_and_treats_like_characters_literally(
    client, make_token, user_id, market_instrument_factory
):
    for index in range(12):
        market_instrument_factory(symbol=f"TCK{index}", name="Tick")
    market_instrument_factory(symbol="ITC", name="ITC")

    capped = _search(client, make_token, user_id, "Tick")
    assert len(capped) == 10

    # A dot is literal, not a wildcard; the same is true for % and _.
    assert _search(client, make_token, user_id, "I.C") == []
    assert _search(client, make_token, user_id, "T%ck") == []
    assert _search(client, make_token, user_id, "T_ck") == []


def test_search_is_not_shadowed_by_the_symbol_route(
    client, make_token, user_id, market_instrument_factory
):
    """`/search` must still reach the search route, not `/:symbol`."""
    market_instrument_factory(symbol="INFY", name="Infosys")

    body = _search(client, make_token, user_id, "INFY")

    assert [row["symbol"] for row in body] == ["INFY"]
