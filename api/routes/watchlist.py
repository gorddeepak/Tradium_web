"""Port of server/routes/watchlistRoutes.js.

The Express routes are:
    router.get("/", protect, ...)        // GET /api/watchlist
    router.post("/", protect, ...)       // POST /api/watchlist
    router.delete("/:id", protect, ...)  // DELETE /api/watchlist/:id

The collection is `watchlists` (Mongoose pluralises model("watchlist")).
"""

import re

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..documents import new_document
from ..serialization import to_json_value

router = APIRouter()

# ^ is allowed as a leading char for index tickers (^NSEI, ^BSESN).
SYMBOL_PATTERN = re.compile(r"[\^A-Z0-9&-]{1,20}")


@router.get("/api/watchlist")
def list_watchlist(
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    # The user field is stored as an ObjectId, so cast the token claim.
    user = ObjectId(user_id)
    items = list(db["watchlists"].find({"user": user}))
    return [to_json_value(item) for item in items]


@router.post("/api/watchlist", status_code=201)
def add_watchlist(
    body: dict = Body(default={}),
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    symbol = body.get("symbol")
    # Reject junk symbols: priceSync quotes every watchlist row, so junk burns
    # Yahoo calls. JS's RegExp.test coerces, so mirror that with str().
    if not symbol or not SYMBOL_PATTERN.fullmatch(str(symbol)):
        raise HTTPException(status_code=400, detail="Invalid symbol")

    user = ObjectId(user_id)
    # The duplicate check is not scoped by exchange, matching Express.
    if db["watchlists"].find_one({"user": user, "symbol": symbol}) is not None:
        raise HTTPException(status_code=409, detail="Already in watchlist")

    item = new_document(
        user=user,
        symbol=symbol,
        name=body.get("name"),
        exchange=body.get("exchange") if body.get("exchange") is not None else "NSE",
        ltp=0,
        dayChangePct=0,
    )
    db["watchlists"].insert_one(item)
    return to_json_value(item)


@router.delete("/api/watchlist/{item_id}", status_code=204)
def delete_watchlist(
    item_id: str,
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    user = ObjectId(user_id)
    # Always 204, even when nothing matched (matches Express).
    db["watchlists"].delete_one({"_id": ObjectId(item_id), "user": user})
    return Response(status_code=204)
