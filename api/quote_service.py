"""The live quote service: upstream feed -> cache -> browser, plus persistence.

One instance per FastAPI process (``quote_service`` at the bottom). It owns:

- the upstream Yahoo connection, on its own thread and event loop;
- the shared in-memory cache (``api/quote_cache.py``);
- immediate browser delivery through the generic quote hub;
- a coalesced ``latest_quotes`` write every ``LIVE_QUOTES_FLUSH_SECONDS``.

Ordering matters and is deliberate:

1. The cache is updated and the frame is published **before** PostgreSQL. A
   browser can therefore see a tick the database has not received yet; that is
   the point of the cache. The frame says ``live: true`` and ``receivedAt`` is
   the receipt time.
2. The database write is batched, keeps only the newest tick per symbol, and on
   failure leaves the pending entry in place for the next flush. A failed write
   is never reported as a successful one.
3. A value restored from ``latest_quotes`` is ``live: false`` and has no
   ``receivedAt``: it is the last persisted quote, not a tick.

The scheduled REST sync stays the fallback. When the feed is connected the
jobs stop publishing polling frames, so a slower poll cannot overwrite a
newer streamed price in the browser.
"""

import asyncio
import logging
import threading

from sqlalchemy import select

from .config import (
    live_quotes_enabled,
    live_quotes_flush_seconds,
    live_quotes_stale_seconds,
)
from .data.nifty50 import INDICES, NIFTY50
from .market_data import ticker_for
from .market_store import persist_price_quotes, provider_source_time
from .postgres.models import Instrument, LatestQuote
from .quote_cache import MAX_FUTURE_SKEW_SECONDS, QuoteCache, is_stale
from .quote_feed import YahooQuoteFeed
from .quote_stream import hub as default_hub
from .rows import utcnow
from .serialization import to_json_value
from .watchlist_stream import publish_persisted_quotes

logger = logging.getLogger(__name__)


def universe_tickers():
    """The 53 Yahoo tickers the REST market cache also covers.

    Book-only instruments outside this list have no live subscription. They
    keep updating through the existing REST sync, which is the documented
    symbol-coverage limit.
    """
    symbols = [symbol for symbol, _name in INDICES]
    symbols.extend(symbol for symbol, _name in NIFTY50)
    return [ticker_for(symbol) for symbol in symbols]


def app_symbol(ticker):
    """Map a provider ticker back to the app's symbol (``INFY.NS`` -> ``INFY``)."""
    text = str(ticker or "").strip()
    if not text:
        return ""
    if text.startswith("^"):
        return text
    if text.endswith(".NS"):
        return text[:-3]
    return text


