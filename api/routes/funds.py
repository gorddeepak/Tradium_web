"""Port of the read and write routes in server/routes/fundsRoutes.js.

The Express routes are:
    router.get("/", protect, ...)              // GET /api/funds
    router.get("/transactions", protect, ...)  // GET /api/funds/transactions
    router.post("/transactions", protect, ...) // POST /api/funds/transactions

Phase 3C2 moves funds and the transaction ledger to PostgreSQL. ``available``
is free cash; ``usedMargin`` is derived, never stored. Every balance change and
its ledger row commit in one transaction.
"""

import math
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..js_compat import js_number
from ..postgres.models import Order, Position, Transaction
from ..postgres.session import get_session
from ..serialization import to_json_value
from ..trading_book import (
    CASH,
    adjust_funds,
    decimal_from,
    debit_existing_funds,
    fund_document,
    get_or_create_fund,
    lock_user,
    new_id,
    quantize,
    transaction_document,
    utcnow,
)

router = APIRouter()

# Only known payment-method labels are stored; anything else falls back.
ALLOWED_METHODS = ["Paper cash", "UPI", "Net banking", "Bank transfer", "Bank withdrawal"]

DEFAULT_METHOD = {"DEPOSIT": "Bank transfer", "WITHDRAWAL": "Bank withdrawal"}


@router.get("/api/funds")
def get_funds(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    now = utcnow()
    with session.begin():
        # Express creates an empty funds row on the first read; keep that.
        fund = get_or_create_fund(session, user_id, now)

        # Only entry orders block cash: not exits, and BUY or MIS.
        open_orders = session.scalars(
            select(Order).where(
                Order.user_id == user_id,
                Order.status == "OPEN",
                Order.is_exit.is_(False),
                or_(Order.side == "BUY", Order.product == "MIS"),
            )
        ).all()
        blocked_in_orders = sum(
            (Decimal(order.qty - order.filled) * order.price for order in open_orders),
            Decimal(0),
        )

        positions = session.scalars(
            select(Position).where(
                Position.user_id == user_id, Position.product == "MIS"
            )
        ).all()
        mis_margin = sum(
            (position.entry * Decimal(position.qty) for position in positions),
            Decimal(0),
        )

        realized_pnl = session.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.kind == "SETTLEMENT",
            )
        )

        document = fund_document(fund)
        blocked_in_orders = quantize(blocked_in_orders, CASH)
        mis_margin = quantize(mis_margin, CASH)
        document["usedMargin"] = blocked_in_orders + mis_margin
        document["blockedInOrders"] = blocked_in_orders
        document["misMargin"] = mis_margin
        document["realizedPnl"] = quantize(realized_pnl, CASH)

    return to_json_value(document)


@router.get("/api/funds/transactions")
def list_transactions(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    # Express sorts newest first; the ledger renders in this order.
    transactions = session.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
    ).all()
    return [to_json_value(transaction_document(row)) for row in transactions]


@router.post("/api/funds/transactions", status_code=201)
def create_transaction(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    kind = body.get("kind")
    # Coerce to a number, like qty in the orders route.
    amount_number = js_number(body.get("amount"))
    if (
        kind not in ("DEPOSIT", "WITHDRAWAL")
        or not math.isfinite(amount_number)
        or amount_number <= 0
    ):
        raise HTTPException(status_code=400, detail="Invalid transaction")

    amount = quantize(decimal_from(amount_number), CASH)
    now = utcnow()

    with session.begin():
        lock_user(session, user_id)

        if kind == "DEPOSIT":
            fund = adjust_funds(session, user_id, amount, now)
        else:
            # The guard makes the debit atomic so the balance can't go negative.
            fund = debit_existing_funds(session, user_id, amount, now)
            if fund is None:
                raise HTTPException(
                    status_code=400, detail="Amount exceeds available balance"
                )

        sent_method = body.get("method")
        if sent_method not in ALLOWED_METHODS:
            sent_method = None

        transaction = Transaction(
            id=new_id(),
            user_id=user_id,
            kind=kind,
            method=sent_method or DEFAULT_METHOD[kind],
            amount=amount if kind == "DEPOSIT" else -amount,
            symbol="",
            status="COMPLETED",
            created_at=now,
            updated_at=now,
            version=0,
        )
        session.add(transaction)
        session.flush()

        funds_document = fund_document(fund)
        transaction_doc = transaction_document(transaction)

    # `funds` here is the raw document, without the derived keys GET adds.
    return {
        "funds": to_json_value(funds_document),
        "transaction": to_json_value(transaction_doc),
    }
