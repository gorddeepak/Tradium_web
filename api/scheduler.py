"""The market-cache schedule, and the switch that says who owns it.

Express schedules ``marketSync`` unconditionally when it connects:

    cron.schedule("*/5 * * * *", marketSync, { timezone: "Asia/Kolkata" });
    marketSync(); // populates the NIFTY 50 cache on a cold start

Two services syncing the same collection would double the Yahoo traffic and
race on the same documents, so ownership here is explicit: **nothing runs
unless ``MARKET_SYNC_ENABLED`` is set.** Exactly one process may set it, and
during the migration that process is whichever service owns the cache -- not
both. See ``docs/migration/MIGRATION_STATUS.md`` §3I.

The tick is a plain thread rather than a scheduler dependency: one five-minute
interval needs no cron expression parser, and the suite never starts it.
"""

import logging
import os
import threading

from .jobs.market_sync import market_sync

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 5 * 60


def market_sync_enabled():
    """Read the switch at call time, so tests and deployments can both set it."""
    return os.getenv("MARKET_SYNC_ENABLED", "").strip().lower() in {"1", "true", "yes"}


class MarketSyncScheduler:
    """Runs ``market_sync`` every five minutes until stopped."""

    def __init__(self, db, interval_seconds=SYNC_INTERVAL_SECONDS):
        self.db = db
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="market-sync", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self):
        # Express also syncs once on connect, so a cold cache is populated
        # immediately rather than after the first interval.
        self._tick()
        while not self._stop.wait(self.interval_seconds):
            self._tick()

    def _tick(self):
        try:
            market_sync(self.db)
        except Exception:  # noqa: BLE001 - keep the thread alive
            logger.exception("Market sync tick failed")
