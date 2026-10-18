"""Port of server/utils/executeOrder.js.

Applies fills and builds/cancels exit orders. The orders routes use these
functions now; the price-sync job will reuse them when that phase is ported.
The atomic merge on positions/holdings keeps the server-side ``$set``
pipeline the Express code relies on so concurrent updates can't be lost.
"""

from pymongo import ReturnDocument

from .documents import inc_funds, new_document, utcnow
from .js_compat import js_number


def apply_fill(db, order):
    """What happens when an order fills. Port of ``applyFill()``."""
    # Bracket exits spawn now — the entry has actually filled.
    if not order.get("isExit") and (
        order.get("slTrigger", 0) > 0 or order.get("tpPrice", 0) > 0
    ):
        spawn_bracket_exits(db, order)

    # Intraday: goes to the positions book, cash was already blocked at placement.
    if order["product"] == "MIS":
        side = "LONG" if order["side"] == "BUY" else "SHORT"
        existing = db["positions"].find_one(
            {
                "user": order["user"],
                "symbol": order["symbol"],
                "exchange": order["exchange"],
                "product": "MIS",
                "side": side,
            }
        )
        if existing:
            # Atomic merge: computes the new average server-side.
            db["positions"].update_one(
                {"_id": existing["_id"]},
                [
                    {
                        "$set": {
                            "qty": {"$add": ["$qty", order["qty"]]},
                            "entry": {
                                "$divide": [
                                    {
                                        "$add": [
                                            {"$multiply": ["$qty", "$entry"]},
                                            order["qty"] * order["price"],
                                        ]
                                    },
                                    {"$add": ["$qty", order["qty"]]},
                                ]
                            },
                            "ltp": order["price"],
                        }
                    }
                ],
            )
        else:
            db["positions"].insert_one(
                new_document(
                    user=order["user"],
                    symbol=order["symbol"],
                    name=order["name"],
                    exchange=order["exchange"],
                    side=side,
                    product="MIS",
                    qty=order["qty"],
                    entry=order["price"],
                    ltp=order["price"],
                )
            )
        return

    # Delivery (CNC).
    existing = db["holdings"].find_one(
        {
            "user": order["user"],
            "symbol": order["symbol"],
            "exchange": order["exchange"],
        }
    )

    if order["side"] == "BUY":
        if existing:
            db["holdings"].update_one(
                {"_id": existing["_id"]},
                [
                    {
                        "$set": {
                            "qty": {"$add": ["$qty", order["qty"]]},
                            "avgPrice": {
                                "$divide": [
                                    {
                                        "$add": [
                                            {"$multiply": ["$qty", "$avgPrice"]},
                                            order["qty"] * order["price"],
                                        ]
                                    },
                                    {"$add": ["$qty", order["qty"]]},
                                ]
                            },
                        }
                    }
                ],
            )
        else:
            db["holdings"].insert_one(
                new_document(
                    user=order["user"],
                    symbol=order["symbol"],
                    name=order["name"],
                    exchange=order["exchange"],
                    qty=order["qty"],
                    avgPrice=order["price"],
                    ltp=order["price"],
                    dayChangePct=0,
                    sector="",
                )
            )
    elif order["side"] == "SELL":
        # Check shares at fill time: the qty guard makes this an atomic CAS.
        updated = db["holdings"].find_one_and_update(
            {
                "user": order["user"],
                "symbol": order["symbol"],
                "exchange": order["exchange"],
                "qty": {"$gte": order["qty"]},
            },
            {"$inc": {"qty": -order["qty"]}, "$set": {"updatedAt": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            # REJECTED (not cancelled): there was nothing left to sell.
            order["status"] = "REJECTED"
            db["orders"].update_one(
                {"_id": order["_id"]},
                {"$set": {"status": "REJECTED", "updatedAt": utcnow()}},
            )
            cancel_sibling_exits(db, order)
            return
        if updated["qty"] <= 0:
            db["holdings"].delete_one({"_id": updated["_id"]})

        # The sell's proceeds land only now that the trade actually happened.
        inc_funds(db, order["user"], order["qty"] * order["price"])

        # Record the realized P&L so closed trades show up in the ledger.
        db["transactions"].insert_one(
            new_document(
                user=order["user"],
                kind="SETTLEMENT",
                method=f"{order['symbol']} sell",
                amount=js_number((order["price"] - updated["avgPrice"]) * order["qty"]),
                symbol=order["symbol"],
                status="COMPLETED",
            )
        )


def create_exit_pair(
    db, *, user, symbol, name, exchange, product, qty, side, sl_trigger, tp_price, group_id
):
    """Build the SL and TP exit orders for a bracket or an exit request.

    Port of ``createExitPair()``. Only a CNC BUY exit blocks cash.
    """
    legs = []
    if sl_trigger > 0:
        legs.append({"type": "SL-M", "triggerPrice": sl_trigger, "price": sl_trigger})
    if tp_price > 0:
        legs.append({"type": "LIMIT", "triggerPrice": 0, "price": tp_price})

    created = []
    for leg in legs:
        if side == "BUY" and product == "CNC":
            inc_funds(db, user, -qty * leg["price"])
        document = new_document(
            user=user,
            symbol=symbol,
            name=name,
            exchange=exchange,
            side=side,
            type=leg["type"],
            product=product,
            qty=qty,
            filled=0,
            price=leg["price"],
            triggerPrice=leg["triggerPrice"],
            slTrigger=0,
            tpPrice=0,
            groupId=group_id,
            isExit=True,
            status="OPEN",
        )
        db["orders"].insert_one(document)
        created.append(document)
    return created


def spawn_bracket_exits(db, entry):
    """A bracket entry just filled — spawn its exits with the opposite side."""
    return create_exit_pair(
        db,
        user=entry["user"],
        symbol=entry["symbol"],
        name=entry["name"],
        exchange=entry["exchange"],
        product=entry["product"],
        qty=entry["qty"],
        side="SELL" if entry["side"] == "BUY" else "BUY",
        sl_trigger=entry["slTrigger"],
        tp_price=entry["tpPrice"],
        group_id=entry["groupId"],
    )


def cancel_sibling_exits(db, order):
    """OCO: one exit filled — cancel its still-open siblings."""
    siblings = list(
        db["orders"].find(
            {
                "groupId": order["groupId"],
                "isExit": True,
                "status": "OPEN",
                "_id": {"$ne": order["_id"]},
            }
        )
    )
    for sibling in siblings:
        db["orders"].update_one(
            {"_id": sibling["_id"]},
            {"$set": {"status": "CANCELLED", "updatedAt": utcnow()}},
        )
        if sibling["side"] == "BUY" and sibling["product"] == "CNC":
            inc_funds(db, sibling["user"], sibling["qty"] * sibling["price"])
