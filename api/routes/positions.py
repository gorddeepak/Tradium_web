"""Port of server/routes/positionsRoutes.js.

The Express routes are:
    router.get("/", protect, ...)                    // GET /api/positions
    router.post("/:id/square-off", protect, ...)     // POST /api/positions/:id/square-off

Square-off prices at a live Yahoo quote and falls back to the position's
stored `ltp`. The provider is deferred (see `market_data.fetch_quote`), so the
documented fallback is what runs today.
"""

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..documents import inc_funds, new_document, utcnow
from ..js_compat import js_number
from ..market_data import fetch_quote
from ..serialization import to_json_value

router = APIRouter()


@router.get("/api/positions")
def list_positions(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    user = ObjectId(user_id)
    positions = list(db["positions"].find({"user": user}))
    return [to_json_value(position) for position in positions]


@router.post("/api/positions/{position_id}/square-off")
def square_off(
    position_id: str,
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)
    position = db["positions"].find_one({"_id": ObjectId(position_id), "user": user})
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position["product"] != "MIS":
        raise HTTPException(
            status_code=400, detail="Only MIS positions can be squared off here"
        )
    if not position.get("ltp"):
        raise HTTPException(
            status_code=400,
            detail="No live price for this position yet — try again shortly",
        )

    # A live quote if one is available; otherwise the stored ltp.
    exit_price = position["ltp"]
    quote = fetch_quote(position["symbol"])
    if quote and quote.get("ltp"):
        exit_price = quote["ltp"]

    # P&L per share: LONG is exit - entry, SHORT is entry - exit.
    # js_number renders whole values the way JavaScript's JSON does (500, not 500.0).
    direction = 1 if position["side"] == "LONG" else -1
    pnl = js_number((exit_price - position["entry"]) * position["qty"] * direction)
    release = js_number(position["entry"] * position["qty"] + pnl)

    # Claim the position first so only one square-off pays.
    claimed = db["positions"].delete_one({"_id": position["_id"]})
    if claimed.deleted_count == 0:
        raise HTTPException(status_code=409, detail="Position was already squared off")

    inc_funds(db, user, release)

    # Book the realized P&L in the ledger.
    db["transactions"].insert_one(
        new_document(
            user=user,
            kind="SETTLEMENT",
            method=f"{position['symbol']} MIS square-off",
            amount=pnl,
            symbol=position["symbol"],
            status="COMPLETED",
        )
    )

    # The closing trade shows up in the orders book, so history stays honest.
    db["orders"].insert_one(
        new_document(
            user=user,
            symbol=position["symbol"],
            name=position["name"],
            exchange=position["exchange"],
            side="SELL" if position["side"] == "LONG" else "BUY",
            type="MARKET",
            product="MIS",
            qty=position["qty"],
            filled=position["qty"],
            price=exit_price,
            triggerPrice=0,
            slTrigger=0,
            tpPrice=0,
            groupId="",
            isExit=False,
            status="EXECUTED",
        )
    )

    # Cancel any live exit pair so it can't fire after square-off.
    db["orders"].update_many(
        {
            "user": user,
            "symbol": position["symbol"],
            "exchange": position["exchange"],
            "product": "MIS",
            "isExit": True,
            "status": "OPEN",
        },
        {"$set": {"status": "CANCELLED", "updatedAt": utcnow()}},
    )

    return {"message": f"Squared off {position['symbol']}", "pnl": pnl}
