"""Port of the read and write routes in server/routes/fundsRoutes.js.

The Express routes are:
    router.get("/", protect, ...)              // GET /api/funds
    router.get("/transactions", protect, ...)  // GET /api/funds/transactions
    router.post("/transactions", protect, ...) // POST /api/funds/transactions

`GET /api/funds` mirrors `derivedFunds`: it upserts a funds row with
`available: 0` when the user has none, then computes the derived keys the
frontend reads. `available` is free cash; `usedMargin` is derived, never
stored.
"""

import math

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException
from pymongo import ReturnDocument
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..documents import inc_funds, new_document, utcnow
from ..js_compat import js_number
from ..serialization import to_json_value

router = APIRouter()

# Only known payment-method labels are stored; anything else falls back.
ALLOWED_METHODS = ["Paper cash", "UPI", "Net banking", "Bank transfer", "Bank withdrawal"]

DEFAULT_METHOD = {"DEPOSIT": "Bank transfer", "WITHDRAWAL": "Bank withdrawal"}


@router.get("/api/funds")
def get_funds(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)

    funds = db["funds"].find_one({"user": user})
    if funds is None:
        # Express creates an empty funds row on the first read; keep that.
        funds = new_document(user=user, available=0)
        db["funds"].insert_one(funds)

    # Only entry orders block cash: not exits, and BUY or MIS.
    open_orders = list(db["orders"].find({"user": user, "status": "OPEN"}))
    blocked_in_orders = sum(
        (order["qty"] - order.get("filled", 0)) * order["price"]
        for order in open_orders
        if not order.get("isExit") and (order["side"] == "BUY" or order["product"] == "MIS")
    )

    positions = list(db["positions"].find({"user": user, "product": "MIS"}))
    mis_margin = sum(position["entry"] * position["qty"] for position in positions)

    settlements = list(db["transactions"].find({"user": user, "kind": "SETTLEMENT"}))
    realized_pnl = sum(settlement["amount"] for settlement in settlements)

    result = dict(funds)
    result["usedMargin"] = blocked_in_orders + mis_margin
    result["blockedInOrders"] = blocked_in_orders
    result["misMargin"] = mis_margin
    result["realizedPnl"] = realized_pnl
    return to_json_value(result)


@router.get("/api/funds/transactions")
def list_transactions(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    user = ObjectId(user_id)
    # Express sorts newest first; the ledger renders in this order.
    transactions = list(db["transactions"].find({"user": user}).sort("createdAt", -1))
    return [to_json_value(transaction) for transaction in transactions]


@router.post("/api/funds/transactions", status_code=201)
def create_transaction(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    kind = body.get("kind")
    # Coerce to a number, like qty in the orders route.
    amount = js_number(body.get("amount"))
    if kind not in ("DEPOSIT", "WITHDRAWAL") or not math.isfinite(amount) or amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid transaction")

    user = ObjectId(user_id)
    if kind == "DEPOSIT":
        funds = inc_funds(db, user, amount)
    else:
        # The $gte guard makes the debit atomic so the balance can't go negative.
        funds = db["funds"].find_one_and_update(
            {"user": user, "available": {"$gte": amount}},
            {"$inc": {"available": -amount}, "$set": {"updatedAt": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if funds is None:
            raise HTTPException(status_code=400, detail="Amount exceeds available balance")

    sent_method = body.get("method")
    if sent_method not in ALLOWED_METHODS:
        sent_method = None

    transaction = new_document(
        user=user,
        kind=kind,
        method=sent_method or DEFAULT_METHOD[kind],
        amount=amount if kind == "DEPOSIT" else -amount,
        symbol="",
        status="COMPLETED",
    )
    db["transactions"].insert_one(transaction)

    # `funds` here is the raw document, without the derived keys GET adds.
    return {"funds": to_json_value(funds), "transaction": to_json_value(transaction)}
