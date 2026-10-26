"""Port of server/routes/watchlistRoutes.js, now backed by PostgreSQL.

The Express routes are:
    router.get("/", protect, ...)        // GET /api/watchlist
    router.post("/", protect, ...)       // POST /api/watchlist
    router.delete("/:id", protect, ...)  // DELETE /api/watchlist/:id

Phase 3B3 moves the collection from MongoDB to the `watchlists` table. The
table stores no prices, so the read joins `instruments` and `latest_quotes`
to keep the legacy `ltp` / `dayChangePct` response fields. `price_sync` still
owns the quote cache.
"""

import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_user
from ..postgres.models import Instrument, LatestQuote, Watchlist
from ..postgres.session import get_session
from ..serialization import to_json_value

router = APIRouter()

# ^ is allowed as a leading char for index tickers (^NSEI, ^BSESN).
SYMBOL_PATTERN = re.compile(r"[\^A-Z0-9&-]{1,20}")

# Phase 2 is NSE-only for equity listings (design D21/F13).
SUPPORTED_EXCHANGE = "NSE"


def new_watchlist_id() -> str:
    """A 24-character lowercase hex id, the ObjectId-compatible external shape."""
    return secrets.token_hex(12)


def utcnow_ms() -> datetime:
    """Current UTC time truncated to the millisecond precision of the column."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def watchlist_item(item: Watchlist, ltp=0, day_change_pct=0) -> dict:
    """The legacy document shape, with quote fields supplied by the caller."""
    return {
        "_id": item.id,
        "user": item.user_id,
        "symbol": item.symbol,
        "name": item.name,
        "exchange": item.exchange,
        "ltp": to_json_value(ltp),
        "dayChangePct": to_json_value(day_change_pct),
        "createdAt": to_json_value(item.created_at),
        "updatedAt": to_json_value(item.updated_at),
        "__v": item.version,
    }


@router.get("/api/watchlist")
def list_watchlist(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(
            Watchlist,
            func.coalesce(LatestQuote.ltp, 0),
            func.coalesce(LatestQuote.day_change_pct, 0),
        )
        .outerjoin(Instrument, Instrument.symbol == Watchlist.symbol)
        .outerjoin(LatestQuote, LatestQuote.instrument_id == Instrument.id)
        .where(Watchlist.user_id == user_id)
        .order_by(Watchlist.created_at.asc(), Watchlist.id.asc())
    ).all()

    return [
        watchlist_item(item, ltp, day_change_pct)
        for item, ltp, day_change_pct in rows
    ]


@router.post("/api/watchlist", status_code=201)
def add_watchlist(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    symbol = body.get("symbol")
    # Reject junk symbols: priceSync quotes every watchlist row, so junk burns
    # Yahoo calls. JS's RegExp.test coerces, so mirror that with str().
    if not symbol or not SYMBOL_PATTERN.fullmatch(str(symbol)):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    # Mongoose's String type cast a numeric-looking symbol to text; do the same
    # so the column never receives a non-string bind.
    symbol = str(symbol)

    exchange = body.get("exchange")
    if exchange is None:
        exchange = SUPPORTED_EXCHANGE
    if exchange != SUPPORTED_EXCHANGE:
        raise HTTPException(status_code=400, detail="Unsupported exchange")

    # The duplicate check is not scoped by exchange, matching Express.
    if session.scalar(
        select(Watchlist.id).where(
            Watchlist.user_id == user_id, Watchlist.symbol == symbol
        )
    ) is not None:
        raise HTTPException(status_code=409, detail="Already in watchlist")

    # Mongoose allowed a missing name; the column is NOT NULL, so fall back to
    # the symbol (design F10).
    name = body.get("name")
    if not name:
        name = symbol

    now = utcnow_ms()
    item = Watchlist(
        id=new_watchlist_id(),
        user_id=user_id,
        symbol=symbol,
        name=str(name),
        exchange=exchange,
        created_at=now,
        updated_at=now,
        version=0,
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        # The pre-check above is only a fast path; the unique key closes the
        # race between two concurrent adds (design F12).
        if "uq_watchlists_user_symbol" in str(err.orig):
            raise HTTPException(status_code=409, detail="Already in watchlist")
        raise

    return watchlist_item(item)


@router.delete("/api/watchlist/{item_id}", status_code=204)
def delete_watchlist(
    item_id: str,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    # Always 204, even when nothing matched (matches Express and design D13):
    # text ids make a malformed id match no row instead of raising.
    session.execute(
        delete(Watchlist).where(
            Watchlist.id == item_id, Watchlist.user_id == user_id
        )
    )
    session.commit()
    return Response(status_code=204)
