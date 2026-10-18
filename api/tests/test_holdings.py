"""Tests for the holdings response content and user isolation."""

from bson import ObjectId


def test_returns_only_the_cookie_users_holdings(
    client, database, make_token, user_id, other_user_id, holdings_factory
):
    database["holdings"].insert_many(
        [
            holdings_factory(user_id, symbol="RELIANCE"),
            holdings_factory(user_id, symbol="INFY", name="Infosys"),
            holdings_factory(other_user_id, symbol="TCS", name="Tata Consultancy"),
        ]
    )

    response = client.get("/api/holdings", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    symbols = [holding["symbol"] for holding in response.json()]
    assert symbols == ["RELIANCE", "INFY"]
    assert "TCS" not in symbols


def test_user_id_from_query_or_body_is_ignored(
    client, database, make_token, user_id, other_user_id, holdings_factory
):
    database["holdings"].insert_many(
        [
            holdings_factory(user_id, symbol="RELIANCE"),
            holdings_factory(other_user_id, symbol="TCS"),
        ]
    )

    # Try to impersonate: the token decides, never the caller.
    response = client.get(
        f"/api/holdings?user={other_user_id}&userId={other_user_id}",
        cookies={"token": make_token(user_id)},
    )

    assert response.status_code == 200
    assert [h["symbol"] for h in response.json()] == ["RELIANCE"]


def test_response_shape_matches_mongoose_serialization(
    client, database, make_token, user_id, holdings_factory
):
    holding_id = ObjectId()
    document = holdings_factory(user_id, _id=holding_id)
    database["holdings"].insert_one(document)

    body = client.get("/api/holdings", cookies={"token": make_token(user_id)}).json()

    assert len(body) == 1
    holding = body[0]
    assert set(holding) == {
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
    assert holding["_id"] == str(holding_id)
    assert holding["user"] == str(user_id)
    assert holding["qty"] == 10
    assert holding["avgPrice"] == 2400.5
    assert holding["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert holding["updatedAt"] == "2026-09-01T04:15:30.123Z"
    assert holding["__v"] == 0
    # No ObjectId wrapper, no "ObjectId('...')" text.
    assert type(holding["_id"]) is str and len(holding["_id"]) == 24


def test_empty_holdings_returns_empty_list(client, make_token, user_id):
    response = client.get("/api/holdings", cookies={"token": make_token(user_id)})
    assert response.status_code == 200
    assert response.json() == []


def test_timestamps_are_utc_with_milliseconds(client, database, make_token, user_id, holdings_factory):
    from datetime import datetime, timezone

    moment = datetime(2026, 1, 2, 3, 4, 5, 6000, tzinfo=timezone.utc)
    database["holdings"].insert_one(
        holdings_factory(user_id, createdAt=moment, updatedAt=moment)
    )

    holding = client.get("/api/holdings", cookies={"token": make_token(user_id)}).json()[0]
    assert holding["createdAt"] == "2026-01-02T03:04:05.006Z"


def test_malformed_user_id_in_token_returns_server_error(client):
    from api.tests.conftest import TEST_SECRET
    import jwt

    # Express casts the token id in the query; an invalid cast reaches the
    # central handler and returns 500.
    token = jwt.encode({"id": "not-an-object-id"}, TEST_SECRET, algorithm="HS256")
    response = client.get("/api/holdings", cookies={"token": token})
    assert response.status_code == 500
    assert response.json() == {"message": "Something went wrong"}
