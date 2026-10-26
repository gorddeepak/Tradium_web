"""Tests for live watchlist quotes over WebSockets.

Authentication uses the same ``token`` cookie as the REST routes. The delivery
tests seed PostgreSQL directly, then call the publisher the way ``price_sync``
does after its commit. ``test_price_sync_publishes_after_persisting`` covers
that job seam end to end with the provider patched out.
"""

import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from api.jobs import price_sync
from api.market_store import persist_price_quotes
from api.postgres.models import Instrument, LatestQuote, Watchlist
from api.watchlist_stream import (
    hub,
    publish_persisted_quotes,
    watchlist_quote_updates,
)

STREAM = "/api/watchlist/stream"
NOW = datetime(2026, 10, 25, 10, 0, 0, 123000, tzinfo=timezone.utc)
CREATED = datetime(2026, 9, 1, 4, 15, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_hub():
    hub.reset()
    yield
    hub.reset()


def add_watchlist(session_factory, user_id, symbol, name=None):
    item = Watchlist(
        id=secrets.token_hex(12),
        user_id=user_id,
        symbol=symbol,
        name=name or symbol,
        exchange="NSE",
        created_at=CREATED,
        updated_at=CREATED,
        version=0,
    )
    with session_factory() as session:
        session.add(item)
        session.commit()
    return item.id


def quote_ltp(session_factory, symbol):
    with session_factory() as session:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol)
        )
        quote = session.get(LatestQuote, instrument.id) if instrument else None
        return quote.ltp if quote else None


def wait_until(predicate, attempts=100):
    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(0.01)
    return False


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
    bad_token = make_token("0123456789abcdef01234567", secret="not-the-secret")

    with connect(client, bad_token) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()

    assert closed.value.code == 1008


def test_each_user_receives_only_their_own_watchlist(
    book_client,
    book_session_factory,
    book_user_factory,
    market_instrument_factory,
    make_token,
):
    alice = book_user_factory()
    bob = book_user_factory()
    market_instrument_factory(symbol="INFY", ltp=1500.0, day_change_pct=0.8)
    market_instrument_factory(symbol="RELIANCE", ltp=2400.0, day_change_pct=-0.4)
    add_watchlist(book_session_factory, alice, "INFY")
    add_watchlist(book_session_factory, bob, "RELIANCE")

    with connect(book_client, make_token(alice)) as alice_socket:
        with connect(book_client, make_token(bob)) as bob_socket:
            assert hub.subscriber_count() == 2
            assert publish_persisted_quotes(
                book_session_factory, ["INFY", "RELIANCE"]
            ) == 2

            alice_frame = alice_socket.receive_json()
            bob_frame = bob_socket.receive_json()

    assert [quote["symbol"] for quote in alice_frame["quotes"]] == ["INFY"]
    assert [quote["symbol"] for quote in bob_frame["quotes"]] == ["RELIANCE"]
    assert alice_frame["type"] == bob_frame["type"] == "quotes"


def test_the_frame_carries_the_committed_postgres_quote(
    book_client,
    book_session_factory,
    book_user_factory,
    market_instrument_factory,
    make_token,
):
    user = book_user_factory()
    market_instrument_factory(symbol="INFY", ltp=1500.0, day_change_pct=0.8)
    add_watchlist(book_session_factory, user, "INFY")

    with connect(book_client, make_token(user)) as socket:
        persist_price_quotes(
            book_session_factory,
            [
                {
                    "symbol": "INFY",
                    "name": "Infosys",
                    "kind": "stock",
                    "row": {
                        "regularMarketPrice": 1512.5,
                        "regularMarketChangePercent": 1.25,
                        "regularMarketTime": NOW.timestamp(),
                    },
                }
            ],
            now=NOW,
        )
        assert publish_persisted_quotes(book_session_factory, ["INFY"]) == 1
        frame = socket.receive_json()

    quote = frame["quotes"][0]
    assert quote["ltp"] == 1512.5
    assert quote["dayChangePct"] == 1.25
    assert quote["updatedAt"] == "2026-10-25T10:00:00.123Z"
    assert quote_ltp(book_session_factory, "INFY") == Decimal("1512.5000")


