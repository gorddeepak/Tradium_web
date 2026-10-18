"""Focused tests for the funds reads: derived keys, first-read creation,
isolation, and the transaction ledger.

Authentication and database-failure behaviour are shared with the holdings
suite and not repeated here.
"""

from datetime import datetime, timezone

from bson import ObjectId

CREATED = datetime(2026, 9, 1, 4, 15, 30, 123456, tzinfo=timezone.utc)


def _funds_doc(user, available):
    return {
        "_id": ObjectId(),
        "user": user,
        "available": available,
        "createdAt": CREATED,
        "updatedAt": CREATED,
        "__v": 0,
    }


def _transaction_doc(user, kind, amount, created=CREATED):
    return {
        "_id": ObjectId(),
        "user": user,
        "kind": kind,
        "method": "Bank transfer",
        "amount": amount,
        "symbol": "",
        "status": "COMPLETED",
        "createdAt": created,
        "updatedAt": created,
        "__v": 0,
    }


def test_derived_margins_and_realized_pnl(
    client, database, make_token, user_id, other_user_id, orders_factory, positions_factory
):
    database["funds"].insert_one(_funds_doc(user_id, 50000))
    database["orders"].insert_many(
        [
            # blocks 1000: OPEN, entry, BUY
            orders_factory(user_id, status="OPEN", side="BUY", product="CNC", qty=10, filled=0, price=100.0),
            # does not block: OPEN but a CNC sell
            orders_factory(user_id, status="OPEN", side="SELL", product="CNC", qty=5, filled=0, price=200.0),
            # blocks 100: OPEN MIS sell
            orders_factory(user_id, status="OPEN", side="SELL", product="MIS", qty=2, filled=0, price=50.0),
            # ignores: not OPEN
            orders_factory(user_id, status="EXECUTED", side="BUY", product="CNC", qty=10, filled=10, price=100.0),
            # ignores: exit leg
            orders_factory(user_id, status="OPEN", side="BUY", product="CNC", qty=10, filled=0, price=100.0, isExit=True),
            # ignores: other user
            orders_factory(other_user_id, status="OPEN", side="BUY", product="CNC", qty=99, filled=0, price=999.0),
        ]
    )
    database["positions"].insert_many(
        [
            positions_factory(user_id, product="MIS", entry=200.0, qty=3),  # 600
            positions_factory(user_id, product="MIS", entry=100.0, qty=1),  # 100
            positions_factory(user_id, product="CNC", entry=500.0, qty=9),  # not MIS, ignored
            positions_factory(other_user_id, product="MIS", entry=1000.0, qty=10),
        ]
    )
    database["transactions"].insert_many(
        [
            _transaction_doc(user_id, "SETTLEMENT", -350.5),
            _transaction_doc(user_id, "SETTLEMENT", 100.0),
            _transaction_doc(user_id, "DEPOSIT", 9999.0),  # not SETTLEMENT, ignored
            _transaction_doc(other_user_id, "SETTLEMENT", 5000.0),
        ]
    )

    body = client.get("/api/funds", cookies={"token": make_token(user_id)}).json()

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
    assert body["user"] == str(user_id)
    assert body["available"] == 50000
    assert body["blockedInOrders"] == 1100.0
    assert body["misMargin"] == 700.0
    assert body["usedMargin"] == 1800.0
    assert body["realizedPnl"] == -250.5


def test_creates_an_empty_funds_row_on_first_read(client, database, make_token, user_id):
    response = client.get("/api/funds", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] == 0
    assert body["usedMargin"] == 0
    assert body["realizedPnl"] == 0
    # Express upserts the row during the read, so it now exists.
    assert database["funds"].count_documents({"user": user_id}) == 1


def test_transactions_are_newest_first_and_user_scoped(
    client, database, make_token, user_id, other_user_id
):
    older = datetime(2026, 9, 1, 4, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 9, 2, 4, 0, 0, tzinfo=timezone.utc)
    database["transactions"].insert_many(
        [
            _transaction_doc(user_id, "DEPOSIT", 100.0, created=older),
            _transaction_doc(user_id, "SETTLEMENT", -50.0, created=newer),
            _transaction_doc(other_user_id, "DEPOSIT", 999.0, created=newer),
        ]
    )

    response = client.get("/api/funds/transactions", cookies={"token": make_token(user_id)})

    assert response.status_code == 200
    body = response.json()
    assert [transaction["kind"] for transaction in body] == ["SETTLEMENT", "DEPOSIT"]
    assert all(transaction["user"] == str(user_id) for transaction in body)


def test_transactions_shape_and_empty(client, database, make_token, user_id):
    empty = client.get("/api/funds/transactions", cookies={"token": make_token(user_id)})
    assert empty.status_code == 200
    assert empty.json() == []

    database["transactions"].insert_one(_transaction_doc(user_id, "DEPOSIT", 100.0))

    body = client.get("/api/funds/transactions", cookies={"token": make_token(user_id)}).json()
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
    assert body[0]["createdAt"] == "2026-09-01T04:15:30.123Z"
