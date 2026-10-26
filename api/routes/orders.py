"""Port of server/routes/ordersRoutes.js, now backed by PostgreSQL.

The Express routes are:
    router.get("/", protect, ...)        // GET /api/orders
    router.post("/", protect, ...)       // POST /api/orders
    router.post("/exits", protect, ...)  // POST /api/orders/exits
    router.delete("/:id", protect, ...)  // DELETE /api/orders/:id

Phase 3C2 moves placement, exits and cancellation to the PostgreSQL book. Each
write is one transaction guarded by the per-user advisory lock, so a debit,
order insert, MARKET fill and bracket spawn either all commit or all roll back.
"""

from uuid import uuid4

from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..js_compat import (
    format_inr,
    is_falsy_number,
    is_whole_number,
    js_number,
    js_number_or_zero,
    number_text,
)
from ..market_data import fetch_quote
from ..order_engine import create_exit_pair, fill_order
from ..postgres.models import Holding, Order, Position
from ..postgres.session import get_session
from ..serialization import to_json_value
from ..trading_book import (
    CASH,
    PRICE,
    decimal_from,
    debit_existing_funds,
    funds_available,
    lock_user,
    new_id,
    order_document,
    quote_is_fresh,
    quantize,
    refund_blocked_cash,
    utcnow,
)

router = APIRouter()

SIDES = ("BUY", "SELL")
TYPES = ("LIMIT", "MARKET", "SL", "SL-M")
PRODUCTS = ("CNC", "MIS")

SUPPORTED_EXCHANGE = "NSE"


@router.get("/api/orders")
def list_orders(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    # Express sorts newest first; the Orders page renders in this order.
    orders = session.scalars(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    return [to_json_value(order_document(order)) for order in orders]


@router.post("/api/orders", status_code=201)
def place_order(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    symbol = body.get("symbol")
    name = body.get("name")
    exchange = body.get("exchange")
    side = body.get("side")
    order_type = body.get("type")
    product = body.get("product")

    # Coerce to numbers so a string qty can't break the math.
    qty_number = js_number(body.get("qty"))
    price_number = js_number(body.get("price"))
    trigger_number = js_number_or_zero(body.get("triggerPrice"))
    sl_number = js_number_or_zero(body.get("slTrigger"))
    tp_number = js_number_or_zero(body.get("tpPrice"))

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
    if is_falsy_number(qty_number) or qty_number <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if not is_whole_number(qty_number):
        raise HTTPException(status_code=400, detail="Quantity must be a whole number")
    if (is_falsy_number(price_number) or price_number <= 0) and order_type != "MARKET":
        raise HTTPException(status_code=400, detail="Price must be greater than zero")

    # The PostgreSQL book is NSE-only (schema constraint), so reject an
    # unsupported exchange explicitly instead of failing at the insert.
    if exchange is None:
        exchange = SUPPORTED_EXCHANGE
    if exchange != SUPPORTED_EXCHANGE:
        raise HTTPException(status_code=400, detail="Unsupported exchange")

    qty = int(qty_number)
    price = quantize(decimal_from(price_number), PRICE)
    trigger_price = quantize(decimal_from(trigger_number), PRICE)
    sl_trigger = quantize(decimal_from(sl_number), PRICE)
    tp_price = quantize(decimal_from(tp_number), PRICE)

    # MARKET orders fill at the live price; LIMIT/SL keep the client's price.
    exec_price = price
    if order_type == "MARKET":
        quote = fetch_quote(symbol)
        # A fill needs a trustworthy provider time, not just a price.
        if (
            not quote
            or not quote.get("ltp")
            or not quote_is_fresh(quote.get("sourceTime"), utcnow())
        ):
            raise HTTPException(
                status_code=503,
                detail=f"No live price available for {symbol}, try again in a moment",
            )
        exec_price = quantize(decimal_from(quote["ltp"]), PRICE)

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

    now = utcnow()
    with session.begin():
        lock_user(session, user_id)

        if side == "SELL" and product != "MIS":
            # CNC sells need real holdings; MIS shorts are allowed.
            holding = session.scalar(
                select(Holding)
                .where(
                    Holding.user_id == user_id,
                    Holding.symbol == symbol,
                    Holding.exchange == exchange,
                )
                .with_for_update()
            )
            held_qty = holding.qty if holding is not None else 0
            if qty > held_qty:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient holdings: you hold {number_text(held_qty)} {symbol} "
                        f"but tried to sell {number_text(qty)}"
                    ),
                )
        else:
            # A BUY or an MIS order blocks cash. There is no funds upsert here,
            # matching Express: a user with no row has nothing to debit.
            amount = quantize(Decimal(qty) * exec_price, CASH)
            if debit_existing_funds(session, user_id, amount, now) is None:
                available = funds_available(session, user_id)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Insufficient funds: order needs "
                        f"₹{format_inr(amount)} but only "
                        f"₹{format_inr(available)} is available"
                    ),
                )

        order = Order(
            id=new_id(),
            user_id=user_id,
            symbol=symbol,
            name=name,
            exchange=exchange,
            side=side,
            type=order_type,
            product=product,
            qty=qty,
            filled=0,
            price=exec_price,
            trigger_price=trigger_price,
            sl_trigger=sl_trigger,
            tp_price=tp_price,
            group_id="",
            is_exit=False,
            status="OPEN",
            created_at=now,
            updated_at=now,
            version=0,
        )
        # A bracket entry anchors its own group; the exits copy this groupId.
        if sl_trigger > 0 or tp_price > 0:
            order.group_id = order.id
        session.add(order)
        session.flush()

        # MARKET orders fill now; limit orders wait for price sync.
        if order_type == "MARKET":
            fill_order(session, order, exec_price, now)
            session.flush()

        document = order_document(order)

    return to_json_value(document)


