"""Port of the instrument routes in server/routes/instrumentRoutes.js.

The Express routes are:
    router.get("/search", protect, ...);            // local cache, no Yahoo call
    router.get("/lookup/:symbol", protect, ...);    // live quote
    router.get("/:symbol", protect, ...);           // live quote, more fields
    router.get("/:symbol/candles", protect, ...);   // Yahoo chart()

Declaration order matters in Express: "/search" and "/lookup/:symbol" come
before "/:symbol", so "search" and "lookup" are never read as symbols. FastAPI
matches by path shape, so the same routes coexist without the ordering rule --
but the paths are registered in the same order to keep that obvious.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from ..auth import require_user
from ..db import get_database
from ..market_data import MarketDataError, fetch_candles, fetch_quote_row

router = APIRouter()
logger = logging.getLogger(__name__)

INSTRUMENT_NOT_FOUND = "Instrument not found"


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


def _omit_missing(document):
    """Drop keys with no value, the way ``JSON.stringify`` drops ``undefined``."""
    return {key: value for key, value in document.items() if value is not None}


@router.get("/api/instruments/lookup/{symbol}")
def lookup_instrument(
    symbol: str,
    # The client also sends `exchange`; Express ignores it, so this does too.
    user_id: str = Depends(require_user),
):
    # Express wraps the whole handler in `try { } catch { 404 }`, so a provider
    # failure and an unknown symbol answer identically.
    try:
        quote = fetch_quote_row(symbol)
        # `!quote?.regularMarketPrice` also rejects a zero price, so a symbol
        # with no trade is "not found" rather than a 200 full of zeros.
        if quote is None or not quote.get("regularMarketPrice"):
            raise HTTPException(status_code=404, detail=INSTRUMENT_NOT_FOUND)

        return _omit_missing(
            {
                "symbol": symbol.upper(),
                "name": quote.get("longName") or quote.get("shortName") or symbol,
                "exchange": "NSE",
                "price": quote.get("regularMarketPrice"),
                "change": quote.get("regularMarketChange"),
                "changePct": quote.get("regularMarketChangePercent"),
            }
        )
    except MarketDataError as err:
        logger.error("Quote fetch failed for %s: %s", symbol, err)
        raise HTTPException(status_code=404, detail=INSTRUMENT_NOT_FOUND)


@router.get("/api/instruments/{symbol}")
def instrument_detail(
    symbol: str,
    user_id: str = Depends(require_user),
):
    try:
        quote = fetch_quote_row(symbol)
        if quote is None or not quote.get("regularMarketPrice"):
            raise HTTPException(status_code=404, detail=INSTRUMENT_NOT_FOUND)

        return _omit_missing(
            {
                "symbol": symbol.upper(),
                "name": quote.get("longName") or quote.get("shortName") or symbol,
                "exchange": "NSE",
                "price": quote.get("regularMarketPrice"),
                "change": quote.get("regularMarketChange"),
                "changePct": quote.get("regularMarketChangePercent"),
                "open": quote.get("regularMarketOpen"),
                "high": quote.get("regularMarketDayHigh"),
                "low": quote.get("regularMarketDayLow"),
                "prevClose": quote.get("regularMarketPreviousClose"),
                "volume": quote.get("regularMarketVolume"),
                "week52High": quote.get("fiftyTwoWeekHigh"),
                "week52Low": quote.get("fiftyTwoWeekLow"),
            }
        )
    except MarketDataError as err:
        logger.error("Quote fetch failed for %s: %s", symbol, err)
        raise HTTPException(status_code=404, detail=INSTRUMENT_NOT_FOUND)


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
