"""PostgreSQL-backed tests for the holdings response and user isolation."""

import jwt

from api.tests.conftest import TEST_SECRET


def test_returns_only_the_cookie_users_holdings(
    book_client, book_user, book_user_factory, book_holding_factory
):
    from datetime import datetime, timedelta, timezone

    early = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    late = early + timedelta(minutes=5)
    other = book_user_factory()
    book_holding_factory(book_user, symbol="RELIANCE", created_at=early)
    book_holding_factory(book_user, symbol="INFY", name="Infosys", created_at=late)
    book_holding_factory(other, symbol="TCS", name="Tata Consultancy")

    response = book_client.get("/api/holdings", cookies={"token": _token(book_user)})

    assert response.status_code == 200
    symbols = [holding["symbol"] for holding in response.json()]
    assert symbols == ["RELIANCE", "INFY"]


def test_user_id_from_query_or_body_is_ignored(
    book_client, book_user, book_user_factory, book_holding_factory
):
    other = book_user_factory()
    book_holding_factory(book_user, symbol="RELIANCE")
    book_holding_factory(other, symbol="TCS")

    response = book_client.get(
        f"/api/holdings?user={other}&userId={other}",
        cookies={"token": _token(book_user)},
    )

    assert response.status_code == 200
    assert [h["symbol"] for h in response.json()] == ["RELIANCE"]


def test_response_shape_and_joined_quote(
    book_client,
    book_user,
    book_holding_factory,
    market_instrument_factory,
):
    holding = book_holding_factory(book_user, symbol="RELIANCE", avg_price="2400.5")
    market_instrument_factory(
        symbol="RELIANCE",
        name="Reliance Industries",
        sector="Energy",
        ltp=2500.0,
        day_change_pct=1.25,
    )

    body = book_client.get(
        "/api/holdings", cookies={"token": _token(book_user)}
    ).json()

    assert len(body) == 1
    row = body[0]
    assert set(row) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "qty",
        "avgPrice",
        "ltp",
        "dayChangePct",
        "sector",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert row["_id"] == holding.id
    assert row["user"] == book_user
    assert row["qty"] == 10
    assert row["avgPrice"] == 2400.5
    assert row["ltp"] == 2500
    assert row["dayChangePct"] == 1.25
    assert row["sector"] == "Energy"
    assert row["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert row["updatedAt"] == "2026-09-01T04:15:30.123Z"
    assert row["__v"] == 0
    assert type(row["_id"]) is str and len(row["_id"]) == 24


def test_missing_quote_and_instrument_fall_back_to_zero(
    book_client, book_user, book_holding_factory
):
    book_holding_factory(book_user, symbol="RELIANCE")

    row = book_client.get(
        "/api/holdings", cookies={"token": _token(book_user)}
    ).json()[0]

    assert row["ltp"] == 0
    assert row["dayChangePct"] == 0
    assert row["sector"] == ""


def test_empty_holdings_returns_empty_list(book_client, book_user):
    response = book_client.get("/api/holdings", cookies={"token": _token(book_user)})
    assert response.status_code == 200
    assert response.json() == []


def test_timestamps_are_utc_with_milliseconds(
    book_client, book_user, book_holding_factory
):
    from datetime import datetime, timezone

    moment = datetime(2026, 1, 2, 3, 4, 5, 6000, tzinfo=timezone.utc)
    book_holding_factory(book_user, created_at=moment)

    holding = book_client.get(
        "/api/holdings", cookies={"token": _token(book_user)}
    ).json()[0]
    assert holding["createdAt"] == "2026-01-02T03:04:05.006Z"


def test_malformed_user_id_in_token_matches_no_rows(book_client):
    # The PostgreSQL ids are text: a malformed token id is not a cast error,
    # it simply owns no rows. This replaces the old Mongoose CastError -> 500.
    token = jwt.encode({"id": "not-an-object-id"}, TEST_SECRET, algorithm="HS256")
    response = book_client.get("/api/holdings", cookies={"token": token})
    assert response.status_code == 200
    assert response.json() == []


def _token(user_id):
    return jwt.encode({"id": user_id}, TEST_SECRET, algorithm="HS256")
