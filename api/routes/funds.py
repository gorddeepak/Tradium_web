"""Port of the read routes in server/routes/fundsRoutes.js.

The Express routes are:
    router.get("/", protect, ...)              // GET /api/funds
    router.get("/transactions", protect, ...)  // GET /api/funds/transactions

`GET /api/funds` mirrors `derivedFunds`: it upserts a funds row with
`available: 0` when the user has none, then computes the derived keys the
frontend reads. `available` is free cash; `usedMargin` is derived, never
stored. `GET /api/funds/transactions` is a plain newest-first read of the
`transactions` collection. The write route (`POST /api/funds/transactions`)
is not ported.
"""

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/funds")
def get_funds(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)

    funds = db["funds"].find_one({"user": user})
    if funds is None:
        # Express creates an empty funds row on the first read; keep that.
        now = datetime.now(timezone.utc)
        funds = {
            "_id": ObjectId(),
            "user": user,
            "available": 0,
            "createdAt": now,
            "updatedAt": now,
            "__v": 0,
        }
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
