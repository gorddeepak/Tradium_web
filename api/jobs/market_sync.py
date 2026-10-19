"""Port of server/jobs/marketSync.js.

Refreshes the shared ``marketquotes`` cache from one batched Yahoo quote
request, then fills in sectors a few at a time.

Two details are load-bearing and were observed rather than assumed:

- ``syncQuotes`` never writes ``sector``. The backfill owns that field, so a
  price cycle must not blank it. The upsert therefore puts ``sector`` in
  ``$setOnInsert``, which is exactly what Mongoose's ``bulkWrite`` generated.
- ``backfillSectors`` writes with ``doc.save()``, which refreshes ``updatedAt``
  and leaves ``__v`` alone. Mongoose's upsert does the same, so both paths are
  reproduced through ``documents.utcnow()``.

The job keeps the last good cache on a provider failure: stale prices beat an
empty Markets page.
"""

import logging
import threading

from pymongo import UpdateOne

from ..data.nifty50 import INDICES, NIFTY50
from ..documents import utcnow
from ..market_data import MarketDataError, fetch_quotes, fetch_sector
from ..market_hours import is_market_open

logger = logging.getLogger(__name__)

# Only a few sectors resolve per run -- quoteSummary is one call per symbol.
SECTORS_PER_RUN = 10

# Yahoo ticker -> our row. Indices keep Yahoo's own ticker ("^NSEI"), stocks get
# ".NS". Built once, in declaration order, exactly like the Express module.
BY_TICKER = {}
for _symbol, _name in INDICES:
    BY_TICKER[_symbol] = {"symbol": _symbol, "name": _name, "kind": "index"}
for _symbol, _name in NIFTY50:
    BY_TICKER[f"{_symbol}.NS"] = {"symbol": _symbol, "name": _name, "kind": "stock"}

TICKERS = list(BY_TICKER)

# Single-flight guard, the equivalent of the Express `isSyncing` flag. It is
# per process; see `docs/migration/MIGRATION_STATUS.md` §3I for why that is
# enough here and what it does not cover.
_sync_lock = threading.Lock()


def _quote_value(row, field):
    """``q.field ?? 0`` -- null/absent becomes 0, and 0 stays 0."""
    value = row.get(field)
    return 0 if value is None else value


def quote_operations(quotes):
    """Build the bulk upserts for a ``{ticker: quote_row}`` batch.

    Returns ``(operations, seen)``. Pure, so the field mapping and the
    ``sector``-preserving ``$setOnInsert`` can be asserted without a database.
    """
    operations = []
    seen = set()
    # One timestamp for the batch, as Mongoose's timestamping does for a
    # synchronous bulkWrite.
    now = utcnow()

    for ticker, quote in quotes.items():
        row = BY_TICKER.get(ticker)
        if row is None:
            continue  # Yahoo echoed something we did not ask for
        seen.add(ticker)

        operations.append(
            UpdateOne(
                {"symbol": row["symbol"]},
                {
                    # `sector` is left alone here -- the backfill below owns it.
                    "$set": {
                        "name": row["name"],
                        "kind": row["kind"],
                        "ltp": _quote_value(quote, "regularMarketPrice"),
                        "dayChange": _quote_value(quote, "regularMarketChange"),
                        "dayChangePct": _quote_value(quote, "regularMarketChangePercent"),
                        "prevClose": _quote_value(quote, "regularMarketPreviousClose"),
                        "volume": _quote_value(quote, "regularMarketVolume"),
                        "marketCap": _quote_value(quote, "marketCap"),
                        "updatedAt": now,
                    },
                    # Mongoose's upsert supplies the model defaults and createdAt
                    # on insert only.
                    "$setOnInsert": {"createdAt": now, "sector": "", "__v": 0},
                },
                upsert=True,
            )
        )

    return operations, seen


def sync_quotes(db):
    """One batched request for all 53 symbols, then a bulk upsert.

    Returns ``(cached, missing)``. A provider failure is logged and returns
    ``(0, [])`` after leaving the cache untouched.
    """
    try:
        quotes = fetch_quotes(TICKERS)
    except MarketDataError as err:
        logger.error("Market sync failed, keeping previous cache: %s", err)
        return 0, []

    operations, seen = quote_operations(quotes)
    if operations:
        # Ordered, like Mongoose's default bulkWrite.
        db["marketquotes"].bulk_write(operations)

    missing = [ticker for ticker in TICKERS if ticker not in seen]
    logger.info("Market sync: %s/%s symbols cached", len(operations), len(TICKERS))
    if missing:
        # Likely dead tickers after renames or demergers.
        logger.warning("Market sync: no quote for %s", ", ".join(missing))

    return len(operations), missing


def backfill_sectors(db):
    """Resolve up to SECTORS_PER_RUN missing sectors.

    A stock's sector never changes, so this is outside the price cycle. A
    symbol Yahoo has no profile for is left empty and retried on a later run,
    which matches the Express loop's ``if (!sector) continue;``.
    """
    pending = list(db["marketquotes"].find({"kind": "stock", "sector": ""}).limit(SECTORS_PER_RUN))
    if not pending:
        return 0

    filled = 0
    for document in pending:
        try:
            sector = fetch_sector(document["symbol"])
        except MarketDataError as err:
            # Express's fetchSector catches its own failure and returns "";
            # here the error surfaces, so it is logged and treated the same.
            logger.error("Sector fetch failed for %s: %s", document["symbol"], err)
            continue
        if not sector:
            continue

        db["marketquotes"].update_one(
            {"_id": document["_id"]},
            {"$set": {"sector": sector, "updatedAt": utcnow()}},
        )
        filled += 1

    if filled:
        logger.info("Market sync: %s sectors resolved", filled)
    return filled


def market_sync(db):
    """One scheduled tick: quote refresh (when it makes sense) plus backfill.

    Syncs only while the market is open, or when the cache is empty, so a cold
    start still populates the page. Errors are caught here because the
    scheduler ignores the return value, exactly as node-cron does.
    """
    if not _sync_lock.acquire(blocking=False):
        return  # previous run still going

    try:
        cached = db["marketquotes"].estimated_document_count()

        if is_market_open() or cached == 0:
            sync_quotes(db)

        backfill_sectors(db)
    except Exception:  # noqa: BLE001 - a job must never take the process down
        logger.exception("Market sync failed")
    finally:
        _sync_lock.release()
