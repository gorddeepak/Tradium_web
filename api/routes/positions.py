"""Port of server/routes/positionsRoutes.js, now backed by PostgreSQL.

The Express routes are:
    router.get("/", protect, ...)                    // GET /api/positions
    router.post("/:id/square-off", protect, ...)     // POST /api/positions/:id/square-off

Positions store no price: ``ltp`` is joined from ``latest_quotes``. Square-off
prefers a live provider quote and falls back to that canonical quote when the
provider is unavailable. The delete, cash credit, settlement, closing order and
exit cancellation all commit together.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..market_data import fetch_quote
from ..postgres.models import Instrument, LatestQuote, Order, Position, Transaction
from ..postgres.session import get_session
from ..serialization import to_json_value
from ..trading_book import (
    CASH,
    PRICE,
    adjust_funds,
    cancel_open_exits,
    decimal_from,
    lock_user,
    new_id,
    position_document,
    quantize,
    utcnow,
)

router = APIRouter()


@router.get("/api/positions")
def list_positions(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(Position, func.coalesce(LatestQuote.ltp, 0))
        .outerjoin(Instrument, Instrument.symbol == Position.symbol)
        .outerjoin(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Position.user_id == user_id)
        .order_by(Position.created_at.asc(), Position.id.asc())
    ).all()
    return [
        to_json_value(position_document(position, ltp))
        for position, ltp in rows
    ]


@router.post("/api/positions/{position_id}/square-off")
def square_off(
    position_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    # Read the position and the canonical quote before the write transaction;
    # the provider call must not hold locks.
    position = session.get(Position, position_id)
    if position is None or position.user_id != user_id:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.product != "MIS":
        raise HTTPException(
            status_code=400, detail="Only MIS positions can be squared off here"
        )

    symbol = position.symbol
    fallback_ltp = session.scalar(
        select(LatestQuote.ltp)
        .join(Instrument, Instrument.id == LatestQuote.instrument_id)
        .where(Instrument.symbol == symbol)
    )
    session.rollback()

    # A live quote if one is available; otherwise the canonical cached ltp.
    quote = fetch_quote(symbol)
    exit_price = None
    if quote and quote.get("ltp"):
        exit_price = quantize(decimal_from(quote["ltp"]), PRICE)
    elif fallback_ltp is not None:
        exit_price = quantize(fallback_ltp, PRICE)

    if exit_price is None or exit_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="No live price for this position yet — try again shortly",
        )

    now = utcnow()
    with session.begin():
        lock_user(session, user_id)

        claimed = session.execute(
            delete(Position)
            .where(Position.id == position_id, Position.user_id == user_id)
            .returning(Position)
        ).scalar_one_or_none()
        if claimed is None:
            raise HTTPException(status_code=404, detail="Position not found")
        if claimed.product != "MIS":
            raise HTTPException(
                status_code=400, detail="Only MIS positions can be squared off here"
            )

        # P&L per share: LONG is exit - entry, SHORT is entry - exit.
        direction = 1 if claimed.side == "LONG" else -1
        pnl = quantize(
            (exit_price - claimed.entry) * Decimal(claimed.qty) * direction, CASH
        )
        release = quantize(
            quantize(claimed.entry * Decimal(claimed.qty), CASH) + pnl, CASH
        )

        adjust_funds(session, user_id, release, now)

        # Book the realized P&L in the ledger.
        session.add(
            Transaction(
                id=new_id(),
                user_id=user_id,
                kind="SETTLEMENT",
                method=f"{claimed.symbol} MIS square-off",
                amount=pnl,
                symbol=claimed.symbol,
                status="COMPLETED",
                created_at=now,
                updated_at=now,
                version=0,
            )
        )

        # The closing trade shows up in the orders book, so history stays honest.
        session.add(
            Order(
                id=new_id(),
                user_id=user_id,
                symbol=claimed.symbol,
                name=claimed.name,
                exchange=claimed.exchange,
                side="SELL" if claimed.side == "LONG" else "BUY",
                type="MARKET",
                product="MIS",
                qty=claimed.qty,
                filled=claimed.qty,
                price=exit_price,
                trigger_price=Decimal("0.0000"),
                sl_trigger=Decimal("0.0000"),
                tp_price=Decimal("0.0000"),
                group_id="",
                is_exit=False,
                status="EXECUTED",
                created_at=now,
                updated_at=now,
                version=0,
            )
        )

        # Cancel any live exit pair so it can't fire after square-off.
        cancel_open_exits(
            session,
            user_id=user_id,
            symbol=claimed.symbol,
            exchange=claimed.exchange,
            product="MIS",
            now=now,
        )

    return {
        "message": f"Squared off {symbol}",
        "pnl": to_json_value(pnl),
    }
