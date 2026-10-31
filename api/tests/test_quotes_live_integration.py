"""End-to-end live-quote test: mock provider -> decoder -> feed -> service -> WS -> PostgreSQL.

The unit suites replace one layer at a time. This file replaces only the
upstream socket, so the rest is the real stack: the real protobuf decoder, the
real ``YahooQuoteFeed`` (including reconnect), the real ``QuoteService``, the
real quote hub and the real ``latest_quotes`` upsert.

Requires ``TEST_DATABASE_URL`` naming a disposable ``*_test`` database; the
``postgres_*`` fixtures in ``conftest.py`` skip the module when it is unset.
No real Yahoo socket is opened here.
"""

import asyncio
import base64
import json
import struct
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from api.postgres.models import Instrument, LatestQuote
from api.quote_feed import YahooQuoteFeed
from api.quote_service import QuoteService
from api.quote_stream import hub
from api.routes import quotes as quote_routes


# --------------------------------------------------------------------------
# A fake upstream socket that emits real decoder frames
# --------------------------------------------------------------------------


def _varint(value):
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _zigzag(value):
    return (value << 1) ^ (value >> 63)


def _field(number, wire_type, payload):
    return _varint((number << 3) | wire_type) + payload


def pricing_frame(symbol, price, stamp, change=0.0, change_pct=0.0, volume=None):
    """Encode one Yahoo ``pricing`` frame with the same field numbers as Yahoo."""
    payload = _field(1, 2, _varint(len(symbol)) + symbol.encode())
    payload += _field(2, 5, struct.pack("<f", price))
    payload += _field(3, 0, _varint(_zigzag(int(stamp.timestamp() * 1000))))
    payload += _field(8, 5, struct.pack("<f", change_pct))
    payload += _field(12, 5, struct.pack("<f", change))
    if volume is not None:
        payload += _field(9, 0, _varint(_zigzag(int(volume))))
    return json.dumps(
        {"type": "pricing", "message": base64.b64encode(payload).decode()}
    )


