"""Focused tests for GET /api/orders: content, ordering, isolation, shape.

Authentication and database-failure behaviour go through the same
`require_user` dependency and error handlers already covered by the
holdings suite, so they are not repeated here.
"""

from datetime import datetime, timezone

from bson import ObjectId


def test_returns_only_the_cookie_users_orders(
    client, database, make_token, user_id, other_user_id, orders_factory
):
    database["orders"].insert_many(
        [
            orders_factory(user_id, symbol="INFY"),
            orders_factory(other_user_id, symbol="TCS"),
        ]
    )

    response = client.get("/api/orders", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    assert [order["symbol"] for order in response.json()] == ["INFY"]


def test_orders_are_newest_first(client, database, make_token, user_id, orders_factory):
    older = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 9, 2, 4, 0, 0, tzinfo=timezone.utc)
    database["orders"].insert_many(
        [
            orders_factory(user_id, symbol="OLD", createdAt=older, updatedAt=older),
            orders_factory(user_id, symbol="NEW", createdAt=newer, updatedAt=newer),
        ]
    )

    response = client.get("/api/orders", cookies={"token": make_token(user_id)})

    assert [order["symbol"] for order in response.json()] == ["NEW", "OLD"]


def test_response_shape_matches_mongoose_serialization(
    client, database, make_token, user_id, orders_factory
):
    order_id = ObjectId()
    database["orders"].insert_one(orders_factory(user_id, _id=order_id))

    body = client.get("/api/orders", cookies={"token": make_token(user_id)}).json()

    assert len(body) == 1
    order = body[0]
    assert set(order) == {
        "_id",
        "user",
        "symbol",
        "name",
        "exchange",
        "side",
        "type",
        "product",
        "qty",
        "filled",
        "price",
        "triggerPrice",
        "slTrigger",
        "tpPrice",
        "groupId",
        "isExit",
        "status",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert order["_id"] == str(order_id)
    assert order["user"] == str(user_id)
    assert type(order["_id"]) is str and len(order["_id"]) == 24
    assert order["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert order["isExit"] is False
    assert order["__v"] == 0


def test_empty_orders_returns_empty_list(client, make_token, user_id):
    response = client.get("/api/orders", cookies={"token": make_token(user_id)})
    assert response.status_code == 200
    assert response.json() == []
