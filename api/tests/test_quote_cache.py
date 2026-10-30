"""Focused tests for the in-memory live quote cache.

No database and no provider: these pin the ordering and freshness rules that
protect the browser from an older price.
"""

from datetime import datetime, timedelta, timezone

import pytest

from api.quote_cache import QuoteCache, is_stale

NOW = datetime(2026, 10, 25, 10, 0, 0, 5000, tzinfo=timezone.utc)


def record(cache, **overrides):
    values = {
        "symbol": "INFY",
        "ltp": 1500.0,
        "day_change": 12.0,
        "day_change_pct": 0.8,
        "source_time": NOW,
        "received_at": NOW,
        "volume": 1000,
    }
    values.update(overrides)
    return cache.record(**values)


def test_a_valid_tick_is_cached_as_live():
    cache = QuoteCache()

    quote = record(cache)

    assert quote is not None
    assert quote.symbol == "INFY"
    assert quote.ltp == 1500.0
    assert quote.day_change_pct == 0.8
    assert quote.source_time == NOW
    assert quote.received_at == NOW
    assert quote.updated_at == NOW
    assert quote.live is True
    assert cache.get("infy") is quote


@pytest.mark.parametrize("price", [0, -1, None, "1500", float("nan"), float("inf"), True])
def test_an_unusable_price_is_rejected(price):
    cache = QuoteCache()

    assert record(cache, ltp=price) is None
    assert len(cache) == 0


def test_a_tick_without_a_symbol_or_source_time_is_rejected():
    cache = QuoteCache()

    assert record(cache, symbol="") is None
    assert record(cache, source_time=None) is None
    assert len(cache) == 0


def test_a_naive_source_time_is_read_as_utc():
    cache = QuoteCache()
    naive = NOW.replace(tzinfo=None)

    quote = record(cache, source_time=naive)

    assert quote.source_time == NOW


def test_an_older_or_equal_tick_cannot_overwrite_a_newer_one():
    cache = QuoteCache()
    record(cache, ltp=1500.0)

    assert record(cache, ltp=1400.0, source_time=NOW - timedelta(seconds=1)) is None
    assert record(cache, ltp=1400.0, source_time=NOW) is None
    assert cache.get("INFY").ltp == 1500.0

    newer = record(cache, ltp=1515.0, source_time=NOW + timedelta(seconds=1))
    assert newer.ltp == 1515.0
    assert cache.get("INFY").ltp == 1515.0


def test_a_restored_quote_is_not_live_and_has_no_receive_time():
    cache = QuoteCache()
    updated_at = NOW - timedelta(minutes=5)

    quote = cache.restore("INFY", 1500.0, 12.0, 0.8, NOW, updated_at)

    assert quote.live is False
    assert quote.received_at is None
    assert quote.updated_at == updated_at
    assert quote.source_time == NOW


def test_a_restored_quote_never_overwrites_a_live_tick():
    cache = QuoteCache()
    live = record(cache, ltp=1510.0)

    restored = cache.restore(
        "INFY", 1400.0, 0.0, 0.0, NOW + timedelta(minutes=1), NOW
    )

    assert restored is None
    assert cache.get("INFY").ltp == live.ltp
    assert cache.get("INFY").live is True


def test_a_persisted_row_only_replaces_an_older_persisted_row():
    cache = QuoteCache()
    cache.restore("INFY", 1500.0, 0.0, 0.0, NOW, NOW)

    stale = cache.restore("INFY", 1400.0, 0.0, 0.0, NOW - timedelta(seconds=1), NOW)
    fresh = cache.restore("INFY", 1520.0, 0.0, 0.0, NOW + timedelta(seconds=1), NOW)

    assert stale is None
    assert fresh is not None
    assert cache.get("INFY").ltp == 1520.0
    assert cache.get("INFY").live is False


@pytest.mark.parametrize("price", [0, -5, None, float("nan")])
def test_restore_rejects_an_unusable_price(price):
    cache = QuoteCache()

    assert cache.restore("INFY", price, 0.0, 0.0, NOW, NOW) is None
    assert len(cache) == 0


def test_snapshot_filters_and_keeps_every_requested_symbol():
    cache = QuoteCache()
    record(cache, symbol="INFY")
    record(cache, symbol="TCS", ltp=3000.0)
    record(cache, symbol="RELIANCE", ltp=2400.0)

    snapshot = cache.snapshot(["INFY", "TCS"])

    assert {quote.symbol for quote in snapshot} == {"INFY", "TCS"}
    assert len(cache.snapshot()) == 3
    assert cache.snapshot([]) == []


def test_staleness_uses_the_provider_time():
    cache = QuoteCache()
    quote = record(cache)

    assert is_stale(quote, NOW, 60) is False
    assert is_stale(quote, NOW + timedelta(seconds=61), 60) is True
    assert is_stale(quote, NOW + timedelta(hours=1), 60) is True
    assert is_stale(quote, NOW - timedelta(hours=1), 60) is True


def test_a_quote_without_a_source_time_is_always_stale():
    cache = QuoteCache()
    quote = cache.restore("INFY", 1500.0, 0.0, 0.0, None, NOW)

    assert is_stale(quote, NOW, 60) is True
