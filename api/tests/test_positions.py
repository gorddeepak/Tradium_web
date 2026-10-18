"""Focused tests for GET /api/positions: isolation and shape.

The route returns natural order with no sort, so ordering is not asserted.
Authentication and database-failure behaviour are shared with the holdings
suite and not repeated here.
"""

from bson import ObjectId


def test_returns_only_the_cookie_users_positions(
    client, database, make_token, user_id, other_user_id, positions_factory
):
    database["positions"].insert_many(
        [
            positions_factory(user_id, symbol="INFY"),
            positions_factory(user_id, symbol="RELIANCE", name="Reliance Industries", side="SHORT"),
            positions_factory(other_user_id, symbol="TCS", name="Tata Consultancy"),
        ]
    )

    response = client.get("/api/positions", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    symbols = [position["symbol"] for position in response.json()]
    assert symbols == ["INFY", "RELIANCE"]
    assert "TCS" not in symbols


def test_response_shape_matches_mongoose_serialization(
    client, database, make_token, user_id, positions_factory
):
    position_id = ObjectId()
    database["positions"].insert_one(positions_factory(user_id, _id=position_id))

    body = client.get("/api/positions", cookies={"token": make_token(user_id)}).json()

    assert len(body) == 1
    position = body[0]
    assert set(position) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "side",
        "product",
        "qty",
        "entry",
        "ltp",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert position["_id"] == str(position_id)
    assert position["user"] == str(user_id)
    assert type(position["_id"]) is str and len(position["_id"]) == 24
    assert position["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_empty_positions_returns_empty_list(client, make_token, user_id):
    response = client.get("/api/positions", cookies={"token": make_token(user_id)})
    assert response.status_code == 200
    assert response.json() == []