@router.post("/api/orders/exits", status_code=201)
def set_exits(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    symbol = body.get("symbol")
    exchange = body.get("exchange")
    product = body.get("product")
    sl_trigger = quantize(decimal_from(js_number_or_zero(body.get("slTrigger"))), PRICE)
    tp_price = quantize(decimal_from(js_number_or_zero(body.get("tpPrice"))), PRICE)

    if not symbol or not product:
        raise HTTPException(status_code=400, detail="symbol and product are required")
    if product not in PRODUCTS:
        raise HTTPException(status_code=400, detail="product must be CNC or MIS")
    if sl_trigger <= 0 and tp_price <= 0:
        raise HTTPException(
            status_code=400, detail="Set at least a stop-loss trigger or a target price"
        )
    if exchange is None:
        exchange = SUPPORTED_EXCHANGE
    if exchange != SUPPORTED_EXCHANGE:
        raise HTTPException(status_code=400, detail="Unsupported exchange")

    now = utcnow()
    with session.begin():
        lock_user(session, user_id)

        if product == "CNC":
            holding = session.scalar(
                select(Holding)
                .where(
                    Holding.user_id == user_id,
                    Holding.symbol == symbol,
                    Holding.exchange == exchange,
                )
                .with_for_update()
            )
            if holding is None:
                raise HTTPException(
                    status_code=404, detail=f"No holding found for {symbol}"
                )
            qty = holding.qty
            name = holding.name
            # A holding is always long — it exits by selling.
            side = "SELL"
            if sl_trigger > 0 and tp_price > 0 and sl_trigger >= tp_price:
                raise HTTPException(
                    status_code=400,
                    detail="Stop-loss trigger must be below the target price",
                )
        else:
            position = session.scalar(
                select(Position)
                .where(
                    Position.user_id == user_id,
                    Position.symbol == symbol,
                    Position.exchange == exchange,
                    Position.product == "MIS",
                )
                .order_by(Position.created_at.asc(), Position.id.asc())
                .limit(1)
                .with_for_update()
            )
            if position is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No open MIS position found for {symbol}",
                )
            qty = position.qty
            name = position.name
            side = "SELL" if position.side == "LONG" else "BUY"
            sl_below_tp = sl_trigger < tp_price
            long_needs_sl_below = (
                sl_below_tp if position.side == "LONG" else not sl_below_tp
            )
            if sl_trigger > 0 and tp_price > 0 and not long_needs_sl_below:
                message = (
                    "Stop-loss trigger must be below the target price for a long"
                    if position.side == "LONG"
                    else "Stop-loss trigger must be above the target price for a short"
                )
                raise HTTPException(status_code=400, detail=message)

        # Cancel the old exit pair first; only CNC BUY exits refund cash.
        old_query = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.symbol == symbol,
                Order.exchange == exchange,
                Order.product == product,
                Order.is_exit.is_(True),
                Order.status == "OPEN",
            )
            .with_for_update()
        )
        for old in session.scalars(old_query).all():
            old.status = "CANCELLED"
            old.updated_at = now
            refund_blocked_cash(session, old, now)

        # No entry order to anchor the group, so a fresh id plays that role.
        orders = create_exit_pair(
            session,
            user_id=user_id,
            symbol=symbol,
            name=name,
            exchange=exchange,
            product=product,
            qty=qty,
            side=side,
            sl_trigger=sl_trigger,
            tp_price=tp_price,
            group_id=str(uuid4()),
            now=now,
        )
        session.flush()
        documents = [order_document(order) for order in orders]

    return {
        "message": f"Exit rules set for {symbol}",
        "orders": to_json_value(documents),
    }


@router.delete("/api/orders/{order_id}")
def cancel_order(
    order_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    now = utcnow()
    with session.begin():
        lock_user(session, user_id)

        # Only OPEN orders match, so a just-filled order never refunds.
        order = session.scalar(
            select(Order)
            .where(
                Order.id == order_id,
                Order.user_id == user_id,
                Order.status == "OPEN",
            )
            .with_for_update()
        )
        if order is None:
            existing = session.scalar(
                select(Order).where(
                    Order.id == order_id, Order.user_id == user_id
                )
            )
            if existing is None:
                raise HTTPException(status_code=404, detail="Order not found")
            raise HTTPException(
                status_code=400,
                detail=f"Order is already {existing.status.lower()}",
            )

        order.status = "CANCELLED"
        order.updated_at = now
        refund_blocked_cash(session, order, now)
        document = order_document(order)

    return to_json_value(document)
