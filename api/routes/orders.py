"""Port of server/routes/ordersRoutes.js.

The Express routes are:
    router.get("/", protect, ...)        // GET /api/orders
    router.post("/", protect, ...)       // POST /api/orders
    router.post("/exits", protect, ...)  // POST /api/orders/exits
    router.delete("/:id", protect, ...)  // DELETE /api/orders/:id

MARKET orders fill at a live Yahoo price. That provider is deferred (see
`market_data.fetch_quote`), so a MARKET order answers the documented 503
instead of filling; LIMIT/SL/SL-M placement and cancels are independent of it.
"""

from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException
from pymongo import ReturnDocument
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..documents import inc_funds, new_document, utcnow
from ..js_compat import (
    format_inr,
    is_falsy_number,
    is_whole_number,
    js_number,
    js_number_or_zero,
    number_text,
)
from ..market_data import fetch_quote
from ..order_engine import apply_fill, create_exit_pair
from ..serialization import to_json_value

router = APIRouter()

SIDES = ("BUY", "SELL")
TYPES = ("LIMIT", "MARKET", "SL", "SL-M")
PRODUCTS = ("CNC", "MIS")


@router.get("/api/orders")
def list_orders(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim, the
    # same way the holdings route does.
    user = ObjectId(user_id)
    # Express sorts newest first; the Orders page renders in this order.
    orders = list(db["orders"].find({"user": user}).sort("createdAt", -1))
    return [to_json_value(order) for order in orders]


@router.post("/api/orders", status_code=201)
def place_order(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    symbol = body.get("symbol")
    name = body.get("name")
    exchange = body.get("exchange")
    side = body.get("side")
    order_type = body.get("type")
    product = body.get("product")

    # Coerce to numbers so a string qty can't break the math.
    qty = js_number(body.get("qty"))
    price = js_number(body.get("price"))
    trigger_price = js_number_or_zero(body.get("triggerPrice"))
    sl_trigger = js_number_or_zero(body.get("slTrigger"))
    tp_price = js_number_or_zero(body.get("tpPrice"))

    if not symbol or not side or not order_type or not name:
        raise HTTPException(
            status_code=400, detail="symbol, name, side and type are required"
        )
    if side not in SIDES:
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    if order_type not in TYPES:
        raise HTTPException(
            status_code=400, detail="type must be LIMIT, MARKET, SL or SL-M"
        )
    if product not in PRODUCTS:
        raise HTTPException(status_code=400, detail="product must be CNC or MIS")
    if is_falsy_number(qty) or qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if not is_whole_number(qty):
        raise HTTPException(status_code=400, detail="Quantity must be a whole number")
    if (is_falsy_number(price) or price <= 0) and order_type != "MARKET":
        raise HTTPException(status_code=400, detail="Price must be greater than zero")

    # MARKET orders fill at the live price; LIMIT/SL keep the client's price.
    exec_price = price
    if order_type == "MARKET":
        quote = fetch_quote(symbol)
        if not quote or not quote.get("ltp"):
            raise HTTPException(
                status_code=503,
                detail=f"No live price available for {symbol}, try again in a moment",
            )
        exec_price = quote["ltp"]

    # A stop order needs a trigger to ever fire.
    if order_type in ("SL", "SL-M") and trigger_price <= 0:
        raise HTTPException(
            status_code=400, detail="SL and SL-M orders need a trigger price"
        )

    # Bracket: SL on the losing side, TP on the winning side.
    if sl_trigger > 0 and tp_price > 0:
        valid = sl_trigger < tp_price if side == "BUY" else sl_trigger > tp_price
        if not valid:
            message = (
                "Stop-loss trigger must be below the target price for a buy"
                if side == "BUY"
                else "Stop-loss trigger must be above the target price for a sell"
            )
            raise HTTPException(status_code=400, detail=message)

    user = ObjectId(user_id)

    # Check the user can afford this order. The $gte guard makes the debit
    # atomic; there is no upsert here, matching Express.
    if side == "BUY" or product == "MIS":
        debited = db["funds"].find_one_and_update(
            {"user": user, "available": {"$gte": qty * exec_price}},
            {"$inc": {"available": -qty * exec_price}, "$set": {"updatedAt": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if debited is None:
            funds = db["funds"].find_one({"user": user})
            available = funds["available"] if funds else 0
            raise HTTPException(
                status_code=400,
                detail=(
                    "Insufficient funds: order needs "
                    f"₹{format_inr(qty * exec_price)} but only "
                    f"₹{format_inr(available)} is available"
                ),
            )

    # CNC sells need real holdings; MIS shorts are allowed.
    if side == "SELL" and product != "MIS":
        holdings_query = {"user": user, "symbol": symbol}
        if exchange is not None:
            holdings_query["exchange"] = exchange
        held = db["holdings"].find_one(holdings_query)
        held_qty = held["qty"] if held else 0
        if qty > held_qty:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient holdings: you hold {number_text(held_qty)} {symbol} "
                    f"but tried to sell {number_text(qty)}"
                ),
            )

    # Cash was blocked above; refunded on cancel or fill.
    executed = order_type == "MARKET"
    order = new_document(
        user=user,
        symbol=symbol,
        name=name,
        exchange=exchange if exchange is not None else "NSE",
        side=side,
        type=order_type,
        product=product,
        qty=qty,
        filled=qty if executed else 0,
        price=exec_price,
        triggerPrice=trigger_price,
        slTrigger=sl_trigger,
        tpPrice=tp_price,
        groupId="",
        isExit=False,
        status="EXECUTED" if executed else "OPEN",
    )
    # A bracket entry anchors its own group; the exits copy this groupId.
    if sl_trigger > 0 or tp_price > 0:
        order["groupId"] = str(order["_id"])
    db["orders"].insert_one(order)

    # MARKET orders fill now; limit orders wait for priceSync.
    if order["status"] == "EXECUTED":
        apply_fill(db, order)

    return to_json_value(order)


@router.post("/api/orders/exits", status_code=201)
def set_exits(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    symbol = body.get("symbol")
    exchange = body.get("exchange")
    product = body.get("product")
    sl_trigger = js_number_or_zero(body.get("slTrigger"))
    tp_price = js_number_or_zero(body.get("tpPrice"))

    if not symbol or not product:
        raise HTTPException(status_code=400, detail="symbol and product are required")
    if sl_trigger <= 0 and tp_price <= 0:
        raise HTTPException(
            status_code=400, detail="Set at least a stop-loss trigger or a target price"
        )

    user = ObjectId(user_id)

    if product == "CNC":
        query = {"user": user, "symbol": symbol}
        if exchange is not None:
            query["exchange"] = exchange
        holding = db["holdings"].find_one(query)
        if holding is None:
            raise HTTPException(status_code=404, detail=f"No holding found for {symbol}")
        qty = holding["qty"]
        name = holding["name"]
        # A holding is always long — it exits by selling.
        side = "SELL"
        if sl_trigger > 0 and tp_price > 0 and sl_trigger >= tp_price:
            raise HTTPException(
                status_code=400,
                detail="Stop-loss trigger must be below the target price",
            )
    elif product == "MIS":
        query = {"user": user, "symbol": symbol, "product": "MIS"}
        if exchange is not None:
            query["exchange"] = exchange
        position = db["positions"].find_one(query)
        if position is None:
            raise HTTPException(
                status_code=404, detail=f"No open MIS position found for {symbol}"
            )
        qty = position["qty"]
        name = position["name"]
        side = "SELL" if position["side"] == "LONG" else "BUY"
        sl_below_tp = sl_trigger < tp_price
        long_needs_sl_below = sl_below_tp if position["side"] == "LONG" else not sl_below_tp
        if sl_trigger > 0 and tp_price > 0 and not long_needs_sl_below:
            message = (
                "Stop-loss trigger must be below the target price for a long"
                if position["side"] == "LONG"
                else "Stop-loss trigger must be above the target price for a short"
            )
            raise HTTPException(status_code=400, detail=message)
    else:
        raise HTTPException(status_code=400, detail="product must be CNC or MIS")

    # Cancel the old exit pair first; only CNC BUY exits refund cash.
    old_query = {
        "user": user,
        "symbol": symbol,
        "product": product,
        "isExit": True,
        "status": "OPEN",
    }
    if exchange is not None:
        old_query["exchange"] = exchange
    for old in list(db["orders"].find(old_query)):
        db["orders"].update_one(
            {"_id": old["_id"]},
            {"$set": {"status": "CANCELLED", "updatedAt": utcnow()}},
        )
        if old["side"] == "BUY" and old["product"] == "CNC":
            inc_funds(db, user, old["qty"] * old["price"])

    # No entry order to anchor the group, so a fresh id plays that role.
    orders = create_exit_pair(
        db,
        user=user,
        symbol=symbol,
        name=name,
        exchange=exchange if exchange is not None else "NSE",
        product=product,
        qty=qty,
        side=side,
        sl_trigger=sl_trigger,
        tp_price=tp_price,
        group_id=str(uuid4()),
    )

    return {"message": f"Exit rules set for {symbol}", "orders": to_json_value(orders)}


@router.delete("/api/orders/{order_id}")
def cancel_order(
    order_id: str,
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)
    # Only OPEN orders match, so a just-filled order never refunds.
    order = db["orders"].find_one_and_update(
        {"_id": ObjectId(order_id), "user": user, "status": "OPEN"},
        {"$set": {"status": "CANCELLED", "updatedAt": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )

    if order is None:
        existing = db["orders"].find_one({"_id": ObjectId(order_id), "user": user})
        if existing is None:
            raise HTTPException(status_code=404, detail="Order not found")
        raise HTTPException(
            status_code=400, detail=f"Order is already {existing['status'].lower()}"
        )

    unfilled = order["qty"] - order["filled"]
    # Refund blocked cash (bracket exits only if they were a CNC BUY).
    if order.get("isExit"):
        blocks = order["side"] == "BUY" and order["product"] == "CNC"
    else:
        blocks = order["side"] == "BUY" or order["product"] == "MIS"
    if unfilled > 0 and blocks:
        inc_funds(db, user, unfilled * order["price"])

    return to_json_value(order)
