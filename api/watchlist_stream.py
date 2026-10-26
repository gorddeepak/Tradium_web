"""Live watchlist price delivery over WebSockets.

The REST route stays the source of the initial list. This module only pushes
price changes after ``price_sync`` has committed them to PostgreSQL, so a
client never sees a price that is not in ``latest_quotes``.

Membership comes from ``watchlists`` on every publish, not from a copy taken
at connect time. That keeps add/remove working while a socket is open and
makes per-user isolation a property of the query: a connection only ever
receives rows whose ``user_id`` matches the JWT that opened it.

``price_sync`` runs on a scheduler thread while FastAPI serves sockets on the
event loop, so ``publish`` schedules sends with
``asyncio.run_coroutine_threadsafe``. No extra service, queue or dependency is
involved.
"""

import asyncio
import logging
import threading

from sqlalchemy import select

from .postgres.models import Instrument, LatestQuote, Watchlist
from .serialization import to_json_value

logger = logging.getLogger(__name__)


class WatchlistHub:
    """Tracks open sockets by user id and schedules quote frames to them."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}
        self._loop = None

    async def connect(self, websocket, user_id):
        """Register a socket on the loop that is serving it."""
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._subscribers.setdefault(user_id, set()).add(websocket)

    def disconnect(self, websocket, user_id):
        """Forget a socket. Safe to call twice."""
        with self._lock:
            connections = self._subscribers.get(user_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._subscribers.pop(user_id, None)

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

    def publish(self, updates_by_user):
        """Schedule one ``quotes`` frame per connection.

        Returns the number of frames scheduled. A closed or missing loop means
        there is nothing to deliver; the next price tick will try again.
        """
        with self._lock:
            loop = self._loop
            targets = [
                (user_id, websocket)
                for user_id, updates in updates_by_user.items()
                for websocket in self._subscribers.get(user_id, ())
            ]

        if loop is None or loop.is_closed():
            return 0

        scheduled = 0
        for user_id, websocket in targets:
            payload = {"type": "quotes", "quotes": updates_by_user[user_id]}
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send(websocket, user_id, payload), loop
                )
                scheduled += 1
            except RuntimeError:
                # The loop closed between the check and the schedule.
                logger.debug("Watchlist stream loop closed; dropping frame")
        return scheduled

    async def _send(self, websocket, user_id, payload):
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 - a dead socket must not stop the others
            self.disconnect(websocket, user_id)


hub = WatchlistHub()


def watchlist_quote_updates(session_factory, symbols):
    """Read persisted quotes for watchlist rows matching ``symbols``.

    Returns ``{user_id: [{"_id", "symbol", "ltp", "dayChangePct", "updatedAt"}]}``.
    A watchlist row without an instrument or quote is omitted rather than
    sending a fabricated zero.
    """
    unique = list(dict.fromkeys(symbols))
    if not unique:
        return {}

    with session_factory() as session:
        rows = session.execute(
            select(
                Watchlist.user_id,
                Watchlist.id,
                Watchlist.symbol,
                LatestQuote.ltp,
                LatestQuote.day_change_pct,
                LatestQuote.updated_at,
            )
            .join(Instrument, Instrument.symbol == Watchlist.symbol)
            .join(LatestQuote, LatestQuote.instrument_id == Instrument.id)
            .where(Watchlist.symbol.in_(unique))
        ).all()

    updates = {}
    for user_id, item_id, symbol, ltp, day_change_pct, updated_at in rows:
        updates.setdefault(user_id, []).append(
            {
                "_id": item_id,
                "symbol": symbol,
                "ltp": to_json_value(ltp),
                "dayChangePct": to_json_value(day_change_pct),
                "updatedAt": to_json_value(updated_at),
            }
        )
    return updates


def publish_persisted_quotes(session_factory, symbols):
    """Publish the stored quotes for ``symbols`` to connected watchlists.

    Called by ``price_sync`` only after its quote transaction commits. A read
    failure is logged and swallowed: live updates are best-effort and must not
    fail the job that fills orders.
    """
    if not hub.has_subscribers():
        return 0

    try:
        updates = watchlist_quote_updates(session_factory, symbols)
    except Exception:  # noqa: BLE001 - a failed push must not fail price sync
        logger.exception("Watchlist quote read failed; skipping live updates")
        return 0

    return hub.publish(updates)
