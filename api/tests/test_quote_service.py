"""Focused tests for the live quote service (cache, batching, lifecycle).

The provider, the database and the WebSocket hub are all replaced with small
fakes. Nothing here touches the network or PostgreSQL.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from api import quote_service as service_module
from api.quote_cache import QuoteCache
from api.quote_service import QuoteService, app_symbol, universe_tickers

NOW = datetime(2026, 10, 25, 10, 0, 0, 5000, tzinfo=timezone.utc)


class FakeHub:
    def __init__(self):
        self.frames = []
        self.statuses = []

    def publish(self, rows):
        self.frames.append(rows)
        return len(rows)

    def publish_status(self, status):
        self.statuses.append(status)
        return 1


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, _statement):
        rows = self.rows

        class Result:
            def all(self):
                return rows

        return Result()


class FakeSessionFactory:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def __call__(self):
        return FakeSession(self.rows)


def yahoo_frame(
    symbol="INFY.NS",
    price=1500.0,
    stamp=NOW,
    change=12.0,
    change_pct=0.8,
    volume=1000,
):
    frame = {
        "id": symbol,
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "time": int(stamp.timestamp() * 1000),
    }
    if volume is not None:
        frame["day_volume"] = volume
    return frame


def make_service(**overrides):
    values = {
        "hub": FakeHub(),
        "clock": lambda: NOW,
        "flush_seconds": 999,
        "stale_seconds": 60,
    }
    values.update(overrides)
    return QuoteService(**values)


def test_a_tick_updates_the_cache_and_publishes_before_persistence():
    service = make_service()

    assert service.handle_stream_quote(yahoo_frame()) is True

    quote = service.cache.get("INFY")
    assert quote is not None
    assert quote.ltp == 1500.0
    assert quote.live is True
    assert service.pending_count() == 1

    frame = service.hub.frames[0]["INFY"]
    assert frame["symbol"] == "INFY"
    assert frame["ltp"] == 1500.0
    assert frame["live"] is True
    assert frame["restored"] is False
    assert frame["stale"] is False
    assert frame["receivedAt"] == "2026-10-25T10:00:00.005Z"
    assert frame["sourceTime"] == "2026-10-25T10:00:00.005Z"


def test_provider_tickers_map_to_application_symbols():
    service = make_service()

    service.handle_stream_quote(yahoo_frame(symbol="^NSEI", price=25000.0))

    assert service.cache.get("^NSEI") is not None
    assert app_symbol("RELIANCE.NS") == "RELIANCE"
    assert app_symbol("^NSEI") == "^NSEI"


def test_the_universe_uses_the_same_mapping_as_the_sync_jobs():
    tickers = universe_tickers()

    assert "^NSEI" in tickers
    assert "INFY.NS" in tickers
    assert "INFY" not in tickers
    assert len(tickers) == 53


@pytest.mark.parametrize("price", [0, -1, None, "1500", float("nan")])
def test_an_invalid_price_is_ignored(price):
    service = make_service()

    assert service.handle_stream_quote(yahoo_frame(price=price)) is False
    assert len(service.cache) == 0
    assert service.hub.frames == []
    assert service.pending_count() == 0


def test_a_frame_without_a_source_time_is_ignored():
    service = make_service()
    frame = yahoo_frame()
    del frame["time"]

    assert service.handle_stream_quote(frame) is False
    assert len(service.cache) == 0


def test_a_stale_tick_is_ignored():
    service = make_service()

    old = yahoo_frame(stamp=NOW - timedelta(seconds=120))

    assert service.handle_stream_quote(old) is False
    assert service.hub.frames == []
    assert service.pending_count() == 0


def test_a_tick_from_the_future_is_ignored():
    service = make_service()

    future = yahoo_frame(stamp=NOW + timedelta(hours=1))

    assert service.handle_stream_quote(future) is False
    assert service.pending_count() == 0


def test_an_out_of_order_tick_cannot_overwrite_a_newer_one():
    service = make_service()
    service.handle_stream_quote(yahoo_frame(price=1500.0))

    older = service.handle_stream_quote(
        yahoo_frame(price=1400.0, stamp=NOW - timedelta(seconds=1))
    )

    assert older is False
    assert service.cache.get("INFY").ltp == 1500.0
    assert len(service.hub.frames) == 1
    assert service.pending_count() == 1


def test_a_restored_quote_is_never_published_as_live():
    service = make_service()
    service.cache.restore("INFY", 1400.0, 0.0, 0.0, NOW, NOW - timedelta(minutes=5))

    frame = service.frames_for(["INFY"])[0]

    assert frame["live"] is False
    assert frame["restored"] is True
    assert frame["receivedAt"] is None
    assert frame["updatedAt"] == "2026-10-25T09:55:00.005Z"


def test_restore_seeds_every_persisted_quote_as_non_live():
    service = make_service(
        session_factory=FakeSessionFactory(
            [
                ("INFY", 1500.0, 12.0, 0.8, NOW, NOW),
                ("^NSEI", 25000.0, 10.0, 0.1, NOW, NOW),
            ]
        )
    )

    assert service.restore(service._session_factory) == 2

    assert service.cache.get("INFY").live is False
    assert service.cache.get("^NSEI").live is False
    assert service.frames_for(None)[0]["live"] is False


def test_restore_swallows_a_database_failure():
    def broken_factory():
        raise RuntimeError("database unavailable")

    service = make_service()

    assert service.restore(broken_factory) == 0


def test_flush_coalesces_to_the_newest_tick_per_symbol(monkeypatch):
    service = make_service(session_factory=object())
    calls = []
    deliveries = []

    def persist(factory, entries):
        calls.append(entries)
        return len(entries)

    monkeypatch.setattr(service_module, "persist_price_quotes", persist)
    monkeypatch.setattr(
        service_module,
        "publish_persisted_quotes",
        lambda factory, symbols: deliveries.append(symbols),
    )

    service.handle_stream_quote(yahoo_frame(price=1500.0))
    service.handle_stream_quote(
        yahoo_frame(price=1510.0, stamp=NOW + timedelta(seconds=1))
    )
    assert service.pending_count() == 1

    assert service.flush() == 1

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0]["symbol"] == "INFY"
    assert calls[0][0]["row"]["regularMarketPrice"] == 1510.0
    assert deliveries == [["INFY"]]
    assert service.pending_count() == 0


def test_a_failed_flush_keeps_the_pending_tick(monkeypatch):
    service = make_service(session_factory=object())
    attempts = []

    def persist(factory, entries):
        attempts.append(entries)
        if len(attempts) == 1:
            raise RuntimeError("database unavailable")
        return len(entries)

    monkeypatch.setattr(service_module, "persist_price_quotes", persist)
    monkeypatch.setattr(
        service_module, "publish_persisted_quotes", lambda factory, symbols: 0
    )

    service.handle_stream_quote(yahoo_frame())

    assert service.flush() == 0
    assert service.pending_count() == 1

    assert service.flush() == 1
    assert service.pending_count() == 0
    assert len(attempts) == 2


def test_a_tick_arriving_during_a_failed_flush_wins_the_retry(monkeypatch):
    service = make_service(session_factory=object())

    def persist(factory, entries):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service_module, "persist_price_quotes", persist)

    service.handle_stream_quote(yahoo_frame(price=1500.0))
    service.flush()
    # The first tick stays queued, then a newer one replaces it.
    service.handle_stream_quote(
        yahoo_frame(price=1520.0, stamp=NOW + timedelta(seconds=1))
    )

    assert service.pending_count() == 1
    assert service._pending["INFY"]["row"]["regularMarketPrice"] == 1520.0


def test_stop_flushes_pending_ticks(monkeypatch):
    service = make_service(session_factory=object())
    calls = []

    monkeypatch.setattr(
        service_module,
        "persist_price_quotes",
        lambda factory, entries: calls.append(entries) or len(entries),
    )
    monkeypatch.setattr(
        service_module, "publish_persisted_quotes", lambda factory, symbols: 0
    )

    service.handle_stream_quote(yahoo_frame())
    service.stop()

    assert len(calls) == 1
    assert service.pending_count() == 0


def test_the_feed_is_disabled_by_default():
    started = []

    def feed_factory():
        started.append(True)
        raise AssertionError("feed must not start while disabled")

    service = make_service(feed_factory=feed_factory)

    service.start(enabled=False)

    assert started == []
    assert service.status()["enabled"] is False
    assert service.status()["state"] == "disabled"
    assert service.is_streaming() is False


class FakeFeed:
    def __init__(self):
        self.state = "connecting"
        self.connected_at = None
        self.last_tick_at = None
        self.stopped = threading.Event()
        self.started = threading.Event()

    async def run(self):
        self.state = "live"
        self.connected_at = NOW
        self.started.set()
        while not self.stopped.is_set():
            await __import__("asyncio").sleep(0.01)
        self.state = "stopped"

    def stop(self):
        self.stopped.set()


def test_start_runs_the_feed_and_stop_joins_it():
    feed = FakeFeed()
    service = make_service(feed_factory=lambda: feed)

    service.start(enabled=True)
    assert feed.started.wait(2)
    assert service.is_streaming() is True
    assert service.status()["state"] == "live"

    service.stop()

    assert feed.stopped.is_set()
    assert service.is_streaming() is False
    assert service.status()["state"] == "stopped"


def test_the_flush_loop_publishes_the_feed_status():
    """A reconnect must reach the browser, not just the startup frame."""
    feed = FakeFeed()
    service = make_service(feed_factory=lambda: feed, flush_seconds=0.02)

    service.start(enabled=True)
    try:
        assert feed.started.wait(2)
        for _ in range(200):
            if service.hub.statuses:
                break
            time.sleep(0.01)

        assert service.hub.statuses
        assert service.hub.statuses[-1]["state"] == "live"
        assert service.hub.statuses[-1]["streaming"] is True
    finally:
        service.stop()
