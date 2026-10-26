"""Port of server/jobs/priceSync.js.

Every scheduled tick refreshes the stored prices of everything a user can see
(holdings, positions, watchlist), backfills a missing holding sector, then
matches OPEN limit/stop orders against those quotes and fills the crossed ones.

Two behaviours are load-bearing and were read off the Express source rather
than inferred:

- **No gate on the order side.** ``syncPrices`` returns early when the market is
  closed, so an OPEN limit order simply waits for the next open session. There
  is no separate "market hours" check around the fill loop.
- **The claim is the race guard.** An order is only filled if
  ``find_one_and_update({_id, status: "OPEN"})`` still matches, so a cancel that
  lands between the quote fetch and the fill wins.

``slTrigger``/``tpPrice`` brackets are spawned by ``apply_fill`` when an entry
fills, exactly as the orders route does. MIS exits go through ``settle_mis_exit``
instead, and every filled exit cancels its still-open siblings (OCO).

The provider is called once for the whole batch of distinct symbols. No test
touches the network: the seam is patched.
"""

import logging
import math
import threading

from pymongo import ReturnDocument

from ..documents import inc_funds, utcnow
from ..market_data import MarketDataError, fetch_quotes, fetch_sector, ticker_for
from ..market_hours import is_market_open
from ..market_store import (
    backfill_sectors as backfill_instrument_sectors,
    instrument_sectors,
    persist_price_quotes,
)
from ..order_engine import apply_fill, cancel_sibling_exits, settle_mis_exit

logger = logging.getLogger(__name__)

# Single-flight guard, the equivalent of the Express `isSyncing` flag. Per
# process; the scheduler is the only caller and runs on one thread.
_sync_lock = threading.Lock()


def _quote_from_row(row):
    """Reduce a raw Yahoo row to ``{"ltp", "dayChangePct"}``, or ``None``.

    Mirrors ``fetch_quote``'s validation: a missing, zero, negative or
    non-numeric price means "no usable quote", and a bad percentage becomes 0.
    """
    price = row.get("regularMarketPrice")
    if not _is_usable_number(price) or price <= 0:
        return None

    change_pct = row.get("regularMarketChangePercent")
    if not _is_usable_number(change_pct):
        change_pct = 0
    return {"ltp": price, "dayChangePct": change_pct}


