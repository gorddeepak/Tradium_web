"""PostgreSQL-backed tests for /api/funds: derived keys, first-read creation,
isolation, the transaction ledger, and deposit/withdrawal writes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
from sqlalchemy import func, select

from api.postgres.models import Fund, Transaction
from api.tests.conftest import TEST_SECRET

CREATED = datetime(2026, 9, 1, 4, 15, 30, 123000, tzinfo=timezone.utc)


def _token(user_id):
    return jwt.encode({"id": user_id}, TEST_SECRET, algorithm="HS256")


def _cookie(user_id):
    return {"token": _token(user_id)}


def test_derived_margins_and_realized_pnl(
    book_client,
    book_user,
    book_user_factory,
    book_funds_factory,
    book_order_factory,
    book_position_factory,
    book_transaction_factory,
):
    other = book_user_factory()
    book_funds_factory(book_user, available=50000)
    # blocks 1000: OPEN, entry, BUY
    book_order_factory(
        book_user, status="OPEN", side="BUY", product="CNC", qty=10, price=100
    )
    # does not block: OPEN but a CNC sell
    book_order_factory(
        book_user, status="OPEN", side="SELL", product="CNC", qty=5, price=200
    )
    # blocks 100: OPEN MIS sell
    book_order_factory(
        book_user, status="OPEN", side="SELL", product="MIS", qty=2, price=50
    )
    # ignores: not OPEN
    book_order_factory(
        book_user,
        status="EXECUTED",
        side="BUY",
        product="CNC",
        qty=10,
        filled=10,
        price=100,
    )
    # ignores: exit leg
    book_order_factory(
        book_user,
        status="OPEN",
        side="BUY",
        product="CNC",
        qty=10,
        price=100,
        is_exit=True,
    )
    # ignores: other user
    book_order_factory(
        other, status="OPEN", side="BUY", product="CNC", qty=99, price=999
    )
    book_position_factory(
        book_user, product="MIS", side="LONG", entry="200", qty=3
    )  # 600
    book_position_factory(
        book_user, product="MIS", side="SHORT", entry="100", qty=1
    )  # 100
    book_position_factory(book_user, product="CNC", entry="500", qty=9)  # ignored
    book_position_factory(other, product="MIS", entry="1000", qty=10)
    book_transaction_factory(book_user, kind="SETTLEMENT", amount="-350.5")
    book_transaction_factory(book_user, kind="SETTLEMENT", amount="100")
    book_transaction_factory(book_user, kind="DEPOSIT", amount="9999")  # ignored
    book_transaction_factory(other, kind="SETTLEMENT", amount="5000")

    body = book_client.get("/api/funds", cookies=_cookie(book_user)).json()

    assert set(body) == {
        "_id",
        "user",
        "available",
        "createdAt",
        "updatedAt",
        "__v",
        "usedMargin",
        "blockedInOrders",
        "misMargin",
        "realizedPnl",
    }
    assert body["user"] == book_user
    assert body["available"] == 50000
    assert body["blockedInOrders"] == 1100
    assert body["misMargin"] == 700
    assert body["usedMargin"] == 1800
    assert body["realizedPnl"] == -250.5


def test_creates_an_empty_funds_row_on_first_read(
    book_client, book_user, book_session_factory
):
    response = book_client.get("/api/funds", cookies=_cookie(book_user))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] == 0
    assert body["usedMargin"] == 0
    assert body["realizedPnl"] == 0
    # Express upserts the row during the read, so it now exists.
    with book_session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Fund).where(Fund.user_id == book_user)
            )
            == 1
        )


def test_transactions_are_newest_first_and_user_scoped(
    book_client, book_user, book_user_factory, book_transaction_factory
):
    older = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    newer = older + timedelta(days=1)
    other = book_user_factory()
    book_transaction_factory(book_user, kind="DEPOSIT", amount="100", created_at=older)
    book_transaction_factory(
        book_user, kind="SETTLEMENT", amount="-50", created_at=newer
    )
    book_transaction_factory(other, kind="DEPOSIT", amount="999", created_at=newer)

    response = book_client.get(
        "/api/funds/transactions", cookies=_cookie(book_user)
    )

    assert response.status_code == 200
    body = response.json()
    assert [transaction["kind"] for transaction in body] == ["SETTLEMENT", "DEPOSIT"]
    assert all(transaction["user"] == book_user for transaction in body)


def test_transactions_shape_and_empty(
    book_client, book_user, book_transaction_factory
):
    empty = book_client.get(
        "/api/funds/transactions", cookies=_cookie(book_user)
    )
    assert empty.status_code == 200
    assert empty.json() == []

    book_transaction_factory(book_user, kind="DEPOSIT", amount="100")

    body = book_client.get(
        "/api/funds/transactions", cookies=_cookie(book_user)
    ).json()
    assert len(body) == 1
    assert set(body[0]) == {
        "_id",
        "user",
        "kind",
        "method",
        "amount",
        "symbol",
        "status",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert body[0]["method"] == "Bank transfer"
    assert body[0]["symbol"] == ""
    assert body[0]["status"] == "COMPLETED"
    assert body[0]["createdAt"] == "2026-09-01T04:15:30.123Z"


def test_deposit_creates_funds_row_and_transaction(
    book_client, book_user, book_session_factory
):
    cookie = _cookie(book_user)

    response = book_client.post(
        "/api/funds/transactions",
        json={"kind": "DEPOSIT", "amount": 5000, "method": "UPI"},
        cookies=cookie,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"funds", "transaction"}
    # `funds` is the raw document, without the derived keys GET adds.
    assert set(body["funds"]) == {
        "_id",
        "user",
        "available",
        "createdAt",
        "updatedAt",
        "__v",
    }
    assert body["funds"]["user"] == book_user
    assert body["funds"]["available"] == 5000
    assert body["transaction"]["kind"] == "DEPOSIT"
    assert body["transaction"]["method"] == "UPI"
    assert body["transaction"]["amount"] == 5000
    assert body["transaction"]["symbol"] == ""
    assert body["transaction"]["status"] == "COMPLETED"

    # The created row is visible through the funds read, value and ledger both.
    assert book_client.get("/api/funds", cookies=cookie).json()["available"] == 5000
    with book_session_factory() as session:
        ledger = session.scalar(
            select(Transaction).where(Transaction.user_id == book_user)
        )
    assert ledger.amount == Decimal("5000.00")


def test_withdrawal_guards_the_balance(
    book_client, book_user, book_session_factory, book_funds_factory
):
    cookie = _cookie(book_user)
    book_funds_factory(book_user, available=1000)

    ok = book_client.post(
        "/api/funds/transactions",
        json={"kind": "WITHDRAWAL", "amount": "400"},
        cookies=cookie,
    )
    assert ok.status_code == 201
    assert ok.json()["funds"]["available"] == 600
    assert ok.json()["transaction"]["amount"] == -400
    assert ok.json()["transaction"]["method"] == "Bank withdrawal"

    too_much = book_client.post(
        "/api/funds/transactions",
        json={"kind": "WITHDRAWAL", "amount": 10000},
        cookies=cookie,
    )
    assert too_much.status_code == 400
    assert too_much.json() == {"message": "Amount exceeds available balance"}
    with book_session_factory() as session:
        assert session.scalar(
            select(Fund.available).where(Fund.user_id == book_user)
        ) == Decimal("600.00")
        assert session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == book_user)
        ) == 1


def test_withdrawal_without_a_funds_row_is_rejected(
    book_client, book_user, book_session_factory
):
    response = book_client.post(
        "/api/funds/transactions",
        json={"kind": "WITHDRAWAL", "amount": 100},
        cookies=_cookie(book_user),
    )

    assert response.status_code == 400
    assert response.json() == {"message": "Amount exceeds available balance"}
    # A rejected withdrawal must not create a zero row or a ledger entry.
    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Fund)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_transaction_validation_and_default_method(book_client, book_user):
    cookie = _cookie(book_user)

    for payload in [
        {"kind": "FEE", "amount": 100},
        {"kind": "DEPOSIT", "amount": 0},
        {"kind": "DEPOSIT", "amount": "abc"},
    ]:
        response = book_client.post(
            "/api/funds/transactions", json=payload, cookies=cookie
        )
        assert response.status_code == 400
        assert response.json() == {"message": "Invalid transaction"}

    # An unknown method label falls back to the generic text.
    fallback = book_client.post(
        "/api/funds/transactions",
        json={"kind": "DEPOSIT", "amount": 100, "method": "Crypto"},
        cookies=cookie,
    )
    assert fallback.json()["transaction"]["method"] == "Bank transfer"


def test_deposit_amount_is_rounded_to_paise(book_client, book_user):
    response = book_client.post(
        "/api/funds/transactions",
        json={"kind": "DEPOSIT", "amount": "100.005"},
        cookies=_cookie(book_user),
    )

    assert response.status_code == 201
    assert response.json()["funds"]["available"] == 100.01
    assert response.json()["transaction"]["amount"] == 100.01
