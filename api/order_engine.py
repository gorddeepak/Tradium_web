"""Fill handling for the PostgreSQL trading book.

Port of ``server/utils/executeOrder.js`` with the Phase 3C2 transaction rules:
the caller locks the order row and owns the surrounding transaction, and this
module moves the book, settles MIS exits, finalises the order status and
cancels OCO siblings. Every function takes the same session, so a business
rejection rolls back with the rest of the flow.

Business validation happens before any book mutation. A rejection therefore
leaves the order's stored ``filled``/``price`` untouched and only changes its
status; the caller refunds blocked cash once, tied to that transition.
"""

from decimal import Decimal

from sqlalchemy import delete, select, update

from .postgres.models import Holding, Order, Position, Transaction
from .trading_book import (
    AVERAGE,
    CASH,
    PRICE,
    FillRejected,
    adjust_funds,
    blocks_cash,
    decimal_from,
    new_id,
    quantize,
    refund_blocked_cash,
)


def _transition(session, order, status, now, *, filled=None, price=None):
    """Final conditional status change; no row means an invariant violation."""
    values = {"status": status, "updated_at": now}
    if filled is not None:
        values["filled"] = filled
    if price is not None:
        values["price"] = price
    result = session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == "OPEN")
        .values(**values)
    )
    if result.rowcount != 1:
        raise RuntimeError(f"order {order.id} is no longer OPEN")

    order.status = status
    order.updated_at = now
    if filled is not None:
        order.filled = filled
    if price is not None:
        order.price = price


def _settlement(session, order, method, amount, now):
    session.add(
        Transaction(
            id=new_id(),
            user_id=order.user_id,
            kind="SETTLEMENT",
            method=method,
            amount=quantize(amount, CASH),
            symbol=order.symbol,
            status="COMPLETED",
            created_at=now,
            updated_at=now,
            version=0,
        )
    )


def apply_fill(session, order, fill_price, now):
    """Move the book for a locked OPEN order, or raise ``FillRejected``."""
    fill_price = quantize(decimal_from(fill_price), PRICE)

    # Validate the backing delivery quantity before any mutation. The row lock
    # makes the later decrement a compare-and-set with the earlier check.
    holding = None
    if order.product == "CNC" and order.side == "SELL":
        holding = session.scalar(
            select(Holding)
            .where(
                Holding.user_id == order.user_id,
                Holding.symbol == order.symbol,
                Holding.exchange == order.exchange,
            )
            .with_for_update()
        )
        if holding is None or holding.qty < order.qty:
            raise FillRejected("insufficient holding")

    # Bracket exits spawn only once the entry has actually filled.
    if not order.is_exit and (order.sl_trigger > 0 or order.tp_price > 0):
        spawn_bracket_exits(session, order, now)

    if order.product == "MIS":
        _merge_position(session, order, fill_price, now)
        return

    if order.side == "BUY":
        _merge_holding(session, order, fill_price, now)
        return

    # Delivery sell: the holding was locked and checked above.
    proceeds = quantize(Decimal(order.qty) * fill_price, CASH)
    pnl = quantize(
        (fill_price - holding.avg_price) * Decimal(order.qty), CASH
    )
    holding.qty -= order.qty
    holding.updated_at = now
    if holding.qty == 0:
        session.delete(holding)

    adjust_funds(session, order.user_id, proceeds, now)
    _settlement(session, order, f"{order.symbol} sell", pnl, now)


def _merge_holding(session, order, fill_price, now):
    holding = session.scalar(
        select(Holding)
        .where(
            Holding.user_id == order.user_id,
            Holding.symbol == order.symbol,
            Holding.exchange == order.exchange,
        )
        .with_for_update()
    )
    if holding is None:
        session.add(
            Holding(
                id=new_id(),
                user_id=order.user_id,
                symbol=order.symbol,
                name=order.name,
                exchange=order.exchange,
                qty=order.qty,
                avg_price=quantize(fill_price, AVERAGE),
                created_at=now,
                updated_at=now,
                version=0,
            )
        )
        return

    total = holding.qty + order.qty
    holding.avg_price = quantize(
        (holding.avg_price * Decimal(holding.qty) + fill_price * Decimal(order.qty))
        / Decimal(total),
        AVERAGE,
    )
    holding.qty = total
    holding.updated_at = now


def _merge_position(session, order, fill_price, now):
    side = "LONG" if order.side == "BUY" else "SHORT"
    position = session.scalar(
        select(Position)
        .where(
            Position.user_id == order.user_id,
            Position.symbol == order.symbol,
            Position.exchange == order.exchange,
            Position.product == "MIS",
            Position.side == side,
        )
        .with_for_update()
    )
    if position is None:
        session.add(
            Position(
                id=new_id(),
                user_id=order.user_id,
                symbol=order.symbol,
                name=order.name,
                exchange=order.exchange,
                side=side,
                product="MIS",
                qty=order.qty,
                entry=quantize(fill_price, AVERAGE),
                created_at=now,
                updated_at=now,
                version=0,
            )
        )
        return

    total = position.qty + order.qty
    position.entry = quantize(
        (position.entry * Decimal(position.qty) + fill_price * Decimal(order.qty))
        / Decimal(total),
        AVERAGE,
    )
    position.qty = total
    position.updated_at = now


