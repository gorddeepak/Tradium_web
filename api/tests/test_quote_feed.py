"""Focused tests for the upstream feed transport.

A fake connector replaces ``websockets.connect``, so every reconnect path runs
without a socket or a market session.
"""

import asyncio
import json
from pathlib import Path

from api.quote_feed import YahooQuoteFeed

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo_stream_frames.json"


def pricing_frames():
    with open(FIXTURES, encoding="utf-8") as handle:
        return [json.dumps(frame) for frame in json.load(handle)]


class FakeSocket:
    def __init__(self, frames=(), error=ConnectionError("connection closed")):
        self.frames = list(frames)
        self.error = error
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        raise self.error


class FakeConnector:
    """An async context manager that hands out one socket per connect call."""

    def __init__(self, sockets):
        self.sockets = list(sockets)
        self.cursor = 0
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        connector = self

        class Connection:
            async def __aenter__(self):
                socket = connector.sockets[connector.cursor]
                connector.cursor += 1
                return socket

            async def __aexit__(self, *_exc):
                return False

        return Connection()


def run_feed(feed):
    asyncio.run(feed.run())


def test_connects_subscribes_and_forwards_decoded_frames():
    frames = pricing_frames()
    socket = FakeSocket(frames[:2])
    connector = FakeConnector([socket])
    received = []

    feed = YahooQuoteFeed(
        ["INFY.NS", "TCS.NS"],
        lambda quote: (received.append(quote), feed.stop()),
        connect=connector,
        backoff_min=0.01,
    )

    run_feed(feed)

    assert len(connector.urls) == 1
    assert json.loads(socket.sent[0]) == {"subscribe": ["INFY.NS", "TCS.NS"]}
    assert len(received) == 1
    assert received[0]["id"] == "^NSEI"
    assert feed.state == "stopped"
    assert feed.connections == 1
    assert feed.connected_at is not None
    assert feed.last_tick_at is not None


def test_a_malformed_frame_is_skipped_without_stopping_the_feed():
    frames = pricing_frames()
    socket = FakeSocket(["not json", '{"type":"unknown"}', frames[0]])
    connector = FakeConnector([socket])
    received = []

    feed = YahooQuoteFeed(
        ["INFY.NS"],
        lambda quote: received.append(quote),
        connect=connector,
        backoff_min=0.01,
    )

    # Let it reconnect after the socket closes, then stop from a timer.
    async def scenario():
        loop = asyncio.get_running_loop()
        loop.call_later(0.2, feed.stop)
        await feed.run()

    asyncio.run(scenario())

    assert len(received) == 1
    assert received[0]["id"] == "^NSEI"


def test_a_disconnect_reconnects_with_backoff():
    frames = pricing_frames()
    first = FakeSocket([frames[0]])
    second = FakeSocket([frames[1]])
    connector = FakeConnector([first, second])
    received = []

    feed = YahooQuoteFeed(
        ["INFY.NS"],
        lambda quote: received.append(quote),
        connect=connector,
        backoff_min=0.01,
        backoff_max=0.02,
    )

    async def scenario():
        original = feed.on_quote

        def on_quote(quote):
            original(quote)
            if len(received) == 2:
                feed.stop()

        feed.on_quote = on_quote
        await feed.run()

    asyncio.run(scenario())

    assert feed.connections == 2
    assert len(received) == 2
    assert connector.cursor == 2


def test_stop_before_run_does_not_connect():
    connector = FakeConnector([])
    feed = YahooQuoteFeed(["INFY.NS"], lambda quote: None, connect=connector)
    feed.stop()

    run_feed(feed)

    assert connector.cursor == 0
    assert feed.state == "stopped"


def test_stop_interrupts_a_backoff_wait():
    class BrokenConnector:
        def __init__(self):
            self.calls = 0

        def __call__(self, url):
            self.calls += 1

            class Connection:
                async def __aenter__(self):
                    raise ConnectionError("provider unavailable")

                async def __aexit__(self, *_exc):
                    return False

            return Connection()

    connector = BrokenConnector()
    feed = YahooQuoteFeed(
        ["INFY.NS"],
        lambda quote: None,
        connect=connector,
        backoff_min=10,
        backoff_max=10,
    )

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, feed.stop)
        await asyncio.wait_for(feed.run(), timeout=2)

    asyncio.run(scenario())

    assert connector.calls == 1
    assert feed.state == "stopped"


def test_a_callback_error_does_not_drop_the_connection():
    frames = pricing_frames()
    socket = FakeSocket(frames[:2])
    connector = FakeConnector([socket])
    seen = []

    def on_quote(quote):
        seen.append(quote["id"])
        if len(seen) == 1:
            raise RuntimeError("handler bug")
        feed.stop()

    feed = YahooQuoteFeed(
        ["INFY.NS"], on_quote, connect=connector, backoff_min=0.01
    )

    run_feed(feed)

    assert len(seen) == 2
    assert feed.connections == 1
