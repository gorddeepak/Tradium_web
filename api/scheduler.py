"""The background schedules, and the switches that say who owns them.

Express schedules three jobs unconditionally when it connects:

    cron.schedule("* * * * *", syncPrices, { timezone: "Asia/Kolkata" });
    syncPrices();
    cron.schedule("*/5 * * * *", marketSync, { timezone: "Asia/Kolkata" });
    marketSync(); // populates the NIFTY 50 cache on a cold start
    cron.schedule("0 18 * * *", recordDailySnapshot, { timezone: "Asia/Kolkata" });

Two services running the same job against one database would double the Yahoo
traffic, race on the same documents, and — for ``priceSync`` — both try to fill
the same orders, so ownership is explicit:

- ``MARKET_SYNC_ENABLED`` gates the shared market-cache refresh.
- ``TRADING_JOBS_ENABLED`` gates the per-minute price sync (which fills orders
  and moves funds) and the daily 18:00 IST portfolio snapshot.

Both default to **off**. Exactly one process may set each, and during the
migration that process is whichever service owns the job — never both. See
``docs/migration/MIGRATION_STATUS.md`` §3J.

The ticks are plain threads rather than a scheduler dependency: two intervals
and one fixed daily time need no cron expression parser, and the suite never
starts them.
"""

import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from .jobs.market_sync import market_sync
from .jobs.portfolio_snapshot import record_daily_snapshot
from .jobs.price_sync import sync_prices
from .market_hours import IST
from .postgres.session import get_session_factory

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 5 * 60
PRICE_SYNC_INTERVAL_SECONDS = 60

# Express's cron is "0 18 * * *" in Asia/Kolkata.
SNAPSHOT_HOUR_IST = 18


def market_sync_enabled():
    """Read the switch at call time, so tests and deployments can both set it."""
    return _enabled("MARKET_SYNC_ENABLED")


def trading_jobs_enabled():
    """Price sync plus the daily snapshot share one owner switch."""
    return _enabled("TRADING_JOBS_ENABLED")


def _enabled(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def seconds_until_snapshot(hour=SNAPSHOT_HOUR_IST, now=None):
    """Seconds from ``now`` to the next ``hour:00`` IST.

    A moment exactly at the hour counts as due now (delay 0), which is the
    instant node-cron fires.
    """
    moment = now or datetime.now(timezone.utc)
    ist_now = moment.astimezone(IST)
    target = ist_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target < ist_now:
        target += timedelta(days=1)
    return (target - ist_now).total_seconds()


class JobScheduler:
    """A daemon thread that runs one job until stopped."""

    name = "job"
    run_immediately = True

    def __init__(self, session_factory=None):
        self.session_factory = session_factory
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def next_delay(self):
        raise NotImplementedError

    def run_job(self, session_factory):
        raise NotImplementedError

    def _run(self):
        if self.run_immediately:
            self._tick()
        while not self._stop.wait(self.next_delay()):
            self._tick()

    def _tick(self):
        try:
            factory = self.session_factory or get_session_factory()
            self.run_job(factory)
        except Exception:  # noqa: BLE001 - keep the thread alive
            logger.exception("%s tick failed", self.name)


class MarketSyncScheduler(JobScheduler):
    """Runs ``market_sync`` every five minutes until stopped."""

    name = "market-sync"

    def __init__(self, interval_seconds=SYNC_INTERVAL_SECONDS, session_factory=None):
        super().__init__(session_factory)
        self.interval_seconds = interval_seconds

    def next_delay(self):
        return self.interval_seconds

    def run_job(self, session_factory):
        market_sync(session_factory)


class PriceSyncScheduler(JobScheduler):
    """Runs ``sync_prices`` every minute until stopped.

    ``sync_prices`` owns the market-hours gate, so a tick outside 09:15-15:30
    IST costs nothing and no order is filled.
    """

    name = "price-sync"

    def __init__(self, interval_seconds=PRICE_SYNC_INTERVAL_SECONDS, session_factory=None):
        super().__init__(session_factory)
        self.interval_seconds = interval_seconds

    def next_delay(self):
        return self.interval_seconds

    def run_job(self, session_factory):
        sync_prices(session_factory)


class PortfolioSnapshotScheduler(JobScheduler):
    """Runs ``record_daily_snapshot`` once a day at 18:00 IST.

    Unlike the two interval jobs there is no run on startup: Express only adds
    the cron entry, so a process that starts at 20:00 waits until tomorrow.
    """

    name = "portfolio-snapshot"
    run_immediately = False

    def __init__(self, hour=SNAPSHOT_HOUR_IST, session_factory=None):
        super().__init__(session_factory)
        self.hour = hour

    def next_delay(self):
        return seconds_until_snapshot(self.hour)

    def run_job(self, session_factory):
        record_daily_snapshot(session_factory)
