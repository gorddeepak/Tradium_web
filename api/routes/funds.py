"""Port of the read route in server/routes/fundsRoutes.js.

The Express route is:
    router.get("/", protect, async (req, res) => {
      res.json(await derivedFunds(req.userId));
    });

`derivedFunds` upserts a funds row with `available: 0` when the user has
none, then computes the derived keys the frontend reads. `available` is free
cash; `usedMargin` is derived, never stored. The other funds read
(`GET /api/funds/transactions`) is not ported yet.
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
