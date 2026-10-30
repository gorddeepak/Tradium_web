"""Shared live-quote delivery for any authenticated page.

``watchlist_stream`` owns the watchlist frame shape: one row per watchlist
entry, carrying that entry's ``_id``. This module is the general channel. A
client subscribes to symbols and receives a quote for each one, so Markets,
Holdings, Positions and the instrument detail pane share a single delivery
mechanism.

Two properties are deliberate and load-bearing:

- **The hub stores no prices.** It is a subscriber registry only. Frames come
  either from the live cache (``api/quote_service.py``) or from
  ``latest_quotes`` after a job commits, and both paths go through here.
- **Someone watching a symbol keeps it quoted.** ``subscribed_symbols`` is
  read by ``price_sync`` and added to its otherwise book-derived symbol set.
  Opening a detail page for a stock nobody holds therefore gets updates
  without widening the permanent provider load.

Live ticks are published immediately by ``QuoteService``. The scheduled REST
sync still publishes persisted rows when the upstream feed is not streaming,
so a deployment without ``LIVE_QUOTES_ENABLED`` behaves as it did before.
"""

import asyncio
import logging
import re
import threading

from sqlalchemy import select

from .postgres.models import Instrument, LatestQuote
from .serialization import to_json_value

logger = logging.getLogger(__name__)

# Same alphabet the watchlist accepts: ^ is allowed for index tickers.
SYMBOL_PATTERN = re.compile(r"[\^A-Z0-9&-]{1,20}")

# One page never needs more than the 53-symbol universe plus a few extras.
MAX_SYMBOLS = 200


def normalize_symbols(values):
    """Upper-case, deduplicate and drop anything that is not a valid symbol."""
    cleaned = []
    for value in values:
        symbol = str(value or "").strip().upper()
        if SYMBOL_PATTERN.fullmatch(symbol) and symbol not in cleaned:
            cleaned.append(symbol)
        if len(cleaned) >= MAX_SYMBOLS:
            break
    return cleaned


class QuoteHub:
    """Tracks open sockets and the symbols each one is watching.

    ``_subscribers`` maps a user id to ``{websocket: symbols}``. The user id is
    kept for diagnostics and per-user isolation; delivery itself is filtered by
    the connection's own symbol set, so two tabs watching different pages never
    receive each other's frames.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}
        self._loop = None

    async def connect(self, websocket, user_id, symbols=()):
        """Register a socket on the loop that is serving it."""
        wanted = set(normalize_symbols(symbols))
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._subscribers.setdefault(user_id, {})[websocket] = wanted
        return wanted

    def subscribe(self, websocket, user_id, symbols):
        """Add symbols to one connection's set. Returns the new set."""
        added = set(normalize_symbols(symbols))
        with self._lock:
            current = self._subscribers.get(user_id, {}).get(websocket)
            if current is None:
                return set()
            current.update(added)
            return set(current)

    def unsubscribe(self, websocket, user_id, symbols):
        """Remove symbols from one connection's set. Returns the new set."""
        removed = set(normalize_symbols(symbols))
        with self._lock:
            current = self._subscribers.get(user_id, {}).get(websocket)
            if current is None:
                return set()
            current.difference_update(removed)
            return set(current)

    def disconnect(self, websocket, user_id):
        """Forget a socket. Safe to call twice."""
        with self._lock:
            connections = self._subscribers.get(user_id)
            if connections is None:
                return
            connections.pop(websocket, None)
            if not connections:
                self._subscribers.pop(user_id, None)

    def subscribed_symbols(self):
        """Every symbol any connected client is watching."""
        with self._lock:
            return {
                symbol
                for connections in self._subscribers.values()
                for symbols in connections.values()
                for symbol in symbols
            }

    def has_subscribers(self):
        with self._lock:
            return bool(self._subscribers)

    def subscriber_count(self):
        """Number of registered sockets, used by tests and diagnostics."""
        with self._lock:
            return sum(len(connections) for connections in self._subscribers.values())

    def reset(self):
        """Drop every socket and loop binding; tests use this between cases."""
        with self._lock:
            self._subscribers.clear()
            self._loop = None

    def publish(self, rows_by_symbol):
        """Schedule one ``quotes`` frame per connection for its own symbols.

        ``rows_by_symbol`` maps a symbol to its already-serialized quote. A
        connection with nothing new is skipped rather than sent an empty frame.
        """
        if not rows_by_symbol:
            return 0

        with self._lock:
            loop = self._loop
            targets = []
            for connections in self._subscribers.values():
                for websocket, symbols in connections.items():
                    quotes = [
                        rows_by_symbol[symbol]
                        for symbol in sorted(symbols)
                        if symbol in rows_by_symbol
                    ]
                    if quotes:
                        targets.append((websocket, quotes))

        if loop is None or loop.is_closed():
            return 0

        scheduled = 0
        for websocket, quotes in targets:
            payload = {"type": "quotes", "quotes": quotes}
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send(websocket, payload), loop
                )
                scheduled += 1
            except RuntimeError:
                # The loop closed between the check and the schedule.
                logger.debug("Quote stream loop closed; dropping frame")
        return scheduled

    def publish_status(self, status):
        """Send a ``status`` frame to every connection.

        This is how a browser learns that the upstream feed is disabled,
        reconnecting or live, instead of guessing from the absence of ticks.
        """
        with self._lock:
            loop = self._loop
            targets = [
                websocket
                for connections in self._subscribers.values()
                for websocket in connections
            ]

        if loop is None or loop.is_closed():
            return 0

        payload = {"type": "status", **status}
        scheduled = 0
        for websocket in targets:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send(websocket, payload), loop
                )
                scheduled += 1
            except RuntimeError:
                logger.debug("Quote stream loop closed; dropping status frame")
        return scheduled

    async def _send(self, websocket, payload):
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 - a dead socket must not stop the others
            with self._lock:
                for user_id, connections in list(self._subscribers.items()):
                    if websocket in connections:
                        connections.pop(websocket, None)
                        if not connections:
                            self._subscribers.pop(user_id, None)
                        break


