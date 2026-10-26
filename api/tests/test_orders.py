"""PostgreSQL-backed tests for /api/orders: listing, placement validation,
cash blocking, MARKET fills, cancellation/refunds and exit orders.

Every write commits in one database transaction, so these tests also assert the
book side effects of each request rather than only the response body.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
from sqlalchemy import func, select

from api.postgres.models import Fund, Holding, Order, Position, Transaction
from api.tests.conftest import TEST_SECRET

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


def _token(user_id):
    return jwt.encode({"id": user_id}, TEST_SECRET, algorithm="HS256")


def _cookie(user_id):
    return {"token": _token(user_id)}


def _fund(session_factory, user_id):
    with session_factory() as session:
        return session.scalar(select(Fund).where(Fund.user_id == user_id))


def _fresh_quote(ltp):
    return {
        "ltp": ltp,
        "dayChangePct": 0,
        "sourceTime": datetime.now(timezone.utc),
    }


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------


def test_returns_only_the_cookie_users_orders(
    book_client, book_user, book_user_factory, book_order_factory
):
    other = book_user_factory()
    book_order_factory(book_user, symbol="INFY")
    book_order_factory(other, symbol="TCS")

    response = book_client.get("/api/orders", cookies=_cookie(book_user))

    assert response.status_code == 200
    assert [order["symbol"] for order in response.json()] == ["INFY"]


def test_orders_are_newest_first(book_client, book_user, book_order_factory):
    older = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    newer = older + timedelta(days=1)
    book_order_factory(book_user, symbol="OLD", created_at=older)
    book_order_factory(book_user, symbol="NEW", created_at=newer)

    body = book_client.get("/api/orders", cookies=_cookie(book_user)).json()

    assert [order["symbol"] for order in body] == ["NEW", "OLD"]


def test_response_shape_matches_mongoose_serialization(
    book_client, book_user, book_order_factory
):
    order = book_order_factory(book_user)

    body = book_client.get("/api/orders", cookies=_cookie(book_user)).json()

    assert len(body) == 1
    row = body[0]
    assert set(row) == ORDER_KEYS
    assert row["_id"] == order.id
    assert row["user"] == book_user
    assert type(row["_id"]) is str and len(row["_id"]) == 24
    assert row["createdAt"] == "2026-09-01T04:15:30.123Z"
    assert row["isExit"] is False
    assert row["__v"] == 0


def test_empty_orders_returns_empty_list(book_client, book_user):
    response = book_client.get("/api/orders", cookies=_cookie(book_user))
    assert response.status_code == 200
    assert response.json() == []


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


def test_limit_buy_places_open_order_and_blocks_cash(
    book_client, book_user, book_session_factory, book_funds_factory
):
    book_funds_factory(book_user, available=100000)

    response = book_client.post(
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
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    order = response.json()
    assert set(order) == ORDER_KEYS
    assert order["status"] == "OPEN"
    assert order["filled"] == 0
    assert order["isExit"] is False
    assert order["price"] == 1500
    assert order["groupId"] == ""
    assert order["user"] == book_user
    # qty * price was blocked, and the order really exists.
    assert _fund(book_session_factory, book_user).available == Decimal("85000.00")
    with book_session_factory() as session:
        assert session.get(Order, order["_id"]).status == "OPEN"


def test_limit_sell_does_not_block_cash(
    book_client, book_user, book_session_factory, book_holding_factory
):
    book_holding_factory(book_user, symbol="INFY", qty=10)

    response = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "SELL",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 5,
            "price": 1500,
        },
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "OPEN"
    # No debit and no funds row were created for a delivery sell.
    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Fund)) == 0


def test_mis_sell_blocks_cash_like_an_entry(
    book_client, book_user, book_session_factory, book_funds_factory
):
    book_funds_factory(book_user, available=10000)

    response = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "SELL",
            "type": "LIMIT",
            "product": "MIS",
            "qty": 5,
            "price": 100,
        },
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "OPEN"
    # MIS shorts are allowed without holdings, and cash was blocked.
    assert _fund(book_session_factory, book_user).available == Decimal("9500.00")


def test_market_order_without_a_provider_returns_503(
    book_client, book_user, book_session_factory, book_funds_factory, monkeypatch
):
    book_funds_factory(book_user, available=100000)
    monkeypatch.setattr("api.routes.orders.fetch_quote", lambda symbol: None)

    response = book_client.post(
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
        cookies=_cookie(book_user),
    )

    assert response.status_code == 503
    assert response.json() == {
        "message": "No live price available for INFY, try again in a moment"
    }
    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 0
    # The quote check runs before the cash block.
    assert _fund(book_session_factory, book_user).available == Decimal("100000.00")


def test_market_order_with_a_stale_provider_time_returns_503(
    book_client, book_user, book_funds_factory, monkeypatch
):
    book_funds_factory(book_user, available=100000)
    stale = datetime.now(timezone.utc) - timedelta(minutes=11)
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote",
        lambda symbol: {"ltp": 1600.0, "dayChangePct": 0, "sourceTime": stale},
    )

    response = book_client.post(
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
        cookies=_cookie(book_user),
    )

    assert response.status_code == 503
    assert "No live price available" in response.json()["message"]


def test_market_order_with_a_quote_fills_and_merges_holdings(
    book_client,
    book_user,
    book_session_factory,
    book_funds_factory,
    monkeypatch,
):
    book_funds_factory(book_user, available=100000)
    prices = {"INFY": 1600.0}
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote",
        lambda symbol: _fresh_quote(prices[symbol]),
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

    first = book_client.post("/api/orders", json=payload, cookies=_cookie(book_user))
    assert first.status_code == 201
    assert first.json()["status"] == "EXECUTED"
    assert first.json()["filled"] == 10
    assert first.json()["price"] == 1600

    # A second fill merges into the same holding at a weighted average.
    prices["INFY"] = 1700.0
    second = book_client.post("/api/orders", json=payload, cookies=_cookie(book_user))
    assert second.status_code == 201

    with book_session_factory() as session:
        holding = session.scalar(
            select(Holding).where(
                Holding.user_id == book_user, Holding.symbol == "INFY"
            )
        )
        assert holding.qty == 20
        assert holding.avg_price == Decimal("1650.000000")
    assert _fund(book_session_factory, book_user).available == Decimal("67000.00")


def test_market_sell_fills_the_holding_and_records_the_pnl(
    book_client,
    book_user,
    book_session_factory,
    book_holding_factory,
    monkeypatch,
):
    book_holding_factory(
        book_user, symbol="INFY", qty=5, avg_price=Decimal("1400")
    )
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote", lambda symbol: _fresh_quote(1500.0)
    )

    response = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "SELL",
            "type": "MARKET",
            "product": "CNC",
            "qty": 5,
            "price": 0,
        },
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "EXECUTED"
    with book_session_factory() as session:
        assert (
            session.scalar(
                select(Holding).where(Holding.user_id == book_user)
            )
            is None
        )
        settlement = session.scalar(
            select(Transaction).where(Transaction.user_id == book_user)
        )
    assert settlement.kind == "SETTLEMENT"
    assert settlement.method == "INFY sell"
    assert settlement.amount == Decimal("500.00")
    # Proceeds were credited even though the row did not exist beforehand.
    assert _fund(book_session_factory, book_user).available == Decimal("7500.00")


def test_market_buy_bracket_spawns_exits_after_the_fill(
    book_client, book_user, book_session_factory, book_funds_factory, monkeypatch
):
    book_funds_factory(book_user, available=100000)
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote", lambda symbol: _fresh_quote(100.0)
    )

    response = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "MARKET",
            "product": "CNC",
            "qty": 5,
            "price": 0,
            "slTrigger": 90,
            "tpPrice": 110,
        },
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    entry = response.json()
    assert entry["status"] == "EXECUTED"
    with book_session_factory() as session:
        exits = session.scalars(
            select(Order).where(Order.user_id == book_user, Order.is_exit.is_(True))
        ).all()
    assert [leg.type for leg in exits] == ["SL-M", "LIMIT"]
    assert [leg.price for leg in exits] == [
        Decimal("90.0000"),
        Decimal("110.0000"),
    ]
    assert all(
        leg.side == "SELL"
        and leg.group_id == entry["_id"]
        and leg.status == "OPEN"
        for leg in exits
    )


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_order_validation_errors(book_client, book_user, book_funds_factory):
    book_funds_factory(book_user, available=100000)
    base = {
        "symbol": "INFY",
        "name": "Infosys",
        "side": "BUY",
        "type": "LIMIT",
        "product": "CNC",
        "qty": 1,
        "price": 100,
    }
    cookie = _cookie(book_user)

    cases = [
        ({**base, "side": None}, "symbol, name, side and type are required"),
        ({**base, "name": None}, "symbol, name, side and type are required"),
        ({**base, "side": "HOLD"}, "side must be BUY or SELL"),
        ({**base, "type": "STOP"}, "type must be LIMIT, MARKET, SL or SL-M"),
        ({**base, "product": "DELIVERY"}, "product must be CNC or MIS"),
        ({**base, "qty": 0}, "Quantity must be greater than zero"),
        ({**base, "qty": "abc"}, "Quantity must be greater than zero"),
        ({**base, "qty": 1.5}, "Quantity must be a whole number"),
        ({**base, "qty": "1e400"}, "Quantity must be a whole number"),
        ({**base, "price": 0}, "Price must be greater than zero"),
        (
            {**base, "type": "SL", "triggerPrice": 0},
            "SL and SL-M orders need a trigger price",
        ),
        ({**base, "exchange": "BSE"}, "Unsupported exchange"),
    ]
    for payload, message in cases:
        response = book_client.post("/api/orders", json=payload, cookies=cookie)
        assert response.status_code == 400, payload
        assert response.json() == {"message": message}, payload

    bracket = book_client.post(
        "/api/orders",
        json={**base, "slTrigger": 200, "tpPrice": 100},
        cookies=cookie,
    )
    assert bracket.status_code == 400
    assert bracket.json() == {
        "message": "Stop-loss trigger must be below the target price for a buy"
    }


def test_insufficient_funds_and_holdings_messages(
    book_client, book_user, book_funds_factory
):
    book_funds_factory(book_user, available=1000)
    cookie = _cookie(book_user)

    broke = book_client.post(
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

    sell = book_client.post(
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


def test_a_user_without_a_funds_row_cannot_buy(book_client, book_user):
    response = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 1,
            "price": 100,
        },
        cookies=_cookie(book_user),
    )

    assert response.status_code == 400
    assert response.json() == {
        "message": "Insufficient funds: order needs ₹100 but only ₹0 is available"
    }


def test_string_numbers_are_coerced(
    book_client, book_user, book_session_factory, book_funds_factory
):
    book_funds_factory(book_user, available=100000)

    response = book_client.post(
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
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    assert response.json()["qty"] == 5
    assert response.json()["price"] == 1500
    assert _fund(book_session_factory, book_user).available == Decimal("92500.00")


def test_bracket_entry_anchors_its_group(
    book_client, book_user, book_funds_factory
):
    book_funds_factory(book_user, available=100000)

    response = book_client.post(
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
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    order = response.json()
    assert order["slTrigger"] == 90
    assert order["tpPrice"] == 110
    # The pending bracket uses its own _id as the group the exits will share.
    assert order["groupId"] == order["_id"]


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------


def test_cancel_order_refunds_and_reports_state(
    book_client,
    book_user,
    book_user_factory,
    book_session_factory,
    book_funds_factory,
    book_order_factory,
):
    book_funds_factory(book_user, available=100000)
    cookie = _cookie(book_user)

    placed = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "LIMIT",
            "product": "CNC",
            "qty": 10,
            "price": 1500,
        },
        cookies=cookie,
    )
    assert placed.status_code == 201
    order_id = placed.json()["_id"]
    assert _fund(book_session_factory, book_user).available == Decimal("85000.00")

    response = book_client.delete(f"/api/orders/{order_id}", cookies=cookie)
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert _fund(book_session_factory, book_user).available == Decimal("100000.00")

    again = book_client.delete(f"/api/orders/{order_id}", cookies=cookie)
    assert again.status_code == 400
    assert again.json() == {"message": "Order is already cancelled"}

    missing = book_client.delete(
        "/api/orders/64b7f1c2a1b2c3d4e5f60718", cookies=cookie
    )
    assert missing.status_code == 404
    assert missing.json() == {"message": "Order not found"}

    # Another user's open order is not cancellable and is left untouched.
    other = book_user_factory()
    foreign = book_order_factory(other, status="OPEN")
    foreign_response = book_client.delete(f"/api/orders/{foreign.id}", cookies=cookie)
    assert foreign_response.status_code == 404
    with book_session_factory() as session:
        assert session.get(Order, foreign.id).status == "OPEN"


def test_cancel_refunds_only_the_unfilled_quantity(
    book_client, book_user, book_session_factory, book_funds_factory, book_order_factory
):
    book_funds_factory(book_user, available=0)
    order = book_order_factory(
        book_user, side="BUY", product="CNC", qty=10, filled=4, price=100
    )

    response = book_client.delete(
        f"/api/orders/{order.id}", cookies=_cookie(book_user)
    )

    assert response.status_code == 200
    assert _fund(book_session_factory, book_user).available == Decimal("600.00")


def test_a_filled_order_cannot_be_cancelled_or_refunded(
    book_client,
    book_user,
    book_session_factory,
    book_funds_factory,
    monkeypatch,
):
    book_funds_factory(book_user, available=100000)
    monkeypatch.setattr(
        "api.routes.orders.fetch_quote", lambda symbol: _fresh_quote(100.0)
    )
    cookie = _cookie(book_user)

    placed = book_client.post(
        "/api/orders",
        json={
            "symbol": "INFY",
            "name": "Infosys",
            "side": "BUY",
            "type": "MARKET",
            "product": "CNC",
            "qty": 1,
            "price": 0,
        },
        cookies=cookie,
    )
    assert placed.status_code == 201
    assert _fund(book_session_factory, book_user).available == Decimal("99900.00")

    response = book_client.delete(f"/api/orders/{placed.json()['_id']}", cookies=cookie)

    assert response.status_code == 400
    assert response.json() == {"message": "Order is already executed"}
    # The cancellation guard matched no OPEN row, so nothing was refunded.
    assert _fund(book_session_factory, book_user).available == Decimal("99900.00")


# --------------------------------------------------------------------------
# Exit orders
# --------------------------------------------------------------------------


def test_set_exits_creates_then_replaces_the_pair(
    book_client, book_user, book_session_factory, book_holding_factory
):
    book_holding_factory(book_user, symbol="INFY", name="Infosys", qty=10)
    cookie = _cookie(book_user)

    first = book_client.post(
        "/api/orders/exits",
        json={
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "CNC",
            "slTrigger": 90,
            "tpPrice": 110,
        },
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

    second = book_client.post(
        "/api/orders/exits",
        json={
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "CNC",
            "slTrigger": 95,
            "tpPrice": 105,
        },
        cookies=cookie,
    )
    assert second.status_code == 201
    with book_session_factory() as session:
        cancelled = session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.user_id == book_user,
                Order.is_exit.is_(True),
                Order.status == "CANCELLED",
            )
        )
    assert cancelled == 2

    missing = book_client.post(
        "/api/orders/exits",
        json={"symbol": "TCS", "exchange": "NSE", "product": "CNC", "slTrigger": 90},
        cookies=cookie,
    )
    assert missing.status_code == 404
    assert missing.json() == {"message": "No holding found for TCS"}


def test_set_exits_from_a_long_mis_position(
    book_client, book_user, book_position_factory
):
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=7, entry=1500
    )

    response = book_client.post(
        "/api/orders/exits",
        json={"symbol": "INFY", "product": "MIS", "slTrigger": 1400},
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    orders = response.json()["orders"]
    assert len(orders) == 1
    assert orders[0]["side"] == "SELL"
    assert orders[0]["qty"] == 7
    assert orders[0]["type"] == "SL-M"
    assert orders[0]["price"] == 1400
    assert position.qty == 7


def test_set_exits_from_a_short_mis_position_uses_a_buy(
    book_client, book_user, book_position_factory
):
    book_position_factory(book_user, symbol="INFY", side="SHORT", qty=4, entry=1500)

    response = book_client.post(
        "/api/orders/exits",
        json={"symbol": "INFY", "product": "MIS", "slTrigger": 1600},
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    order = response.json()["orders"][0]
    assert order["side"] == "BUY"
    assert order["product"] == "MIS"
    assert order["qty"] == 4


def test_set_exits_validation_and_ordering_rules(
    book_client, book_user, book_holding_factory, book_position_factory
):
    book_holding_factory(book_user, symbol="INFY", qty=10)
    book_position_factory(book_user, symbol="INFY", side="SHORT", qty=5)
    cookie = _cookie(book_user)

    cases = [
        (
            {"product": "CNC", "slTrigger": 90},
            "symbol and product are required",
        ),
        (
            {"symbol": "INFY", "product": "DELIVERY", "slTrigger": 90},
            "product must be CNC or MIS",
        ),
        (
            {"symbol": "INFY", "product": "CNC"},
            "Set at least a stop-loss trigger or a target price",
        ),
        (
            {"symbol": "INFY", "product": "CNC", "slTrigger": 110, "tpPrice": 90},
            "Stop-loss trigger must be below the target price",
        ),
        (
            {"symbol": "INFY", "product": "MIS", "slTrigger": 1500, "tpPrice": 1600},
            "Stop-loss trigger must be above the target price for a short",
        ),
        (
            {"symbol": "INFY", "exchange": "BSE", "product": "CNC", "slTrigger": 90},
            "Unsupported exchange",
        ),
    ]
    for payload, message in cases:
        response = book_client.post("/api/orders/exits", json=payload, cookies=cookie)
        assert response.status_code == 400, payload
        assert response.json() == {"message": message}, payload

    no_position = book_client.post(
        "/api/orders/exits",
        json={"symbol": "TCS", "product": "MIS", "slTrigger": 90},
        cookies=cookie,
    )
    assert no_position.status_code == 404
    assert no_position.json() == {"message": "No open MIS position found for TCS"}