def create_exit_pair(
    session,
    *,
    user_id,
    symbol,
    name,
    exchange,
    product,
    qty,
    side,
    sl_trigger,
    tp_price,
    group_id,
    now,
):
    """Build the SL and TP exit orders for a bracket or an exit request.

    Only a CNC BUY exit blocks cash; the debit is part of this transaction.
    """
    legs = []
    if sl_trigger > 0:
        legs.append(("SL-M", sl_trigger, sl_trigger))
    if tp_price > 0:
        legs.append(("LIMIT", tp_price, Decimal(0)))

    created = []
    for order_type, price, trigger in legs:
        price = quantize(price, PRICE)
        trigger = quantize(trigger, PRICE)
        if blocks_cash(is_exit=True, side=side, product=product):
            adjust_funds(
                session, user_id, -quantize(Decimal(qty) * price, CASH), now
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
            price=price,
            trigger_price=trigger,
            sl_trigger=Decimal("0.0000"),
            tp_price=Decimal("0.0000"),
            group_id=group_id,
            is_exit=True,
            status="OPEN",
            created_at=now,
            updated_at=now,
            version=0,
        )
        session.add(order)
        created.append(order)
    return created


def spawn_bracket_exits(session, entry, now):
    """A bracket entry just filled — spawn its exits with the opposite side."""
    return create_exit_pair(
        session,
        user_id=entry.user_id,
        symbol=entry.symbol,
        name=entry.name,
        exchange=entry.exchange,
        product=entry.product,
        qty=entry.qty,
        side="SELL" if entry.side == "BUY" else "BUY",
        sl_trigger=entry.sl_trigger,
        tp_price=entry.tp_price,
        group_id=entry.group_id,
        now=now,
    )


def settle_mis_exit(session, order, fill_price, now):
    """Move the book for an MIS exit; return settled, rejected or cancelled.

    The position row is locked by the caller's per-user lock and this select.
    An oversized exit is rejected rather than silently capped, and a partial
    exit keeps the remaining position instead of deleting it.
    """
    fill_price = quantize(decimal_from(fill_price), PRICE)
    position = session.scalar(
        select(Position)
        .where(
            Position.user_id == order.user_id,
            Position.symbol == order.symbol,
            Position.exchange == order.exchange,
            Position.product == "MIS",
            Position.side == ("LONG" if order.side == "SELL" else "SHORT"),
        )
        .with_for_update()
    )
    if position is None:
        return "cancelled"
    if order.qty > position.qty:
        return "rejected"

    direction = 1 if position.side == "LONG" else -1
    pnl = quantize(
        (fill_price - position.entry) * Decimal(order.qty) * direction, CASH
    )
    release = quantize(
        quantize(position.entry * Decimal(order.qty), CASH) + pnl, CASH
    )

    # A full exit must delete the row: the qty > 0 check constraint forbids
    # writing zero, so a decrement-to-zero is not a valid transition.
    if order.qty == position.qty:
        result = session.execute(
            delete(Position).where(
                Position.id == position.id, Position.qty == order.qty
            )
        )
        if result.rowcount != 1:
            return "rejected"
        session.expunge(position)
    else:
        remaining = session.execute(
            update(Position)
            .where(Position.id == position.id, Position.qty >= order.qty)
            .values(qty=Position.qty - order.qty, updated_at=now)
            .returning(Position.qty)
        ).scalar_one_or_none()
        if remaining is None:
            return "rejected"
        session.expire(position, ["qty"])

    adjust_funds(session, order.user_id, release, now)
    _settlement(session, order, f"{order.symbol} MIS exit", pnl, now)
    return "settled"


def cancel_sibling_exits(session, order, now):
    """OCO: one exit finished — cancel its still-open siblings and refund."""
    rows = session.execute(
        update(Order)
        .where(
            Order.user_id == order.user_id,
            Order.group_id == order.group_id,
            Order.is_exit.is_(True),
            Order.status == "OPEN",
            Order.id != order.id,
        )
        .values(status="CANCELLED", updated_at=now)
        .returning(Order)
    ).scalars().all()
    for sibling in rows:
        refund_blocked_cash(session, sibling, now)
    return rows


def fill_order(session, order, fill_price, now):
    """Settle a locked OPEN order, finalise its status and cancel siblings.

    The book moves first; only a settled fill adjusts an SL-M order's blocked
    cash from its stored price to the live fill price, so a rejected order is
    never adjusted and then refunded.
    """
    fill_price = quantize(decimal_from(fill_price), PRICE)

    if order.is_exit and order.product == "MIS":
        outcome = settle_mis_exit(session, order, fill_price, now)
    else:
        try:
            apply_fill(session, order, fill_price, now)
            outcome = "settled"
        except FillRejected:
            outcome = "rejected"

    if outcome == "settled":
        # The SL-M placement blocked the stored price, but the fill happened
        # at the live one. Adjust only once the fill is certain, so a rejected
        # order does not receive the adjustment and the refund on top.
        if (
            order.type == "SL-M"
            and blocks_cash(
                is_exit=order.is_exit, side=order.side, product=order.product
            )
            and order.price != fill_price
        ):
            blocked = quantize(Decimal(order.qty) * order.price, CASH)
            actual = quantize(Decimal(order.qty) * fill_price, CASH)
            adjust_funds(session, order.user_id, blocked - actual, now)

        _transition(
            session,
            order,
            "EXECUTED",
            now,
            filled=order.qty,
            price=fill_price,
        )
    elif outcome == "rejected":
        # The stored filled/price are deliberately left alone.
        _transition(session, order, "REJECTED", now)
        refund_blocked_cash(session, order, now)
    else:
        _transition(session, order, "CANCELLED", now)

    # Only an exit finishes an OCO group. A bracket entry anchors the group
    # and spawns its exits here; those must stay OPEN.
    if order.is_exit:
        cancel_sibling_exits(session, order, now)
    return outcome
