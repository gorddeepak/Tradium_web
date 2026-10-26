"""Port of server/jobs/priceSync.js, now backed by PostgreSQL.

Every scheduled tick refreshes the canonical quote cache, backfills missing
instrument sectors, then matches OPEN limit/stop orders against those quotes
and fills the crossed ones.

The fill rules come from ``POSTGRES_SCHEMA_DESIGN.md`` §6.4:

- The quote must carry a trustworthy provider ``source_time``. Missing, older
  than ten minutes, or more than two minutes future means "skip this order";
  the order stays OPEN.
- Each fill is its own transaction with the per-user advisory lock and a
  ``FOR UPDATE`` order lock. A cancel that wins the lock first leaves the order
  non-OPEN, so the fill cannot also settle it.
- One bad order rolls back only that order; the rest of the batch continues.
"""

import logging
import math
import threading

from sqlalchemy import select

from ..market_data import MarketDataError, fetch_quotes, fetch_sector, ticker_for
from ..market_hours import is_market_open
from ..market_store import (
    backfill_sectors as backfill_instrument_sectors,
    persist_price_quotes,
)
from ..order_engine import fill_order
from ..postgres.models import (
    Holding,
    Instrument,
    LatestQuote,
    Order,
    Position,
    Watchlist,
)
from ..trading_book import lock_user, quote_is_fresh, utcnow
from ..watchlist_stream import publish_persisted_quotes

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


def sync_prices(session_factory):
    """One scheduled tick, gated on market hours, like ``syncPrices()``."""
    # Yahoo quotes don't move while the market is closed, so syncing is wasted
    # calls. Open limit orders wait for the next open market.
    if not is_market_open():
        return

    if not _sync_lock.acquire(blocking=False):
        logger.info("Price sync still running, skipping this tick")
        return

    try:
        run_sync(session_factory)
    except Exception:  # noqa: BLE001 - an unhandled error would kill the thread
        logger.exception("Price sync failed")
    finally:
        _sync_lock.release()


def _watchlists(session_factory):
    with session_factory() as session:
        return session.scalars(
            select(Watchlist).order_by(Watchlist.created_at.asc(), Watchlist.id.asc())
        ).all()


def run_sync(session_factory, *, now=None):
    """One full quote/fill cycle. Exposed separately so tests can skip the gate.

    The provider call happens outside every transaction. Quotes are persisted
    in their own transaction, then each crossed order fills in its own
    transaction from the canonical cache.
    """
    clock = (lambda: now) if now is not None else utcnow

    with session_factory() as session:
        holdings = session.scalars(select(Holding)).all()
        positions = session.scalars(select(Position)).all()
        open_orders = session.scalars(
            select(Order).where(Order.status == "OPEN")
        ).all()

    try:
        watchlist = _watchlists(session_factory)
    except Exception:  # noqa: BLE001 - book prices and fills still proceed
        logger.exception("PostgreSQL watchlist read failed; skipping it")
        watchlist = []

    # One quote per symbol+exchange, in first-seen order (holdings, positions,
    # watchlist, open orders), exactly like the Express Map.
    symbols = {}
    names = {}
    for document in [*holdings, *positions, *watchlist, *open_orders]:
        key = f"{document.symbol}-{document.exchange}"
        symbols[key] = {"symbol": document.symbol, "exchange": document.exchange}
        names.setdefault(document.symbol, document.name or document.symbol)

    # One batched request for every distinct Yahoo ticker. A provider failure
    # leaves the stored quotes alone, just as a per-symbol failure did.
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

    # The canonical quote cache is written from the same provider batch. A
    # persistence failure must not stop the rest of the tick.
    if quotes:
        entries = [
            {
                "symbol": item["symbol"],
                "name": names.get(item["symbol"], item["symbol"]),
                "kind": "stock",
                "row": rows[ticker_for(item["symbol"])],
            }
            for key, item in symbols.items()
            if key in quotes
        ]
        try:
            persisted = persist_price_quotes(session_factory, entries, now=clock())
        except Exception:  # noqa: BLE001 - fills still use the existing cache
            persisted = 0
            logger.exception("PostgreSQL quote persistence failed")
        if persisted:
            # Push only after the commit, so a subscriber never sees a price
            # that is not in latest_quotes. Best-effort: the job continues even
            # if no socket or no database read is available.
            publish_persisted_quotes(
                session_factory,
                [entry["symbol"] for entry in entries],
            )

    # Sectors live on PostgreSQL instruments now; holdings/positions read them
    # through the join, so there is no book row to mirror.
    try:
        sectors_filled = backfill_instrument_sectors(session_factory, fetch_sector)
        if sectors_filled:
            logger.info("Sector backfill: %s instruments updated", sectors_filled)
    except Exception:  # noqa: BLE001 - sector metadata is not a fill blocker
        logger.exception("PostgreSQL sector backfill failed")

    filled_count = 0
    for open_order in open_orders:
        try:
            with session_factory() as session:
                with session.begin():
                    lock_user(session, open_order.user_id)
                    order = session.get(
                        Order,
                        open_order.id,
                        with_for_update=True,
                        populate_existing=True,
                    )
                    if order is None or order.status != "OPEN":
                        continue

                    quote = session.scalar(
                        select(LatestQuote)
                        .join(
                            Instrument,
                            Instrument.id == LatestQuote.instrument_id,
                        )
                        .where(Instrument.symbol == order.symbol)
                    )
                    if quote is None or quote.ltp <= 0:
                        continue
                    moment = clock()
                    if not quote_is_fresh(quote.source_time, moment):
                        logger.warning(
                            "Skipping fill for %s: quote source_time is missing or stale",
                            order.symbol,
                        )
                        continue

                    if order.type in ("SL", "SL-M"):
                        crossed = (
                            quote.ltp >= order.trigger_price
                            if order.side == "BUY"
                            else quote.ltp <= order.trigger_price
                        )
                    else:
                        crossed = (
                            quote.ltp <= order.price
                            if order.side == "BUY"
                            else quote.ltp >= order.price
                        )
                    if not crossed:
                        continue

                    # SL-M fills at the live market price, not the trigger.
                    fill_price = quote.ltp if order.type == "SL-M" else order.price
                    fill_order(session, order, fill_price, moment)
                    filled_count += 1
        except Exception:  # noqa: BLE001 - one bad order shouldn't stop the rest
            logger.exception("Fill failed for order %s", open_order.id)

    if filled_count > 0:
        logger.info("Limit fills: %s order(s) executed", filled_count)

    logger.info("Price sync complete: %s symbols updated", len(quotes))