hub = QuoteHub()


def quote_frames(session_factory, symbols, live=False):
    """Read the persisted quotes for ``symbols`` as JSON-safe frames.

    Returns ``{symbol: {"symbol", "ltp", "dayChange", "dayChangePct",
    "updatedAt", "sourceTime", "receivedAt", "live", "restored", "stale"}}``.
    A symbol without an instrument or quote is omitted rather than sent as a
    fabricated zero. ``live`` stays false here: these rows were committed by a
    scheduled sync, not received from the upstream stream. ``restored`` is
    false too, because polling is a real update of the REST fallback, unlike a
    cache seed loaded at startup.
    """
    wanted = normalize_symbols(symbols)
    if not wanted:
        return {}

    with session_factory() as session:
        rows = session.execute(
            select(
                Instrument.symbol,
                LatestQuote.ltp,
                LatestQuote.day_change,
                LatestQuote.day_change_pct,
                LatestQuote.updated_at,
                LatestQuote.source_time,
            )
            .join(LatestQuote, LatestQuote.instrument_id == Instrument.id)
            .where(Instrument.symbol.in_(wanted))
        ).all()

    frames = {}
    for symbol, ltp, day_change, day_change_pct, updated_at, source_time in rows:
        frames[symbol] = {
            "symbol": symbol,
            "ltp": to_json_value(ltp),
            "dayChange": to_json_value(day_change),
            "dayChangePct": to_json_value(day_change_pct),
            "updatedAt": to_json_value(updated_at),
            "sourceTime": to_json_value(source_time),
            "receivedAt": None,
            "live": live,
            "restored": False,
            "stale": False,
        }
    return frames


def publish_live_quotes(session_factory, symbols, live=False):
    """Publish committed quotes for ``symbols`` to every subscriber watching.

    Called by ``price_sync`` and ``market_sync`` only after their write
    transaction commits, and only while the upstream feed is not streaming. A
    read failure is logged and swallowed: live delivery is best-effort and must
    never fail the job that fills orders.
    """
    if not hub.has_subscribers():
        return 0

    try:
        frames = quote_frames(session_factory, symbols, live=live)
    except Exception:  # noqa: BLE001 - a failed push must not fail the job
        logger.exception("Live quote read failed; skipping live updates")
        return 0

    return hub.publish(frames)
