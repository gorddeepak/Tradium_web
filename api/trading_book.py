"""Shared primitives for the PostgreSQL trading book.

Phase 3C2 moves funds, holdings, positions, orders and transactions off
MongoDB. Every financial write runs in one database transaction, serialized
per user by a transaction-scoped advisory lock, so a debit, a fill and an
order-status change can never diverge.

Money and prices are ``Decimal`` end to end. The quantizers below are the one
place that rounds: cash at 2 dp, prices at 4 dp, weighted averages at 6 dp,
always ``ROUND_HALF_UP`` and never on an intermediate per-share value.
"""

from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .portfolio_math import mis_components
from .postgres.models import (
    Fund,
    Holding,
    Instrument,
    LatestQuote,
    Order,
    Position,
    Transaction,
)
from .rows import new_id, utcnow

getcontext().prec = 28

CASH = Decimal("0.01")
PRICE = Decimal("0.0001")
AVERAGE = Decimal("0.000001")

# A fill needs the provider's own market time, not the receipt time. A missing,
# older-than-10-minutes or more-than-2-minutes-future source time means the
# order stays OPEN.
MAX_QUOTE_AGE = timedelta(minutes=10)
MAX_FUTURE_SKEW = timedelta(minutes=2)


class FillRejected(Exception):
    """A business reason the locked order cannot fill; caller marks REJECTED."""


def quantize(value, unit=CASH):
    """Round a value to a financial unit, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    result = value.quantize(unit, rounding=ROUND_HALF_UP)
    # A financial value should never render as "-0".
    return Decimal(0) if result == 0 else result


def decimal_from(value):
    """Convert a JSON/JS number or provider value to ``Decimal``."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def lock_user(session: Session, user_id: str):
    """Serialize every financial write for one user's transaction."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
        {"user_id": user_id},
    )


def quote_is_fresh(source_time, now):
    """True when a provider time may be used to fill an order."""
    if source_time is None:
        return False
    if source_time.tzinfo is None:
        source_time = source_time.replace(tzinfo=timezone.utc)
    age = now - source_time
    return -MAX_FUTURE_SKEW <= age <= MAX_QUOTE_AGE


def blocks_cash(*, is_exit, side, product):
    """The one cash-block predicate used by placement, cancel and refunds."""
    if is_exit:
        return side == "BUY" and product == "CNC"
    return side == "BUY" or product == "MIS"


def get_or_create_fund(session: Session, user_id: str, now):
    """Return the user's locked funds row, creating the zero row if absent."""
    session.execute(
        pg_insert(Fund)
        .values(
            id=new_id(),
            user_id=user_id,
            available=Decimal("0.00"),
            created_at=now,
            updated_at=now,
            version=0,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    return session.scalar(
        select(Fund).where(Fund.user_id == user_id).with_for_update()
    )


def adjust_funds(session: Session, user_id: str, amount, now):
    """Credit (or debit) a user's funds, creating the row when necessary."""
    fund = get_or_create_fund(session, user_id, now)
    fund.available = quantize(fund.available + decimal_from(amount), CASH)
    fund.updated_at = now
    return fund


def debit_existing_funds(session: Session, user_id: str, amount, now):
    """Guarded debit; ``None`` means the row is missing or cash is too low."""
    amount = quantize(amount, CASH)
    return session.execute(
        update(Fund)
        .where(Fund.user_id == user_id, Fund.available >= amount)
        .values(available=Fund.available - amount, updated_at=now)
        .returning(Fund)
    ).scalar_one_or_none()


def funds_available(session: Session, user_id: str):
    """The user's free cash, or zero when no row exists yet."""
    available = session.scalar(
        select(Fund.available).where(Fund.user_id == user_id)
    )
    return available if available is not None else Decimal("0.00")


def derived_fund_totals(session: Session, user_id: str):
    """The funds figures that are calculated from the rest of the book."""
    blocked_in_orders = session.scalar(
        select(
            func.coalesce(func.sum((Order.qty - Order.filled) * Order.price), 0)
        ).where(
            Order.user_id == user_id,
            Order.status == "OPEN",
            Order.is_exit.is_(False),
            or_(Order.side == "BUY", Order.product == "MIS"),
        )
    )
    mis_margin = session.scalar(
        select(func.coalesce(func.sum(Position.entry * Position.qty), 0)).where(
            Position.user_id == user_id,
            Position.product == "MIS",
        )
    )
    realized_pnl = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.kind == "SETTLEMENT",
        )
    )

    blocked_in_orders = quantize(blocked_in_orders, CASH)
    mis_margin = quantize(mis_margin, CASH)
    return {
        "blocked_in_orders": blocked_in_orders,
        "mis_margin": mis_margin,
        "used_margin": blocked_in_orders + mis_margin,
        "realized_pnl": quantize(realized_pnl, CASH),
    }


def holding_rows(session: Session, user_id: str):
    """The user's holdings with the cached quote, as legacy-shaped dicts.

    The book stores quantity and cost basis only; ``ltp`` and ``dayChangePct``
    come from ``latest_quotes``, so the reading code keeps the Mongoose field
    names without a second copy of the price. Values stay ``Decimal``; rows are
    in creation order, which is the order the Express ``find()`` returned.
    """
    rows = session.execute(
        select(
            Holding.symbol,
            Holding.name,
            Holding.exchange,
            Holding.qty,
            Holding.avg_price,
            func.coalesce(LatestQuote.ltp, 0),
            func.coalesce(LatestQuote.day_change_pct, 0),
        )
        .outerjoin(Instrument, Instrument.symbol == Holding.symbol)
        .outerjoin(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Holding.user_id == user_id)
        .order_by(Holding.created_at.asc(), Holding.id.asc())
    )

    return [
        {
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "qty": qty,
            "avgPrice": avg_price,
            "ltp": ltp,
            "dayChangePct": day_change_pct,
        }
        for symbol, name, exchange, qty, avg_price, ltp, day_change_pct in rows
    ]


