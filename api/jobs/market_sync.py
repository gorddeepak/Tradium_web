"""Port of server/jobs/marketSync.js, persisted in PostgreSQL.

Refreshes the shared market cache from one batched Yahoo quote request, then
fills in sectors a few at a time.

Two details are load-bearing and were observed rather than assumed:

- Quote sync never writes ``sector``. The backfill owns that field, so a price
  cycle must not blank it. The instrument upsert therefore leaves sector alone.
- A quote without a usable price never overwrites the stored quote. Provider
  failures leave the last good cache untouched: stale prices beat an empty
  Markets page.

``updated_at`` is the quote receipt time; ``source_time`` is the provider's
market time and stays ``NULL`` when Yahoo does not send one.
"""

import logging
import threading

from ..data.nifty50 import INDICES, NIFTY50
from ..market_data import MarketDataError, fetch_quotes, fetch_sector
from ..market_hours import is_market_open
from ..market_store import (
    backfill_sectors as backfill_instrument_sectors,
    count_market_quotes,
    is_usable_quote,
    persist_market_quotes,
)
from ..postgres.session import get_session_factory

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


def sync_quotes(session_factory):
    """One batched request for all 53 symbols, then a PostgreSQL upsert.

    Returns ``(cached, missing)``. ``cached`` counts usable quotes written;
    ``missing`` lists tickers Yahoo did not return. A provider failure is
    logged and returns ``(0, [])`` after leaving the cache untouched.
    """
    try:
        quotes = fetch_quotes(TICKERS)
    except MarketDataError as err:
        logger.error("Market sync failed, keeping previous cache: %s", err)
        return 0, []

    entries = []
    for ticker, instrument in BY_TICKER.items():
        entries.append(
            {
                "symbol": instrument["symbol"],
                "name": instrument["name"],
                "kind": instrument["kind"],
                "row": quotes.get(ticker),
            }
        )

    cached = persist_market_quotes(session_factory, entries)
    missing = [ticker for ticker in TICKERS if ticker not in quotes]
    unusable = [
        BY_TICKER[ticker]["symbol"]
        for ticker in TICKERS
        if ticker in quotes and not is_usable_quote(quotes[ticker])
    ]

    logger.info("Market sync: %s/%s symbols cached", cached, len(TICKERS))
    if unusable:
        logger.warning("Market sync: no usable price for %s", ", ".join(unusable))
    if missing:
        # Likely dead tickers after renames or demergers.
        logger.warning("Market sync: no quote for %s", ", ".join(missing))

    return cached, missing


def backfill_sectors(session_factory):
    """Resolve up to SECTORS_PER_RUN missing instrument sectors.

    A stock's sector never changes, so this is outside the price cycle. A
    symbol Yahoo has no profile for is left empty and retried on a later run.
    """
    return backfill_instrument_sectors(
        session_factory, fetch_sector, limit=SECTORS_PER_RUN
    )


def market_sync(session_factory=None):
    """One scheduled tick: quote refresh (when it makes sense) plus backfill.

    Syncs only while the market is open, or when the cache is empty, so a cold
    start still populates the page. Errors are caught here because the
    scheduler ignores the return value, exactly as node-cron does.
    """
    if not _sync_lock.acquire(blocking=False):
        return  # previous run still going

    try:
        factory = session_factory or get_session_factory()
        with factory() as session:
            cached = count_market_quotes(session)

        if is_market_open() or cached == 0:
            sync_quotes(factory)

        backfill_sectors(factory)
    except Exception:  # noqa: BLE001 - a job must never take the process down
        logger.exception("Market sync failed")
    finally:
        _sync_lock.release()