def test_a_watchlist_row_without_a_quote_is_omitted(
    book_client,
    book_session_factory,
    book_user_factory,
    market_instrument_factory,
    make_token,
):
    user = book_user_factory()
    market_instrument_factory(symbol="INFY", quote=False)
    add_watchlist(book_session_factory, user, "INFY")

    with connect(book_client, make_token(user)) as _socket:
        assert watchlist_quote_updates(book_session_factory, ["INFY"]) == {}
        assert publish_persisted_quotes(book_session_factory, ["INFY"]) == 0


def test_a_failed_quote_read_is_swallowed_and_the_socket_survives(
    book_client,
    book_session_factory,
    book_user_factory,
    market_instrument_factory,
    make_token,
):
    user = book_user_factory()
    market_instrument_factory(symbol="INFY", ltp=1500.0)
    add_watchlist(book_session_factory, user, "INFY")

    def broken_session_factory():
        raise RuntimeError("database is unavailable")

    with connect(book_client, make_token(user)) as socket:
        assert publish_persisted_quotes(broken_session_factory, ["INFY"]) == 0
        assert publish_persisted_quotes(book_session_factory, ["INFY"]) == 1
        assert socket.receive_json()["quotes"][0]["symbol"] == "INFY"


def test_disconnect_removes_the_subscription(
    book_client,
    book_session_factory,
    book_user_factory,
    market_instrument_factory,
    make_token,
):
    user = book_user_factory()
    market_instrument_factory(symbol="INFY")
    add_watchlist(book_session_factory, user, "INFY")

    with connect(book_client, make_token(user)):
        assert hub.subscriber_count() == 1

    assert wait_until(lambda: hub.subscriber_count() == 0)


def test_price_sync_publishes_after_persisting(
    book_client,
    book_session_factory,
    book_user_factory,
    make_token,
    monkeypatch,
):
    user = book_user_factory()
    add_watchlist(book_session_factory, user, "INFY")
    monkeypatch.setattr(price_sync, "is_market_open", lambda: True)
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")
    monkeypatch.setattr(
        price_sync,
        "fetch_quotes",
        lambda tickers: {
            "INFY.NS": {
                "regularMarketPrice": 1512.5,
                "regularMarketChangePercent": 1.25,
                "regularMarketTime": NOW.timestamp(),
            }
        },
    )

    with connect(book_client, make_token(user)) as socket:
        price_sync.run_sync(book_session_factory, now=NOW)
        frame = socket.receive_json()

    assert frame["quotes"][0]["ltp"] == 1512.5
    assert quote_ltp(book_session_factory, "INFY") == Decimal("1512.5000")


def test_price_sync_does_not_publish_when_persistence_fails(
    book_session_factory,
    book_user_factory,
    monkeypatch,
):
    user = book_user_factory()
    add_watchlist(book_session_factory, user, "INFY")
    published = []

    def fail(*_args, **_kwargs):
        raise RuntimeError("database is unavailable")

    monkeypatch.setattr(price_sync, "is_market_open", lambda: True)
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")
    monkeypatch.setattr(price_sync, "persist_price_quotes", fail)
    monkeypatch.setattr(
        price_sync,
        "publish_persisted_quotes",
        lambda *args: published.append(args),
    )
    monkeypatch.setattr(
        price_sync,
        "fetch_quotes",
        lambda tickers: {
            "INFY.NS": {
                "regularMarketPrice": 1512.5,
                "regularMarketChangePercent": 1.25,
                "regularMarketTime": NOW.timestamp(),
            }
        },
    )

    price_sync.run_sync(book_session_factory, now=NOW)

    assert published == []