def position_rows(session: Session, user_id: str, product=None):
    """The user's positions with the cached quote, as legacy-shaped dicts.

    ``product`` narrows the read to one product (``MIS`` for the margin and
    portfolio-value readers). A position stores no price, so ``ltp`` is joined
    from ``latest_quotes`` and is 0 when the symbol has no quote yet.
    """
    statement = (
        select(
            Position.symbol,
            Position.side,
            Position.product,
            Position.qty,
            Position.entry,
            func.coalesce(LatestQuote.ltp, 0),
        )
        .outerjoin(Instrument, Instrument.symbol == Position.symbol)
        .outerjoin(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Position.user_id == user_id)
        .order_by(Position.created_at.asc(), Position.id.asc())
    )
    if product is not None:
        statement = statement.where(Position.product == product)

    return [
        {
            "symbol": symbol,
            "side": side,
            "product": row_product,
            "qty": qty,
            "entry": entry,
            "ltp": ltp,
        }
        for symbol, side, row_product, qty, entry, ltp in session.execute(statement)
    ]


def portfolio_totals(session: Session, user_id: str):
    """Portfolio value and cost basis from PostgreSQL, as ``Decimal``.

    Returns ``(value, invested, mis_value, mis_invested)``: holdings plus the
    open MIS legs, which is the whole-account view the portfolio chart and the
    daily snapshot both show. ``/api/portfolio/history``'s live point and
    ``api/jobs/portfolio_snapshot.py`` call this, so the chart and the stored
    row can never disagree.
    """
    holdings = holding_rows(session, user_id)
    value = sum(
        (holding["qty"] * holding["ltp"] for holding in holdings), Decimal(0)
    )
    invested = sum(
        (holding["qty"] * holding["avgPrice"] for holding in holdings), Decimal(0)
    )

    mis_positions = position_rows(session, user_id, "MIS")
    mis_value, mis_invested = mis_components(mis_positions)
    return value, invested, mis_value, mis_invested


def refund_blocked_cash(session: Session, order: Order, now):
    """Credit back the unfilled part of an order that blocked cash."""
    if not blocks_cash(
        is_exit=order.is_exit, side=order.side, product=order.product
    ):
        return
    unfilled = order.qty - order.filled
    if unfilled <= 0:
        return
    adjust_funds(
        session, order.user_id, quantize(Decimal(unfilled) * order.price, CASH), now
    )


def cancel_open_exits(session: Session, *, user_id, symbol, exchange, product, now):
    """Cancel every OPEN exit for one book row and refund the blocking ones."""
    rows = session.execute(
        update(Order)
        .where(
            Order.user_id == user_id,
            Order.symbol == symbol,
            Order.exchange == exchange,
            Order.product == product,
            Order.is_exit.is_(True),
            Order.status == "OPEN",
        )
        .values(status="CANCELLED", updated_at=now)
        .returning(Order)
    ).scalars().all()
    for order in rows:
        refund_blocked_cash(session, order, now)
    return rows


def fund_document(fund: Fund):
    """Legacy Mongoose document shape for the funds response."""
    return {
        "_id": fund.id,
        "user": fund.user_id,
        "available": fund.available,
        "createdAt": fund.created_at,
        "updatedAt": fund.updated_at,
        "__v": fund.version,
    }


def holding_document(holding, ltp=0, day_change_pct=0, sector=""):
    return {
        "_id": holding.id,
        "user": holding.user_id,
        "symbol": holding.symbol,
        "name": holding.name,
        "exchange": holding.exchange,
        "qty": holding.qty,
        "avgPrice": holding.avg_price,
        "ltp": ltp,
        "dayChangePct": day_change_pct,
        "sector": sector,
        "createdAt": holding.created_at,
        "updatedAt": holding.updated_at,
        "__v": holding.version,
    }


def position_document(position, ltp=0):
    return {
        "_id": position.id,
        "user": position.user_id,
        "symbol": position.symbol,
        "name": position.name,
        "exchange": position.exchange,
        "side": position.side,
        "product": position.product,
        "qty": position.qty,
        "entry": position.entry,
        "ltp": ltp,
        "createdAt": position.created_at,
        "updatedAt": position.updated_at,
        "__v": position.version,
    }


def order_document(order: Order):
    return {
        "_id": order.id,
        "user": order.user_id,
        "symbol": order.symbol,
        "name": order.name,
        "exchange": order.exchange,
        "side": order.side,
        "type": order.type,
        "product": order.product,
        "qty": order.qty,
        "filled": order.filled,
        "price": order.price,
        "triggerPrice": order.trigger_price,
        "slTrigger": order.sl_trigger,
        "tpPrice": order.tp_price,
        "groupId": order.group_id,
        "isExit": order.is_exit,
        "status": order.status,
        "createdAt": order.created_at,
        "updatedAt": order.updated_at,
        "__v": order.version,
    }


def transaction_document(transaction):
    return {
        "_id": transaction.id,
        "user": transaction.user_id,
        "kind": transaction.kind,
        "method": transaction.method,
        "amount": transaction.amount,
        "symbol": transaction.symbol,
        "status": transaction.status,
        "createdAt": transaction.created_at,
        "updatedAt": transaction.updated_at,
        "__v": transaction.version,
    }