def _is_usable_number(value):
    """True for a real number, excluding ``bool`` and ``NaN``/``inf``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def sync_prices(db, session_factory=None):
    """One scheduled tick, gated on market hours, like ``syncPrices()``."""
    # Yahoo quotes don't move while the market is closed, so syncing is wasted
    # calls. Open limit orders wait for the next open market.
    if not is_market_open():
        return

    if not _sync_lock.acquire(blocking=False):
        logger.info("Price sync still running, skipping this tick")
        return

    try:
        run_sync(db, session_factory)
    except Exception:  # noqa: BLE001 - an unhandled error would kill the thread
        logger.exception("Price sync failed")
    finally:
        _sync_lock.release()


def run_sync(db, session_factory=None):
    """One full price/fill cycle. Exposed separately so tests can skip the gate.

    When a PostgreSQL session factory is supplied, the canonical quote state is
    refreshed too. The book/order path stays MongoDB-backed and keeps using the
    in-memory provider batch, so fills do not depend on that write succeeding.
    """
    holdings = list(db["holdings"].find({}))
    positions = list(db["positions"].find({}))
    watchlist = list(db["watchlists"].find({}))
    # Open limit orders need quotes so they can fill.
    open_orders = list(db["orders"].find({"status": "OPEN"}))

    # One quote per symbol+exchange, in first-seen order (holdings, positions,
    # watchlist, open orders), exactly like the Express Map.
    symbols = {}
    names = {}
    for document in [*holdings, *positions, *watchlist, *open_orders]:
        key = f"{document['symbol']}-{document['exchange']}"
        symbols[key] = {"symbol": document["symbol"], "exchange": document["exchange"]}
        names.setdefault(document["symbol"], document.get("name") or document["symbol"])

    # One batched request for every distinct Yahoo ticker. A provider failure
    # leaves the stored prices alone, just as a per-symbol failure did.
    tickers = list(dict.fromkeys(ticker_for(item["symbol"]) for item in symbols.values()))
    rows = {}
    if tickers:
        try:
            rows = fetch_quotes(tickers)
        except MarketDataError as err:
            logger.error("Price fetch failed, keeping stored prices: %s", err)

    quotes = {}
    for key, item in symbols.items():
        ticker = ticker_for(item["symbol"])
        row = rows.get(ticker)
        if row is None:
            continue
        quote = _quote_from_row(row)
        if quote is None:
            logger.error("No price returned for %s, skipping", ticker)
            continue
        quotes[key] = quote

    # The canonical PostgreSQL quote is written from the same provider batch.
    # A persistence failure must not stop the MongoDB price/fill cycle.
    if session_factory is not None and quotes:
        entries = []
        for key, item in symbols.items():
            if key not in quotes:
                continue
            ticker = ticker_for(item["symbol"])
            row = rows.get(ticker)
            if row is None:
                continue
            entries.append(
                {
                    "symbol": item["symbol"],
                    "name": names.get(item["symbol"], item["symbol"]),
                    "kind": "stock",
                    "row": row,
                }
            )
        try:
            persist_price_quotes(session_factory, entries)
        except Exception:  # noqa: BLE001 - Mongo book updates still proceed
            logger.exception("PostgreSQL quote persistence failed")

    for holding in holdings:
        quote = quotes.get(f"{holding['symbol']}-{holding['exchange']}")
        if not quote:
            continue
        db["holdings"].update_one(
            {"_id": holding["_id"]},
            {
                "$set": {
                    "ltp": quote["ltp"],
                    "dayChangePct": quote["dayChangePct"],
                    "updatedAt": utcnow(),
                }
            },
        )

    for position in positions:
        quote = quotes.get(f"{position['symbol']}-{position['exchange']}")
        if not quote:
            continue
        db["positions"].update_one(
            {"_id": position["_id"]},
            {"$set": {"ltp": quote["ltp"], "updatedAt": utcnow()}},
        )

    for item in watchlist:
        quote = quotes.get(f"{item['symbol']}-{item['exchange']}")
        if not quote:
            continue
        db["watchlists"].update_one(
            {"_id": item["_id"]},
            {
                "$set": {
                    "ltp": quote["ltp"],
                    "dayChangePct": quote["dayChangePct"],
                    "updatedAt": utcnow(),
                }
            },
        )

    # Sectors live on PostgreSQL instruments now. This call is slow and only
    # runs for stocks without one. Holdings still display a stored Mongo
    # sector until that collection migrates, so the resolved value is mirrored
    # onto an empty holding as a temporary read projection.
    if session_factory is not None:
        try:
            sectors_filled = backfill_instrument_sectors(
                session_factory, fetch_sector
            )
            if sectors_filled:
                logger.info(
                    "Sector backfill: %s instruments updated", sectors_filled
                )

            sectors = instrument_sectors(
                session_factory, [holding["symbol"] for holding in holdings]
            )
            for holding in holdings:
                if holding.get("sector"):
                    continue
                sector = sectors.get(holding["symbol"])
                if not sector:
                    continue
                db["holdings"].update_one(
                    {"_id": holding["_id"], "sector": ""},
                    {"$set": {"sector": sector, "updatedAt": utcnow()}},
                )
        except Exception:  # noqa: BLE001 - sector metadata is not a fill blocker
            logger.exception("PostgreSQL sector backfill failed")

    filled_count = 0
    for order in open_orders:
        try:
            quote = quotes.get(f"{order['symbol']}-{order['exchange']}")
            if not quote or not quote.get("ltp"):
                continue

            if order["type"] in ("SL", "SL-M"):
                crossed = (
                    quote["ltp"] >= order["triggerPrice"]
                    if order["side"] == "BUY"
                    else quote["ltp"] <= order["triggerPrice"]
                )
            else:
                crossed = (
                    quote["ltp"] <= order["price"]
                    if order["side"] == "BUY"
                    else quote["ltp"] >= order["price"]
                )
            if not crossed:
                continue

            # SL-M fills at the live market price, not the trigger price.
            fill_price = quote["ltp"] if order["type"] == "SL-M" else order["price"]

            # Only grab the order if it is still OPEN.
            claimed = db["orders"].find_one_and_update(
                {"_id": order["_id"], "status": "OPEN"},
                {
                    "$set": {
                        "status": "EXECUTED",
                        "filled": order["qty"],
                        "price": fill_price,
                        "updatedAt": utcnow(),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if claimed is None:
                continue

            # Fix the blocked cash if SL-M filled at a different price.
            if order["type"] == "SL-M" and order["price"] != fill_price:
                if not order.get("isExit") and (
                    order["side"] == "BUY" or order["product"] == "MIS"
                ):
                    inc_funds(
                        db,
                        order["user"],
                        (order["price"] - fill_price) * order["qty"],
                    )

            # MIS exits close a position (and cancel their sibling, OCO);
            # others are normal fills.
            if claimed.get("isExit") and claimed["product"] == "MIS":
                settle_mis_exit(db, claimed)
            else:
                apply_fill(db, claimed)
            if claimed.get("isExit"):
                cancel_sibling_exits(db, claimed)

            filled_count += 1
        except Exception:  # noqa: BLE001 - one bad order shouldn't stop the rest
            logger.exception("Fill failed for order %s", order["_id"])

    if filled_count > 0:
        logger.info("Limit fills: %s order(s) executed", filled_count)

    logger.info("Price sync complete: %s symbols updated", len(quotes))