class QuoteService:
    """Ties the feed, cache, persistence and WebSocket delivery together."""

    def __init__(
        self,
        *,
        cache=None,
        hub=None,
        session_factory=None,
        flush_seconds=None,
        stale_seconds=None,
        feed_factory=None,
        clock=None,
    ):
        self.cache = cache if cache is not None else QuoteCache()
        self.hub = hub if hub is not None else default_hub
        self._session_factory = session_factory
        self.flush_seconds = (
            flush_seconds if flush_seconds is not None else live_quotes_flush_seconds()
        )
        self.stale_seconds = (
            stale_seconds if stale_seconds is not None else live_quotes_stale_seconds()
        )
        self._clock = clock or utcnow
        self._feed_factory = feed_factory or self._default_feed
        self._feed = None
        self._feed_thread = None
        self._flush_thread = None
        self._stop = threading.Event()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._enabled = False
        self._state = "disabled"

    # -- lifecycle ---------------------------------------------------------

    def _default_feed(self):
        return YahooQuoteFeed(universe_tickers(), self.handle_stream_quote)

    def start(self, session_factory=None, enabled=None):
        """Start the feed and flush loop. Idempotent. Disabled by default."""
        if self._feed_thread is not None or self._flush_thread is not None:
            return

        if session_factory is not None:
            self._session_factory = session_factory

        self._enabled = live_quotes_enabled() if enabled is None else bool(enabled)
        if not self._enabled:
            self._state = "disabled"
            logger.info(
                "Live quote feed is disabled (LIVE_QUOTES_ENABLED is not set); "
                "prices keep updating through the scheduled REST sync."
            )
            return

        if self._session_factory is not None:
            self.restore(self._session_factory)

        self._feed = self._feed_factory()
        if self._feed is None:
            self._enabled = False
            self._state = "disabled"
            return

        self._stop.clear()
        self._state = "connecting"
        self._feed_thread = threading.Thread(
            target=self._run_feed, name="live-quotes", daemon=True
        )
        self._flush_thread = threading.Thread(
            target=self._flush_loop, name="live-quotes-flush", daemon=True
        )
        self._feed_thread.start()
        self._flush_thread.start()

    def _run_feed(self):
        try:
            asyncio.run(self._feed.run())
        except Exception:  # noqa: BLE001 - never let the worker die silently
            logger.exception("Live quote feed stopped unexpectedly")
        finally:
            if self._state != "disabled":
                self._state = "stopped"

    def _flush_loop(self):
        while not self._stop.wait(self.flush_seconds):
            try:
                self.flush()
            except Exception:  # noqa: BLE001 - keep the interval alive
                logger.exception("Live quote flush failed")
            try:
                # The browser learns about a dropped or recovered upstream
                # connection here; the route only sends the starting state.
                self.hub.publish_status(self.status())
            except Exception:  # noqa: BLE001 - status is best-effort
                logger.exception("Live quote status publish failed")

    def stop(self):
        """Stop both workers, then flush whatever is still pending."""
        if self._feed is not None:
            self._feed.stop()
        self._stop.set()

        if self._flush_thread is not None:
            self._flush_thread.join(timeout=5)
            self._flush_thread = None
        if self._feed_thread is not None:
            self._feed_thread.join(timeout=5)
            self._feed_thread = None

        self.flush()
        self._feed = None
        self._state = "stopped" if self._enabled else "disabled"

    # -- status ------------------------------------------------------------

    def status(self):
        """A small, honest description of the feed for the status frame."""
        feed = self._feed
        state = feed.state if feed is not None else self._state
        connected_at = feed.connected_at if feed is not None else None
        last_tick_at = feed.last_tick_at if feed is not None else None
        return {
            "enabled": self._enabled,
            "state": state,
            "streaming": state == "live",
            "staleAfterSeconds": self.stale_seconds,
            "flushSeconds": self.flush_seconds,
            "connectedAt": to_json_value(connected_at) if connected_at else None,
            "lastTickAt": to_json_value(last_tick_at) if last_tick_at else None,
        }

    def is_streaming(self):
        """True only while the upstream connection is actually live."""
        return self._feed is not None and self._feed.state == "live"

    # -- cache reads -------------------------------------------------------

    def restore(self, session_factory):
        """Seed the cache from ``latest_quotes`` as non-live values."""
        try:
            with session_factory() as session:
                rows = session.execute(
                    select(
                        Instrument.symbol,
                        LatestQuote.ltp,
                        LatestQuote.day_change,
                        LatestQuote.day_change_pct,
                        LatestQuote.source_time,
                        LatestQuote.updated_at,
                    ).join(
                        LatestQuote, LatestQuote.instrument_id == Instrument.id
                    )
                ).all()
        except Exception:  # noqa: BLE001 - REST still works without a seed
            logger.exception("Could not seed the live quote cache from PostgreSQL")
            return 0

        restored = 0
        for symbol, ltp, day_change, day_change_pct, source_time, updated_at in rows:
            quote = self.cache.restore(
                symbol,
                float(ltp),
                float(day_change),
                float(day_change_pct),
                source_time,
                updated_at,
            )
            if quote is not None:
                restored += 1
        logger.info("Live quote cache seeded with %s persisted quotes", restored)
        return restored

    def frame_for(self, quote, now=None):
        """Serialize one cached quote for the browser."""
        moment = now or self._clock()
        updated_at = quote.updated_at or quote.received_at or quote.source_time
        return {
            "symbol": quote.symbol,
            "ltp": quote.ltp,
            "dayChange": quote.day_change,
            "dayChangePct": quote.day_change_pct,
            "updatedAt": to_json_value(updated_at) if updated_at else None,
            "sourceTime": to_json_value(quote.source_time) if quote.source_time else None,
            "receivedAt": (
                to_json_value(quote.received_at) if quote.received_at else None
            ),
            "live": quote.live,
            # A value seeded from latest_quotes at startup. It is a fast first
            # paint, not a price update, so the frontend must not let it block
            # the REST row that polling keeps refreshing.
            "restored": not quote.live,
            "stale": is_stale(quote, moment, self.stale_seconds),
        }

    def frames_for(self, symbols):
        """Snapshot frames for the requested symbols (all when ``None``)."""
        now = self._clock()
        return [self.frame_for(quote, now) for quote in self.cache.snapshot(symbols)]

    def pending_count(self):
        with self._pending_lock:
            return len(self._pending)

    # -- writes ------------------------------------------------------------

    def handle_stream_quote(self, quote):
        """Accept one decoded Yahoo frame. Returns True when it was applied."""
        symbol = app_symbol(quote.get("id"))
        if not symbol:
            return False

        stamp = quote.get("time")
        source_time = (
            provider_source_time(stamp / 1000)
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
            else None
        )
        if source_time is None:
            logger.debug("Skipping %s: live frame has no source time", symbol)
            return False

        received_at = self._clock()
        age = (received_at - source_time).total_seconds()
        if age > self.stale_seconds:
            logger.debug("Skipping %s: live frame is %.0fs old", symbol, age)
            return False
        if age < -MAX_FUTURE_SKEW_SECONDS:
            logger.debug("Skipping %s: live frame is in the future", symbol)
            return False

        cached = self.cache.record(
            symbol,
            quote.get("price"),
            quote.get("change"),
            quote.get("change_percent"),
            source_time,
            received_at,
            quote.get("day_volume"),
        )
        if cached is None:
            # Invalid price, or an out-of-order/duplicate frame.
            return False

        self.hub.publish({cached.symbol: self.frame_for(cached)})
        self._queue(cached)
        return True

    def _queue(self, quote):
        """Remember the newest tick for the next coalesced database write."""
        row = {
            "regularMarketPrice": quote.ltp,
            "regularMarketChange": quote.day_change,
            "regularMarketChangePercent": quote.day_change_pct,
            "regularMarketTime": quote.source_time.timestamp(),
        }
        if quote.volume is not None:
            row["regularMarketVolume"] = quote.volume
        entry = {
            "symbol": quote.symbol,
            "name": quote.symbol,
            "kind": "index" if quote.symbol.startswith("^") else "stock",
            "row": row,
        }
        with self._pending_lock:
            self._pending[quote.symbol] = entry

    def flush(self):
        """Write the newest pending tick per symbol. Failure keeps the queue."""
        with self._pending_lock:
            pending = self._pending
            self._pending = {}

        if not pending:
            return 0

        factory = self._session_factory
        if factory is None:
            logger.warning(
                "Live quote flush skipped (%s update(s)): no session factory",
                len(pending),
            )
            self._requeue(pending)
            return 0

        try:
            written = persist_price_quotes(factory, list(pending.values()))
        except Exception:  # noqa: BLE001 - keep ticks for the next flush
            logger.exception(
                "Live quote persistence failed; %s update(s) kept for retry",
                len(pending),
            )
            self._requeue(pending)
            return 0

        if written:
            try:
                # The watchlist channel keeps working for older clients. The
                # generic channel already received each live tick immediately.
                publish_persisted_quotes(factory, list(pending))
            except Exception:  # noqa: BLE001 - delivery is best-effort
                logger.exception("Live quote delivery after persistence failed")
        return written

    def _requeue(self, pending):
        with self._pending_lock:
            for symbol, entry in pending.items():
                # A tick that arrived during the failed write is newer.
                self._pending.setdefault(symbol, entry)


# One instance per process. ``api.main`` starts and stops it with the app.
quote_service = QuoteService()
