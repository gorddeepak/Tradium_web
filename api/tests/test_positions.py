"""PostgreSQL-backed tests for /api/positions and the MIS square-off."""

from decimal import Decimal

import jwt
from sqlalchemy import select

from api.postgres.models import Fund, Order, Position, Transaction
from api.tests.conftest import TEST_SECRET


def _token(user_id):
    return jwt.encode({"id": user_id}, TEST_SECRET, algorithm="HS256")


def _funds(factory, user_id):
    with factory() as session:
        return session.scalar(select(Fund).where(Fund.user_id == user_id))


def test_returns_only_the_cookie_users_positions(
    book_client, book_user, book_user_factory, book_position_factory
):
    from datetime import datetime, timedelta, timezone

    early = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    late = early + timedelta(minutes=5)
    other = book_user_factory()
    book_position_factory(book_user, symbol="INFY", created_at=early)
    book_position_factory(
        book_user, symbol="RELIANCE", side="SHORT", created_at=late
    )
    book_position_factory(other, symbol="TCS")

    response = book_client.get("/api/positions", cookies={"token": _token(book_user)})

    assert response.status_code == 200
    assert [p["symbol"] for p in response.json()] == ["INFY", "RELIANCE"]


def test_response_shape_and_joined_quote(
    book_client, book_user, book_position_factory, market_instrument_factory
):
    position = book_position_factory(book_user, symbol="INFY", entry="1500.0")
    market_instrument_factory(symbol="INFY", ltp=1520.0)

    body = book_client.get(
        "/api/positions", cookies={"token": _token(book_user)}
    ).json()

    assert len(body) == 1
    row = body[0]
    assert set(row) == {
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
    assert row["_id"] == position.id
    assert row["user"] == book_user
    assert row["entry"] == 1500
    assert row["ltp"] == 1520
    assert row["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_missing_quote_falls_back_to_zero(
    book_client, book_user, book_position_factory
):
    book_position_factory(book_user, symbol="INFY")
    row = book_client.get(
        "/api/positions", cookies={"token": _token(book_user)}
    ).json()[0]
    assert row["ltp"] == 0


def test_empty_positions_returns_empty_list(book_client, book_user):
    response = book_client.get("/api/positions", cookies={"token": _token(book_user)})
    assert response.status_code == 200
    assert response.json() == []


def test_square_off_long_uses_canonical_quote_and_records_settlement(
    book_client,
    book_user,
    book_session_factory,
    book_position_factory,
    book_order_factory,
    market_instrument_factory,
    monkeypatch,
):
    # No live quote: the canonical latest_quotes ltp is the fallback.
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=10, entry="1500.0"
    )
    exit_order = book_order_factory(
        book_user,
        symbol="INFY",
        product="MIS",
        is_exit=True,
        status="OPEN",
        group_id="group-1",
    )
    market_instrument_factory(symbol="INFY", ltp=1550.0)

    response = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies={"token": _token(book_user)}
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Squared off INFY", "pnl": 500}

    with book_session_factory() as session:
        assert session.get(Position, position.id) is None
        assert _funds(book_session_factory, book_user).available == Decimal("15500.00")
        settlement = session.scalar(
            select(Transaction).where(
                Transaction.user_id == book_user,
                Transaction.kind == "SETTLEMENT",
            )
        )
        assert settlement.amount == Decimal("500.00")
        assert settlement.method == "INFY MIS square-off"
        assert settlement.symbol == "INFY"
        closing = session.scalar(
            select(Order).where(
                Order.user_id == book_user, Order.is_exit.is_(False)
            )
        )
        assert closing.side == "SELL"
        assert closing.type == "MARKET"
        assert closing.status == "EXECUTED"
        assert closing.filled == 10
        assert closing.price == Decimal("1550.0000")
        assert session.get(Order, exit_order.id).status == "CANCELLED"


def test_square_off_prefers_the_live_quote(
    book_client,
    book_user,
    book_session_factory,
    book_position_factory,
    market_instrument_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "api.routes.positions.fetch_quote",
        lambda symbol: {"ltp": 1600.0, "dayChangePct": 0, "sourceTime": None},
    )
    position = book_position_factory(
        book_user, symbol="INFY", side="LONG", qty=10, entry="1500.0"
    )
    market_instrument_factory(symbol="INFY", ltp=1550.0)

    response = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies={"token": _token(book_user)}
    )

    assert response.status_code == 200
    assert response.json()["pnl"] == 1000
    assert _funds(book_session_factory, book_user).available == Decimal("16000.00")


def test_square_off_short_pnl_sign(
    book_client,
    book_user,
    book_session_factory,
    book_position_factory,
    market_instrument_factory,
    monkeypatch,
):
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)
    position = book_position_factory(
        book_user, symbol="INFY", side="SHORT", qty=5, entry="200.0"
    )
    market_instrument_factory(symbol="INFY", ltp=190.0)

    response = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies={"token": _token(book_user)}
    )

    assert response.status_code == 200
    assert response.json()["pnl"] == 50
    assert _funds(book_session_factory, book_user).available == Decimal("1050.00")


def test_second_square_off_returns_404(
    book_client, book_user, book_position_factory, market_instrument_factory, monkeypatch
):
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)
    position = book_position_factory(book_user, symbol="INFY")
    market_instrument_factory(symbol="INFY", ltp=1520.0)

    first = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies={"token": _token(book_user)}
    )
    second = book_client.post(
        f"/api/positions/{position.id}/square-off", cookies={"token": _token(book_user)}
    )

    assert first.status_code == 200
    # Intentional change: the race-specific 409 does not exist after the lock;
    # a missing position is the normal 404.
    assert second.status_code == 404
    assert second.json() == {"message": "Position not found"}


def test_square_off_errors(
    book_client,
    book_user,
    book_user_factory,
    book_position_factory,
    market_instrument_factory,
    monkeypatch,
):
    cookie = {"token": _token(book_user)}
    # Keep this test offline; there is no provider quote for any symbol.
    monkeypatch.setattr("api.routes.positions.fetch_quote", lambda symbol: None)

    missing = book_client.post(
        "/api/positions/64b7f1c2a1b2c3d4e5f60718/square-off", cookies=cookie
    )
    assert missing.status_code == 404
    assert missing.json() == {"message": "Position not found"}

    other = book_user_factory()
    foreign = book_position_factory(other, symbol="INFY", product="MIS")
    foreign_response = book_client.post(
        f"/api/positions/{foreign.id}/square-off", cookies=cookie
    )
    assert foreign_response.status_code == 404

    cnc = book_position_factory(book_user, symbol="TCS", product="CNC")
    not_mis = book_client.post(f"/api/positions/{cnc.id}/square-off", cookies=cookie)
    assert not_mis.status_code == 400
    assert not_mis.json() == {
        "message": "Only MIS positions can be squared off here"
    }

    # No provider quote and no canonical quote row: no usable price.
    no_price = book_position_factory(book_user, symbol="WIPRO", product="MIS")
    no_price_response = book_client.post(
        f"/api/positions/{no_price.id}/square-off", cookies=cookie
    )
    assert no_price_response.status_code == 400
    assert no_price_response.json() == {
        "message": "No live price for this position yet — try again shortly"
    }
