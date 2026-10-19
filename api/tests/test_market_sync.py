"""Focused tests for the quote provider, market-hours gate and cache sync.

No network and no real database: the provider is patched at the seam
(`api.market_data._request_quotes` / `fetch_quotes` / `fetch_sector`) and the
database is mongomock. The one part mongomock cannot run is `bulk_write`, so
`quote_operations` is asserted directly and the real write is covered by
`test_mongo_integration.py`.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pymongo import UpdateOne

from api import market_data
from api import scheduler
from api.data.nifty50 import INDICES, NIFTY50
from api.jobs import market_sync as sync
from api.market_hours import IST, is_market_open


# --------------------------------------------------------------------------
# The universe
# --------------------------------------------------------------------------


def test_universe_matches_the_express_seed():
    assert len(NIFTY50) == 50
    assert len(INDICES) == 3
    assert len(sync.TICKERS) == 53
    # Indices keep Yahoo's own ticker; stocks get .NS.
    assert "^NSEI" in sync.BY_TICKER
    assert "RELIANCE.NS" in sync.BY_TICKER
    assert sync.BY_TICKER["^NSEI"]["kind"] == "index"
    assert sync.BY_TICKER["RELIANCE.NS"] == {
        "symbol": "RELIANCE",
        "name": "Reliance Industries",
        "kind": "stock",
    }
    # M&M is the one symbol with a non-alphanumeric character.
    assert "M&M.NS" in sync.BY_TICKER


# --------------------------------------------------------------------------
# Market hours
# --------------------------------------------------------------------------


def _ist(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


@pytest.mark.parametrize(
    "moment, expected",
    [
        (_ist(2026, 10, 19, 9, 14), False),  # Monday, one minute early
        (_ist(2026, 10, 19, 9, 15), True),  # open, inclusive
        (_ist(2026, 10, 19, 12, 0), True),
        (_ist(2026, 10, 19, 15, 30), True),  # close, inclusive
        (_ist(2026, 10, 19, 15, 30, 59), True),  # whole-minute comparison
        (_ist(2026, 10, 19, 15, 31), False),
        (_ist(2026, 10, 24, 12, 0), False),  # Saturday
        (_ist(2026, 10, 25, 12, 0), False),  # Sunday
    ],
)
def test_market_open_window(moment, expected):
    assert is_market_open(moment) is expected


def test_market_open_reads_the_clock_as_ist():
    # 09:45 UTC is 15:15 IST -- open -- while the naive UTC hour is 09.
    assert is_market_open(datetime(2026, 10, 19, 9, 45, tzinfo=timezone.utc)) is True
    # 04:00 UTC is 09:30 IST.
    assert is_market_open(datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)) is True
    # 03:45 UTC is 09:15 IST.
    assert is_market_open(datetime(2026, 10, 19, 3, 44, tzinfo=timezone.utc)) is False


# --------------------------------------------------------------------------
# fetch_quote -- the shape the order engine and square-off consume
# --------------------------------------------------------------------------


def _row(**overrides):
    row = {
        "symbol": "RELIANCE.NS",
        "regularMarketPrice": 1202.8,
        "regularMarketChange": -8.4,
        "regularMarketChangePercent": -0.69,
    }
    row.update(overrides)
    return row


def _serve(monkeypatch, rows):
    monkeypatch.setattr(market_data, "_request_quotes", lambda tickers: rows)


def test_fetch_quote_reduces_to_the_documented_shape(monkeypatch):
    _serve(monkeypatch, [_row()])

    assert market_data.fetch_quote("RELIANCE") == {"ltp": 1202.8, "dayChangePct": -0.69}


def test_fetch_quote_adds_the_ns_suffix_but_leaves_indices_alone(monkeypatch):
    asked = []

    def fake_request(tickers):
        asked.append(tickers)
        return [_row(symbol="^NSEI", regularMarketPrice=22888.95)]

    monkeypatch.setattr(market_data, "_request_quotes", fake_request)

    market_data.fetch_quote("^NSEI")
    market_data.fetch_quote("RELIANCE")

    assert asked == [["^NSEI"], ["RELIANCE.NS"]]


def test_fetch_quote_returns_none_for_an_unknown_symbol(monkeypatch):
    _serve(monkeypatch, [])  # Yahoo answers 200 with an empty result

    assert market_data.fetch_quote("NOTAREALSYMBOL") is None


@pytest.mark.parametrize("price", [None, 0, -1.0, "1202.8", True])
def test_fetch_quote_rejects_an_unusable_price(monkeypatch, price):
    _serve(monkeypatch, [_row(regularMarketPrice=price)])

    assert market_data.fetch_quote("RELIANCE") is None


def test_fetch_quote_tolerates_a_missing_change_percent(monkeypatch):
    row = _row()
    del row["regularMarketChangePercent"]
    _serve(monkeypatch, [row])

    assert market_data.fetch_quote("RELIANCE") == {"ltp": 1202.8, "dayChangePct": 0}


def test_fetch_quote_swallows_a_provider_error(monkeypatch):
    def explode(tickers):
        raise market_data.MarketDataError("Yahoo is down")

    monkeypatch.setattr(market_data, "_request_quotes", explode)

    # The callers have no handler of their own: raising here would be a 500.
    assert market_data.fetch_quote("RELIANCE") is None


def test_fetch_quote_picks_its_own_ticker_out_of_a_batch(monkeypatch):
    _serve(monkeypatch, [_row(symbol="INFY.NS", regularMarketPrice=1500.0), _row()])

    assert market_data.fetch_quote("RELIANCE") == {"ltp": 1202.8, "dayChangePct": -0.69}


# --------------------------------------------------------------------------
# fetch_quote_row -- the raw row the detail routes read
# --------------------------------------------------------------------------


def test_fetch_quote_row_returns_the_raw_row(monkeypatch):
    _serve(monkeypatch, [_row(fiftyTwoWeekHigh=1611.8, longName="Reliance Industries Limited")])

    row = market_data.fetch_quote_row("RELIANCE")

    assert row["fiftyTwoWeekHigh"] == 1611.8
    assert row["longName"] == "Reliance Industries Limited"


def test_fetch_quote_row_propagates_a_provider_failure(monkeypatch):
    """Express's `quote()` throws, and the route's bare catch turns that into a 404."""

    def explode(tickers):
        raise market_data.MarketDataError("Yahoo is down")

    monkeypatch.setattr(market_data, "_request_quotes", explode)

    with pytest.raises(market_data.MarketDataError):
        market_data.fetch_quote_row("RELIANCE")


def test_fetch_quotes_indexes_rows_by_ticker(monkeypatch):
    _serve(monkeypatch, [_row(), _row(symbol="^NSEI", regularMarketPrice=22888.95)])

    found = market_data.fetch_quotes(["RELIANCE.NS", "^NSEI"])

    assert set(found) == {"RELIANCE.NS", "^NSEI"}


# --------------------------------------------------------------------------
# The bulk upsert mapping
# --------------------------------------------------------------------------


def test_operations_cover_all_nine_quote_fields():
    quotes = {
        "RELIANCE.NS": {
            "symbol": "RELIANCE.NS",
            "regularMarketPrice": 1202.8,
            "regularMarketChange": -8.4,
            "regularMarketChangePercent": -0.69,
            "regularMarketPreviousClose": 1211.2,
            "regularMarketVolume": 15138916,
            "marketCap": 16276858601472,
        }
    }

    operations, seen = sync.quote_operations(quotes)

    assert len(operations) == 1
    assert seen == {"RELIANCE.NS"}
    operation = operations[0]
    assert isinstance(operation, UpdateOne)
    assert operation._filter == {"symbol": "RELIANCE"}
    assert operation._doc["$set"] == {
        "name": "Reliance Industries",
        "kind": "stock",
        "ltp": 1202.8,
        "dayChange": -8.4,
        "dayChangePct": -0.69,
        "prevClose": 1211.2,
        "volume": 15138916,
        "marketCap": 16276858601472,
        "updatedAt": operation._doc["$set"]["updatedAt"],
    }
    assert operation._upsert is True


def test_operations_leave_sector_to_the_backfill():
    """A price cycle must not blank a sector the backfill already filled."""
    operations, _ = sync.quote_operations({"RELIANCE.NS": _row()})

    assert "sector" not in operations[0]._doc["$set"]
    # On insert only, matching Mongoose's model default.
    assert operations[0]._doc["$setOnInsert"]["sector"] == ""


def test_operations_supply_mongoose_insert_fields():
    operations, _ = sync.quote_operations({"RELIANCE.NS": _row()})

    on_insert = operations[0]._doc["$setOnInsert"]
    assert on_insert["__v"] == 0
    assert "createdAt" in on_insert


def test_operations_turn_null_fields_into_zero():
    """Indices have no marketCap; Express writes 0 via `?? 0`."""
    operations, _ = sync.quote_operations(
        {"^NSEI": {"symbol": "^NSEI", "regularMarketPrice": 22888.95, "marketCap": None}}
    )

    set_values = operations[0]._doc["$set"]
    assert set_values["marketCap"] == 0
    assert set_values["volume"] == 0
    assert set_values["dayChange"] == 0
    assert set_values["kind"] == "index"
    assert set_values["name"] == "NIFTY 50"


def test_operations_keep_a_real_zero():
    """`??` only coalesces null, so a genuine 0 stays 0."""
    operations, _ = sync.quote_operations({"^NSEI": {"symbol": "^NSEI", "regularMarketVolume": 0}})

    assert operations[0]._doc["$set"]["volume"] == 0


def test_operations_ignore_a_ticker_we_did_not_ask_for():
    operations, seen = sync.quote_operations({"SOMETHINGELSE.NS": _row(symbol="SOMETHINGELSE.NS")})

    assert operations == []
    assert seen == set()


# --------------------------------------------------------------------------
# sync_quotes / backfill_sectors / market_sync
# --------------------------------------------------------------------------


def test_sync_quotes_reports_the_symbols_yahoo_did_not_return(database, monkeypatch):
    monkeypatch.setattr(
        sync, "fetch_quotes", lambda tickers: {"RELIANCE.NS": _row()}
    )
    written = {}
    monkeypatch.setattr(
        database["marketquotes"], "bulk_write", lambda ops, **kwargs: written.setdefault("ops", ops)
    )

    cached, missing = sync.sync_quotes(database)

    assert cached == 1
    assert len(written["ops"]) == 1
    assert "RELIANCE.NS" not in missing
    assert "^NSEI" in missing
    assert len(missing) == 52


def test_sync_quotes_keeps_the_previous_cache_on_failure(database, monkeypatch):
    def explode(tickers):
        raise market_data.MarketDataError("Yahoo is down")

    monkeypatch.setattr(sync, "fetch_quotes", explode)

    def must_not_write(*args, **kwargs):
        raise AssertionError("a failed sync must not write")

    monkeypatch.setattr(database["marketquotes"], "bulk_write", must_not_write)

    assert sync.sync_quotes(database) == (0, [])


def test_sync_quotes_writes_nothing_when_no_quote_matches(database, monkeypatch):
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: {})

    def must_not_write(*args, **kwargs):
        raise AssertionError("nothing to write")

    monkeypatch.setattr(database["marketquotes"], "bulk_write", must_not_write)

    cached, missing = sync.sync_quotes(database)

    assert cached == 0
    assert len(missing) == 53


def test_backfill_fills_only_the_stock_sectors_it_resolves(
    database, monkeypatch, market_quote_factory
):
    database["marketquotes"].insert_many(
        [
            market_quote_factory(symbol="INFY", kind="stock", sector=""),
            market_quote_factory(symbol="TCS", kind="stock", sector=""),
            market_quote_factory(symbol="ITC", kind="stock", sector="Energy"),
            market_quote_factory(symbol="^NSEI", kind="index", sector=""),
        ]
    )
    sectors = {"INFY": "Technology", "TCS": ""}  # TCS has no profile
    monkeypatch.setattr(sync, "fetch_sector", lambda symbol: sectors[symbol])

    assert sync.backfill_sectors(database) == 1
    assert database["marketquotes"].find_one({"symbol": "INFY"})["sector"] == "Technology"
    # Unresolved stays empty and is retried on a later run.
    assert database["marketquotes"].find_one({"symbol": "TCS"})["sector"] == ""
    # An index is never asked.
    assert database["marketquotes"].find_one({"symbol": "^NSEI"})["sector"] == ""


def test_backfill_is_capped_per_run(database, monkeypatch, market_quote_factory):
    database["marketquotes"].insert_many(
        [market_quote_factory(symbol=f"TCK{i}", sector="") for i in range(15)]
    )
    monkeypatch.setattr(sync, "fetch_sector", lambda symbol: "Technology")

    assert sync.backfill_sectors(database) == 10


def test_backfill_logs_a_provider_error_and_keeps_going(
    database, monkeypatch, market_quote_factory
):
    database["marketquotes"].insert_many(
        [
            market_quote_factory(symbol="INFY", sector=""),
            market_quote_factory(symbol="TCS", sector=""),
        ]
    )

    def flaky(symbol):
        if symbol == "INFY":
            raise market_data.MarketDataError("profile lookup failed")
        return "Technology"

    monkeypatch.setattr(sync, "fetch_sector", flaky)

    assert sync.backfill_sectors(database) == 1
    assert database["marketquotes"].find_one({"symbol": "TCS"})["sector"] == "Technology"


def test_market_sync_skips_the_quote_refresh_when_closed_with_a_warm_cache(
    database, monkeypatch, market_quote_factory
):
    database["marketquotes"].insert_one(market_quote_factory(symbol="INFY"))
    monkeypatch.setattr(sync, "is_market_open", lambda: False)
    monkeypatch.setattr(
        sync, "sync_quotes", lambda db: pytest.fail("must not quote while closed")
    )
    monkeypatch.setattr(sync, "backfill_sectors", lambda db: 0)

    sync.market_sync(database)  # no exception


def test_market_sync_syncs_a_cold_cache_even_when_closed(database, monkeypatch):
    monkeypatch.setattr(sync, "is_market_open", lambda: False)
    called = []
    monkeypatch.setattr(sync, "sync_quotes", lambda db: called.append("quotes") or (0, []))
    monkeypatch.setattr(sync, "backfill_sectors", lambda db: 0)

    sync.market_sync(database)

    assert called == ["quotes"]


def test_market_sync_survives_an_unexpected_error(database, monkeypatch):
    def explode(db):
        raise RuntimeError("boom")

    monkeypatch.setattr(database["marketquotes"], "estimated_document_count", lambda: 0)
    monkeypatch.setattr(sync, "sync_quotes", explode)
    monkeypatch.setattr(sync, "backfill_sectors", lambda db: 0)

    sync.market_sync(database)  # logged, not raised

    # The lock must be released, or every later tick would be skipped.
    assert not sync._sync_lock.locked()


def test_market_sync_skips_a_tick_while_one_is_running(database, monkeypatch):
    entered = []

    def slow_sync(db):
        entered.append(True)
        # A second tick arriving now must be refused.
        sync.market_sync(db)
        return 0, []

    monkeypatch.setattr(database["marketquotes"], "estimated_document_count", lambda: 0)
    monkeypatch.setattr(sync, "sync_quotes", slow_sync)
    monkeypatch.setattr(sync, "backfill_sectors", lambda db: 0)

    sync.market_sync(database)

    assert entered == [True]  # the nested call returned without syncing


# --------------------------------------------------------------------------
# Scheduler ownership
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_scheduler_switch_accepts_the_documented_truthy_values(monkeypatch, value):
    monkeypatch.setenv("MARKET_SYNC_ENABLED", value)

    assert scheduler.market_sync_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_scheduler_switch_is_off_for_anything_else(monkeypatch, value):
    monkeypatch.setenv("MARKET_SYNC_ENABLED", value)

    assert scheduler.market_sync_enabled() is False


def test_scheduler_switch_defaults_to_off(monkeypatch):
    monkeypatch.delenv("MARKET_SYNC_ENABLED", raising=False)

    assert scheduler.market_sync_enabled() is False


def test_scheduler_runs_once_immediately_then_stops(database, monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "market_sync", lambda db: ticks.append(db))

    instance = scheduler.MarketSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.stop()

    # The immediate tick populates a cold cache, like Express's call on connect.
    assert ticks == [database]


def test_scheduler_does_not_start_twice(database, monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "market_sync", lambda db: ticks.append(db))

    instance = scheduler.MarketSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.start()  # a second start must not spawn another thread
    instance.stop()

    assert len(ticks) == 1


def test_scheduler_survives_a_failing_tick(database, monkeypatch):
    calls = []

    def flaky(db):
        calls.append(db)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "market_sync", flaky)

    instance = scheduler.MarketSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.stop()

    # The thread logged the failure instead of dying before stop() could join it.
    assert calls == [database]
    assert instance._thread is None


def test_injected_test_database_never_starts_the_scheduler(database, monkeypatch):
    """Even with the switch on, a test app must not touch the network."""
    from api.main import create_app

    monkeypatch.setenv("MARKET_SYNC_ENABLED", "true")
    started = []
    monkeypatch.setattr(
        scheduler.MarketSyncScheduler, "start", lambda self: started.append(self.db)
    )

    with TestClient(create_app(database=database)) as client:
        assert client.get("/api/health").status_code == 200

    assert started == []
