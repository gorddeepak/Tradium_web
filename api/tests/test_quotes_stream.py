"""Tests for the generic quote WebSocket route.

These need no PostgreSQL: authentication reads the JWT, and the snapshot comes
from the in-memory cache. The watchlist endpoint keeps its own suite in
``test_watchlist_stream.py``; this file only checks that the general channel
authenticates, reports status and delivers frames.
"""

from datetime import datetime, timezone
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from api.quote_service import quote_service
from api.quote_stream import hub

STREAM = "/api/quotes/stream?symbols=INFY,TCS"
NOW = datetime(2026, 10, 30, 10, 0, 0, 0, tzinfo=timezone.utc)


def wait_until(predicate, attempts=100):
    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def clean_state():
    hub.reset()
    quote_service.cache.clear()
    yield
    hub.reset()
    quote_service.cache.clear()


def connect(client, token=None):
    """Open the stream with the same ``token`` cookie the REST routes use."""
    if token is not None:
        client.cookies.set("token", token)
    return client.websocket_connect(STREAM)


def test_a_missing_cookie_is_closed_with_policy_violation(client):
    with connect(client) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()

    assert closed.value.code == 1008


def test_an_invalid_token_is_closed_with_policy_violation(client, make_token):
    token = make_token("0123456789abcdef01234567", secret="not-the-secret")

    with connect(client, token) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()

    assert closed.value.code == 1008


def test_connect_reports_status_and_a_cached_snapshot(client, make_token, user_id):
    quote_service.cache.record("INFY", 1512.5, 12.5, 0.83, NOW, NOW)

    with connect(client, make_token(user_id)) as socket:
        status = socket.receive_json()
        snapshot = socket.receive_json()

    assert status["type"] == "status"
    assert status["enabled"] is False
    assert status["state"] == "disabled"
    assert status["streaming"] is False
    assert status["staleAfterSeconds"] > 0

    assert snapshot["type"] == "quotes"
    assert [quote["symbol"] for quote in snapshot["quotes"]] == ["INFY"]
    assert snapshot["quotes"][0]["ltp"] == 1512.5
    assert snapshot["quotes"][0]["live"] is True
    assert snapshot["quotes"][0]["restored"] is False


def test_a_restored_snapshot_is_not_labeled_live(client, make_token, user_id):
    quote_service.cache.restore("INFY", 1400.0, 0.0, 0.0, NOW, NOW)

    with connect(client, make_token(user_id)) as socket:
        socket.receive_json()  # status
        snapshot = socket.receive_json()

    assert snapshot["quotes"][0]["live"] is False
    assert snapshot["quotes"][0]["restored"] is True
    assert snapshot["quotes"][0]["receivedAt"] is None


def test_connect_without_cached_quotes_sends_only_status(client, make_token, user_id):
    with connect(client, make_token(user_id)) as socket:
        first = socket.receive_json()
        assert wait_until(lambda: hub.subscriber_count() == 1)

        # A status frame is always sent; the snapshot is omitted when empty.
        hub.publish_status({"state": "disabled"})
        second = socket.receive_json()

    assert first["type"] == "status"
    assert second["type"] == "status"


def test_a_subscribed_symbol_gets_its_cached_snapshot(client, make_token, user_id):
    quote_service.cache.record("RELIANCE", 2400.0, -8.0, -0.33, NOW, NOW)

    with connect(client, make_token(user_id)) as socket:
        socket.receive_json()  # status
        socket.send_json({"type": "subscribe", "symbols": ["RELIANCE"]})
        frame = socket.receive_json()

    assert frame["type"] == "quotes"
    assert frame["quotes"][0]["symbol"] == "RELIANCE"
    assert frame["quotes"][0]["ltp"] == 2400.0


def test_published_frames_reach_only_subscribed_symbols(client, make_token, user_id):
    with connect(client, make_token(user_id)) as socket:
        socket.receive_json()  # status
        assert wait_until(lambda: hub.subscriber_count() == 1)

        hub.publish(
            {
                "INFY": {"symbol": "INFY", "ltp": 1500.0, "live": True},
                "TCS": {"symbol": "TCS", "ltp": 3000.0, "live": True},
                "WIPRO": {"symbol": "WIPRO", "ltp": 250.0, "live": True},
            }
        )
        frame = socket.receive_json()

    assert frame["type"] == "quotes"
    assert [quote["symbol"] for quote in frame["quotes"]] == ["INFY", "TCS"]


def test_disconnect_removes_the_subscription(client, make_token, user_id):
    with connect(client, make_token(user_id)) as socket:
        socket.receive_json()  # status
        assert wait_until(lambda: hub.subscriber_count() == 1)

    assert wait_until(lambda: hub.subscriber_count() == 0)
