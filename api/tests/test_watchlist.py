"""Focused tests for GET /api/watchlist: content, isolation, shape.

The route returns natural order with no sort, so ordering is not asserted.
Authentication and database-failure behaviour are shared with the holdings
suite and not repeated here.
"""

from bson import ObjectId


def test_returns_only_the_cookie_users_watchlist(
    client, database, make_token, user_id, other_user_id, watchlist_factory
):
    database["watchlists"].insert_many(
        [
            watchlist_factory(user_id, symbol="INFY"),
            watchlist_factory(user_id, symbol="RELIANCE", name="Reliance Industries"),
            watchlist_factory(other_user_id, symbol="TCS", name="Tata Consultancy"),
        ]
    )

    response = client.get("/api/watchlist", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    symbols = [item["symbol"] for item in response.json()]
    assert symbols == ["INFY", "RELIANCE"]
    assert "TCS" not in symbols


def test_response_shape_matches_mongoose_serialization(
    client, database, make_token, user_id, watchlist_factory
):
    item_id = ObjectId()
    database["watchlists"].insert_one(watchlist_factory(user_id, _id=item_id))

    body = client.get("/api/watchlist", cookies={"token": make_token(user_id)}).json()

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
    assert item["_id"] == str(item_id)
    assert item["user"] == str(user_id)
    assert type(item["_id"]) is str and len(item["_id"]) == 24
    assert item["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert item["__v"] == 0


def test_empty_watchlist_returns_empty_list(client, make_token, user_id):
    response = client.get("/api/watchlist", cookies={"token": make_token(user_id)})
    assert response.status_code == 200
    assert response.json() == []