class FakeSocket:
    """Queues frames from the test thread and never closes on its own."""

    def __init__(self):
        self.queue = None
        self.loop = None
        self.ready = threading.Event()
        self.sent = []

    async def _open(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.ready.set()
        return self

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return await self.queue.get()

    def push(self, raw):
        assert self.ready.wait(5), "the feed never connected"
        self.loop.call_soon_threadsafe(self.queue.put_nowait, raw)


class FakeConnector:
    """Hands out the same socket for every connect, optionally failing first."""

    def __init__(self, socket, fail_first=False):
        self.socket = socket
        self.fail_first = fail_first
        self.calls = 0

    def __call__(self, _url):
        self.calls += 1
        socket = self.socket
        fail = self.fail_first and self.calls == 1

        class Connection:
            async def __aenter__(self):
                if fail:
                    raise ConnectionError("provider unavailable")
                return await socket._open()

            async def __aexit__(self, *_exc):
                return False

        return Connection()


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_hub():
    hub.reset()
    yield
    hub.reset()


@pytest.fixture
def start_live_service(postgres_session_factory, monkeypatch):
    """Start a service the test can push fake frames into, and stop it after."""
    started = []

    def _start(flush_seconds=0.05, fail_first=False):
        connector = FakeConnector(FakeSocket(), fail_first=fail_first)

        def feed_factory():
            return YahooQuoteFeed(
                ["INFY.NS", "TCS.NS"],
                service.handle_stream_quote,
                connect=connector,
                backoff_min=0.01,
                backoff_max=0.05,
            )

        service = QuoteService(
            session_factory=postgres_session_factory,
            feed_factory=feed_factory,
            flush_seconds=flush_seconds,
        )
        monkeypatch.setattr(quote_routes, "quote_service", service)
        service.start(enabled=True)
        assert wait_until(lambda: service.is_streaming()), "mock feed never connected"
        started.append(service)
        return service, connector

    yield _start

    for service in started:
        service.stop()


def wait_until(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def receive_quotes(socket):
    """The next quote frame, skipping the periodic status frames."""
    while True:
        frame = socket.receive_json()
        if frame["type"] == "quotes":
            return frame


def read_quote(session_factory, symbol="INFY"):
    with session_factory() as session:
        return session.execute(
            select(
                LatestQuote.ltp,
                LatestQuote.day_change,
                LatestQuote.day_change_pct,
                LatestQuote.prev_close,
                LatestQuote.volume,
                LatestQuote.source_time,
            )
            .join(Instrument, Instrument.id == LatestQuote.instrument_id)
            .where(Instrument.symbol == symbol)
        ).first()


def ltp(session_factory, symbol="INFY"):
    row = read_quote(session_factory, symbol)
    return None if row is None else float(row.ltp)


def connect(client, make_token, user_id, symbols="INFY,TCS"):
    client.cookies.set("token", make_token(user_id))
    return client.websocket_connect(f"/api/quotes/stream?symbols={symbols}")


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_a_mock_tick_reaches_the_browser_and_postgresql(
    client, make_token, user_id, market_instrument_factory,
    postgres_session_factory, start_live_service,
):
    market_instrument_factory(
        symbol="INFY", ltp=1400.0, day_change=12.0, day_change_pct=0.8,
        prev_close=1388.0, volume=10000,
    )
    service, _connector = start_live_service()

    with connect(client, make_token, user_id) as browser:
        status = browser.receive_json()
        snapshot = browser.receive_json()
        assert status["type"] == "status"
        assert status["streaming"] is True
        # The cache was seeded from latest_quotes, not from a tick.
        assert [quote["restored"] for quote in snapshot["quotes"]] == [True]
        assert ltp(postgres_session_factory) == 1400.0

        stamp = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
        _connector.socket.push(
            pricing_frame("INFY.NS", 1501.5, stamp, change=25.0, change_pct=1.7, volume=999)
        )
        quote = receive_quotes(browser)["quotes"][0]

        assert quote["symbol"] == "INFY"
        assert quote["ltp"] == 1501.5
        assert quote["live"] is True
        assert quote["restored"] is False
        assert quote["stale"] is False
        assert quote["sourceTime"] == stamp.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"

        assert wait_until(lambda: ltp(postgres_session_factory) == 1501.5), (
            "the tick never reached latest_quotes"
        )

        row = read_quote(postgres_session_factory)
        # Price sync owns these columns only; the richer market-sync fields
        # (day change, previous close, volume) must survive the tick.
        assert float(row.day_change) == 12.0
        assert float(row.prev_close) == 1388.0
        assert row.volume == 10000
        assert row.source_time is not None
        assert abs((row.source_time - stamp).total_seconds()) < 1
        assert service.status()["lastTickAt"] is not None


def test_invalid_stale_future_and_older_ticks_are_rejected(
    client, make_token, user_id, market_instrument_factory,
    postgres_session_factory, start_live_service,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    service, connector = start_live_service()
    now = datetime.now(timezone.utc)

    with connect(client, make_token, user_id, symbols="INFY") as browser:
        browser.receive_json()  # status
        browser.receive_json()  # restored snapshot

        connector.socket.push(pricing_frame("INFY.NS", 1500.0, now))
        assert receive_quotes(browser)["quotes"][0]["ltp"] == 1500.0

        connector.socket.push(pricing_frame("INFY.NS", 0.0, now + timedelta(seconds=1)))
        connector.socket.push(pricing_frame("INFY.NS", 1490.0, now - timedelta(seconds=120)))
        connector.socket.push(pricing_frame("INFY.NS", 1490.0, now + timedelta(hours=2)))
        connector.socket.push(pricing_frame("INFY.NS", 1400.0, now - timedelta(seconds=1)))

        assert service.cache.get("INFY").ltp == 1500.0
        assert service.pending_count() <= 1  # only the accepted tick is queued

        connector.socket.push(pricing_frame("INFY.NS", 1520.0, now + timedelta(seconds=2)))
        # If any rejected tick had been published, this would be its frame.
        assert receive_quotes(browser)["quotes"][0]["ltp"] == 1520.0

    assert wait_until(lambda: ltp(postgres_session_factory) == 1520.0)


def test_two_browsers_get_their_own_symbols_and_unsubscribe_stops_delivery(
    client, make_token, user_id, market_instrument_factory, start_live_service,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    market_instrument_factory(symbol="TCS", ltp=3000.0)
    service, connector = start_live_service()
    now = datetime.now(timezone.utc)

    with connect(client, make_token, user_id, symbols="INFY") as first:
        first.receive_json()  # status
        first.receive_json()  # snapshot
        with connect(client, make_token, user_id, symbols="TCS") as second:
            second.receive_json()
            second.receive_json()
            assert wait_until(lambda: hub.subscriber_count() == 2)

            connector.socket.push(pricing_frame("INFY.NS", 1500.0, now))
            connector.socket.push(pricing_frame("TCS.NS", 3100.0, now))
            assert [q["symbol"] for q in receive_quotes(first)["quotes"]] == ["INFY"]
            assert [q["symbol"] for q in receive_quotes(second)["quotes"]] == ["TCS"]

            second.send_json({"type": "unsubscribe", "symbols": ["TCS"]})
            assert wait_until(lambda: hub.subscribed_symbols() == {"INFY"})

            connector.socket.push(pricing_frame("INFY.NS", 1510.0, now + timedelta(seconds=1)))
            assert receive_quotes(first)["quotes"][0]["ltp"] == 1510.0
            # Only the first browser still watches anything.
            assert service.cache.get("TCS").ltp == 3100.0


def test_an_unauthenticated_browser_is_closed_while_the_feed_is_live(
    client, make_token, market_instrument_factory, start_live_service,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    service, _connector = start_live_service()
    token = make_token("0123456789abcdef01234567", secret="not-the-secret")
    client.cookies.set("token", token)

    with client.websocket_connect("/api/quotes/stream?symbols=INFY") as browser:
        with pytest.raises(WebSocketDisconnect) as closed:
            browser.receive_json()

    assert closed.value.code == 1008
    assert service.is_streaming() is True


def test_a_database_outage_keeps_the_tick_and_recovers(
    market_instrument_factory, postgres_session_factory, start_live_service,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    service, _connector = start_live_service(flush_seconds=999)

    class DeadFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    working_factory = service._session_factory
    service._session_factory = DeadFactory()
    try:
        service.handle_stream_quote(
            {
                "id": "INFY.NS",
                "price": 1500.0,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "change": 0.0,
                "change_percent": 0.0,
            }
        )

        assert service.flush() == 0
        assert service.pending_count() == 1
        assert ltp(postgres_session_factory) == 1400.0
    finally:
        service._session_factory = working_factory

    assert service.flush() == 1
    assert service.pending_count() == 0
    assert ltp(postgres_session_factory) == 1500.0


def test_stop_flushes_the_last_tick_to_postgresql(
    market_instrument_factory, postgres_session_factory,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    connector = FakeConnector(FakeSocket())

    def feed_factory():
        return YahooQuoteFeed(
            ["INFY.NS"], service.handle_stream_quote, connect=connector,
            backoff_min=0.01,
        )

    service = QuoteService(
        session_factory=postgres_session_factory,
        feed_factory=feed_factory,
        flush_seconds=999,
    )
    service.start(enabled=True)
    try:
        assert wait_until(lambda: service.is_streaming())
        service.handle_stream_quote(
            {
                "id": "INFY.NS",
                "price": 1495.0,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "change": 0.0,
                "change_percent": 0.0,
            }
        )
        assert service.pending_count() == 1
    finally:
        service.stop()

    assert service.pending_count() == 0
    assert ltp(postgres_session_factory) == 1495.0


def test_a_provider_disconnect_reconnects_and_resumes_delivery(
    market_instrument_factory, postgres_session_factory, start_live_service,
):
    market_instrument_factory(symbol="INFY", ltp=1400.0)
    service, connector = start_live_service(fail_first=True)

    assert connector.calls >= 2
    assert service._feed.connections == 1

    service.handle_stream_quote(
        {
            "id": "INFY.NS",
            "price": 1505.0,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "change": 0.0,
            "change_percent": 0.0,
        }
    )
    assert service.pending_count() == 1
    assert service.flush() == 1
    assert ltp(postgres_session_factory) == 1505.0
