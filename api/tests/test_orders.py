"""Focused tests for GET /api/orders plus the order writes: placement
(validation, cash block, MARKET fills), cancellation/refund, and exits.

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


ORDER_KEYS = {
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


def test_limit_buy_places_open_order_and_blocks_cash(
    client, database, make_token, user_id, funds_factory
):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))

    response = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "exchange": "NSE",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 10,
            "price": 1500,
        },
        cookies=cookie,
    )

    assert response.status_code == 201
    order = response.json()
    assert set(order) == ORDER_KEYS
    assert order["status"] == "OPEN"
    assert order["filled"] == 0
    assert order["isExit"] is False
    assert order["price"] == 1500
    assert order["groupId"] == ""
    assert order["user"] == str(user_id)
    # qty * price was blocked
    assert database["funds"].find_one({"user": user_id})["available"] == 85000


def test_market_order_without_a_provider_returns_503(
    client, database, make_token, user_id, funds_factory, monkeypatch
):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))
    # No quote available: the documented "provider returned no price" branch.
    monkeypatch.setattr("api.routes.orders.fetch_quote", lambda symbol: None)

    response = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "MARKET",
            "product": "CNC",
            "qty": 5,
            "price": 0,
        },
        cookies=cookie,
    )

    assert response.status_code == 503
    assert response.json() == {
        "message": "No live price available for INFY, try again in a moment"
    }
    assert database["orders"].count_documents({"user": user_id}) == 0
    # The quote check runs before the cash block.
    assert database["funds"].find_one({"user": user_id})["available"] == 100000


def test_market_order_with_a_quote_fills_and_merges_holdings(
    client, database, make_token, user_id, funds_factory, monkeypatch
):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))
    prices = {"INFY": 1600.0}
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote",
        lambda symbol: {"ltp": prices[symbol], "dayChangePct": 0},
    )
    payload = {
        "symbol": "INFY",
        "name": "Infosys",
        "exchange": "NSE",
        "side": "BUY",
        "type": "MARKET",
        "product": "CNC",
        "qty": 10,
        "price": 0,
    }

    first = client.post("/api/orders", json=payload, cookies=cookie)
    assert first.status_code == 201
    assert first.json()["status"] == "EXECUTED"
    assert first.json()["filled"] == 10
    assert first.json()["price"] == 1600

    # A second fill merges into the same holding through the atomic pipeline.
    prices["INFY"] = 1700.0
    second = client.post("/api/orders", json=payload, cookies=cookie)
    assert second.status_code == 201

    holding = database["holdings"].find_one({"user": user_id, "symbol": "INFY"})
    assert holding["qty"] == 20
    assert holding["avgPrice"] == 1650.0
    assert database["funds"].find_one({"user": user_id})["available"] == 67000


def test_order_validation_errors(client, database, make_token, user_id, funds_factory):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))
    base = {
        "symbol": "INFY",
        "name": "Infosys",
        "side": "BUY",
        "type": "LIMIT",
        "product": "CNC",
        "qty": 1,
        "price": 100,
    }

    cases = [
        ({**base, "side": None}, "symbol, name, side and type are required"),
        ({**base, "side": "HOLD"}, "side must be BUY or SELL"),
        ({**base, "type": "STOP"}, "type must be LIMIT, MARKET, SL or SL-M"),
        ({**base, "product": "DELIVERY"}, "product must be CNC or MIS"),
        ({**base, "qty": 0}, "Quantity must be greater than zero"),
        ({**base, "qty": "abc"}, "Quantity must be greater than zero"),
        ({**base, "qty": 1.5}, "Quantity must be a whole number"),
        ({**base, "qty": "1e400"}, "Quantity must be a whole number"),
        ({**base, "price": 0}, "Price must be greater than zero"),
        ({**base, "type": "SL", "triggerPrice": 0}, "SL and SL-M orders need a trigger price"),
    ]
    for payload, message in cases:
        response = client.post("/api/orders", json=payload, cookies=cookie)
        assert response.status_code == 400, payload
        assert response.json() == {"message": message}, payload

    bracket = client.post(
        "/api/orders", json={**base, "slTrigger": 200, "tpPrice": 100}, cookies=cookie
    )
    assert bracket.status_code == 400
    assert bracket.json() == {
        "message": "Stop-loss trigger must be below the target price for a buy"
    }


def test_insufficient_funds_and_holdings_messages(
    client, database, make_token, user_id, funds_factory
):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=1000))

    broke = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 5,
            "price": 1500,
        },
        cookies=cookie,
    )
    assert broke.status_code == 400
    assert broke.json() == {
        "message": "Insufficient funds: order needs ₹7,500 but only ₹1,000 is available"
    }

    sell = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "SELL",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 10,
            "price": 1500,
        },
        cookies=cookie,
    )
    assert sell.status_code == 400
    assert sell.json() == {
        "message": "Insufficient holdings: you hold 0 INFY but tried to sell 10"
    }


def test_cancel_order_refunds_and_reports_state(
    client, database, make_token, user_id, other_user_id, funds_factory, orders_factory
):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))
    order_id = ObjectId()
    database["orders"].insert_one(
        orders_factory(
            user_id,
            _id=order_id,
            side="BUY",
            product="CNC",
            status="OPEN",
            qty=10,
            filled=0,
            price=1500,
            isExit=False,
        )
    )

    response = client.delete(f"/api/orders/{order_id}", cookies=cookie)
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert database["funds"].find_one({"user": user_id})["available"] == 115000

    again = client.delete(f"/api/orders/{order_id}", cookies=cookie)
    assert again.status_code == 400
    assert again.json() == {"message": "Order is already cancelled"}

    missing = client.delete(f"/api/orders/{ObjectId()}", cookies=cookie)
    assert missing.status_code == 404
    assert missing.json() == {"message": "Order not found"}

    # Another user's open order is not cancellable and is left untouched.
    foreign_id = ObjectId()
    database["orders"].insert_one(orders_factory(other_user_id, _id=foreign_id, status="OPEN"))
    foreign = client.delete(f"/api/orders/{foreign_id}", cookies=cookie)
    assert foreign.status_code == 404
    assert database["orders"].find_one({"_id": foreign_id})["status"] == "OPEN"


def test_string_numbers_are_coerced(client, database, make_token, user_id, funds_factory):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))

    response = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": "5",
            "price": "1500",
        },
        cookies=cookie,
    )

    assert response.status_code == 201
    assert response.json()["qty"] == 5
    assert response.json()["price"] == 1500
    assert database["funds"].find_one({"user": user_id})["available"] == 92500


def test_bracket_entry_anchors_its_group(client, database, make_token, user_id, funds_factory):
    cookie = {"token": make_token(user_id)}
    database["funds"].insert_one(funds_factory(user_id, available=100000))

    response = client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 1,
            "price": 100,
            "slTrigger": 90,
            "tpPrice": 110,
        },
        cookies=cookie,
    )

    assert response.status_code == 201
    order = response.json()
    assert order["slTrigger"] == 90
    assert order["tpPrice"] == 110
    # The pending bracket uses its own _id as the group the exits will share.
    assert order["groupId"] == order["_id"]


def test_set_exits_creates_then_replaces_the_pair(
    client, database, make_token, user_id, holdings_factory
):
    cookie = {"token": make_token(user_id)}
    database["holdings"].insert_one(
        holdings_factory(user_id, symbol="INFY", name="Infosys", qty=10)
    )

    first = client.post(
        "/api/orders/exits",
        json={"symbol": "INFY", "exchange": "NSE", "product": "CNC", "slTrigger": 90, "tpPrice": 110},
        cookies=cookie,
    )
    assert first.status_code == 201
    body = first.json()
    assert body["message"] == "Exit rules set for INFY"
    assert [order["type"] for order in body["orders"]] == ["SL-M", "LIMIT"]
    assert [order["price"] for order in body["orders"]] == [90, 110]
    assert all(
        order["isExit"] is True and order["side"] == "SELL" and order["qty"] == 10
        for order in body["orders"]
    )
    assert len({order["groupId"] for order in body["orders"]}) == 1

    second = client.post(
        "/api/orders/exits",
        json={"symbol": "INFY", "exchange": "NSE", "product": "CNC", "slTrigger": 95, "tpPrice": 105},
        cookies=cookie,
    )
    assert second.status_code == 201
    # The first pair was cancelled when the new pair replaced it.
    assert (
        database["orders"].count_documents(
            {"user": user_id, "isExit": True, "status": "CANCELLED"}
        )
        == 2
    )

    missing = client.post(
        "/api/orders/exits",
        json={"symbol": "TCS", "exchange": "NSE", "product": "CNC", "slTrigger": 90},
        cookies=cookie,
    )
    assert missing.status_code == 404
    assert missing.json() == {"message": "No holding found for TCS"}
