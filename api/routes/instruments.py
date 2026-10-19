"""Port of the instrument routes in server/routes/instrumentRoutes.js.

The Express routes are:
    router.get("/search", protect, async (req, res) => {
      // regex over the local MarketQuote cache; no Yahoo call
    });
    router.get("/:symbol/candles", protect, async (req, res) => {
      // Yahoo Finance chart(); see api/market_data.py
    });

The remaining instrument routes (`/lookup/:symbol`, `/:symbol`) read live
quotes and are deferred to the quote phase.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..market_data import MarketDataError, fetch_candles

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/instruments/search")
def search_instruments(
    q: str = "",
    user_id: str = Depends(require_user),
    db: Database = Depends(get_database),
):
    query = q.strip()
    if not query:
        return []

    # Escape user input so regex metacharacters match literally.
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    rows = list(
        db["marketquotes"].find({"$or": [{"symbol": pattern}, {"name": pattern}]}).limit(10)
    )

    # Field names are renamed for the client: price <- ltp, changePct <- dayChangePct.
    return [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "kind": row.get("kind"),
            "price": row.get("ltp"),
            "changePct": row.get("dayChangePct"),
        }
        for row in rows
    ]


@router.get("/api/instruments/{symbol}/candles")
def instrument_candles(
    symbol: str,
    # The client also sends `exchange`; Express ignores it, so this does too.
    chart_range: str = Query(default="1M", alias="range"),
    user_id: str = Depends(require_user),
):
    # Express wraps the whole handler in the router's error path: any failure,
    # including an unknown symbol, is a 404 with this one message. It logs the
    # provider message server-side and keeps it out of the response.
    try:
        return fetch_candles(symbol, chart_range)
    except MarketDataError as err:
        logger.error("Candle fetch failed for %s: %s", symbol, err)
        raise HTTPException(status_code=404, detail="Could not fetch candle data")
