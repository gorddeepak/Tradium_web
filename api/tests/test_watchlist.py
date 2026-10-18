"""Focused tests for /api/watchlist: reads (content, isolation, shape) and the
add/delete mutations (validation, duplicate guard, always-204 delete).

The read route returns natural order with no sort, so ordering is not
asserted. Authentication and database-failure behaviour are shared with the
holdings suite and not repeated here.
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


def test_add_watchlist_creates_item_and_rejects_duplicates(
    client, database, make_token, user_id
):
    cookie = {"token": make_token(user_id)}

    response = client.post(
        "/api/watchlist",
        json={"symbol": "INFY", "name": "Infosys", "exchange": "NSE"},
        cookies=cookie,
    )

    assert response.status_code == 201
    item = response.json()
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
    assert item["symbol"] == "INFY"
    assert item["user"] == str(user_id)
    assert item["ltp"] == 0
    assert database["watchlists"].count_documents({"user": user_id}) == 1

    duplicate = client.post(
        "/api/watchlist", json={"symbol": "INFY", "name": "Other"}, cookies=cookie
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"message": "Already in watchlist"}


def test_add_watchlist_validates_symbol(client, database, make_token, user_id):
    cookie = {"token": make_token(user_id)}

    assert (
        client.post(
            "/api/watchlist", json={"symbol": "bad symbol!"}, cookies=cookie
        ).status_code
        == 400
    )
    assert client.post("/api/watchlist", json={}, cookies=cookie).json() == {
        "message": "Invalid symbol"
    }

    # A leading ^ is allowed for index tickers, and exchange defaults to NSE.
    index = client.post(
        "/api/watchlist", json={"symbol": "^NSEI", "name": "NIFTY 50"}, cookies=cookie
    )
    assert index.status_code == 201
    assert index.json()["exchange"] == "NSE"


def test_delete_watchlist_is_always_204(
    client, database, make_token, user_id, other_user_id, watchlist_factory
):
    cookie = {"token": make_token(user_id)}
    mine = ObjectId()
    theirs = ObjectId()
    database["watchlists"].insert_many(
        [
            watchlist_factory(user_id, _id=mine, symbol="INFY"),
            watchlist_factory(other_user_id, _id=theirs, symbol="TCS"),
        ]
    )

    first = client.delete(f"/api/watchlist/{mine}", cookies=cookie)
    assert first.status_code == 204
    assert first.content == b""
    assert database["watchlists"].count_documents({"_id": mine}) == 0

    # Deleting again still 204, and another user's row is untouched.
    assert client.delete(f"/api/watchlist/{mine}", cookies=cookie).status_code == 204
    assert client.delete(f"/api/watchlist/{theirs}", cookies=cookie).status_code == 204
    assert database["watchlists"].count_documents({"_id": theirs}) == 1
