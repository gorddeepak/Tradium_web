"""Focused tests for the quote provider, market-hours gate and market sync.

No network: the provider is patched at the seam
(`api.market_data._request_quotes` / `fetch_quotes` / `fetch_sector`). Database
writes and reads use PostgreSQL and are skipped unless TEST_DATABASE_URL is
set; there is no SQLite fallback. MongoDB is no longer touched by market sync.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api import market_data
from api import scheduler
from api.data.nifty50 import INDICES, NIFTY50
from api.jobs import market_sync as sync
from api.market_hours import IST, is_market_open
from api.postgres.models import Instrument, LatestQuote


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

    assert market_data.fetch_quote("RELIANCE") == {
        "ltp": 1202.8,
        "dayChangePct": -0.69,
        "sourceTime": None,
    }


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

    assert market_data.fetch_quote("RELIANCE") == {
        "ltp": 1202.8,
        "dayChangePct": 0,
        "sourceTime": None,
    }


def test_fetch_quote_carries_the_provider_source_time(monkeypatch):
    moment = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    _serve(monkeypatch, [_row(regularMarketTime=moment.timestamp())])

    quote = market_data.fetch_quote("RELIANCE")

    assert quote["sourceTime"] == moment
    assert quote["sourceTime"].tzinfo is timezone.utc


def test_fetch_quote_swallows_a_provider_error(monkeypatch):
    def explode(tickers):
        raise market_data.MarketDataError("Yahoo is down")

    monkeypatch.setattr(market_data, "_request_quotes", explode)

    # The callers have no handler of their own: raising here would be a 500.
    assert market_data.fetch_quote("RELIANCE") is None


def test_fetch_quote_picks_its_own_ticker_out_of_a_batch(monkeypatch):
    _serve(monkeypatch, [_row(symbol="INFY.NS", regularMarketPrice=1500.0), _row()])

    assert market_data.fetch_quote("RELIANCE") == {
        "ltp": 1202.8,
        "dayChangePct": -0.69,
        "sourceTime": None,
    }


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


def test_fetch_quotes_deduplicates_before_the_provider_request(monkeypatch):
    asked = []

    def fake_request(tickers):
        asked.append(tickers)
        return [_row()]

    monkeypatch.setattr(market_data, "_request_quotes", fake_request)

    market_data.fetch_quotes(["RELIANCE.NS", "RELIANCE.NS", "^NSEI"])

    assert asked == [["RELIANCE.NS", "^NSEI"]]


# --------------------------------------------------------------------------
# PostgreSQL persistence
# --------------------------------------------------------------------------


def _quote(session_factory, symbol):
    with session_factory() as session:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol)
        )
        if instrument is None:
            return None, None
        quote = session.get(LatestQuote, instrument.id)
        return instrument, quote


def _instrument_count(session_factory, **filters):
    with session_factory() as session:
        statement = select(func.count()).select_from(Instrument)
        for column, value in filters.items():
            statement = statement.where(getattr(Instrument, column) == value)
        return session.scalar(statement)


def _all_market_rows():
    rows = {}
    for symbol, _name in INDICES:
        rows[symbol] = _row(
            symbol=symbol,
            regularMarketPrice=22888.95,
            regularMarketChange=-257.2,
            regularMarketChangePercent=-1.11,
            regularMarketPreviousClose=23146.15,
            regularMarketVolume=0,
            marketCap=None,
        )
    for symbol, _name in NIFTY50:
        rows[f"{symbol}.NS"] = _row(
            symbol=f"{symbol}.NS",
            regularMarketPrice=1202.8,
            regularMarketChange=-8.4,
            regularMarketChangePercent=-0.69,
            regularMarketPreviousClose=1211.2,
            regularMarketVolume=15138916,
            marketCap=16276858601472,
        )
    return rows


def test_sync_quotes_upserts_the_universe_and_keeps_it_at_53(
    postgres_session_factory, monkeypatch
):
    rows = _all_market_rows()
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)

    cached, missing = sync.sync_quotes(postgres_session_factory)

    assert cached == 53
    assert missing == []
    assert _instrument_count(postgres_session_factory) == 53
    assert (
        _instrument_count(
            postgres_session_factory, in_market_universe=True
        )
        == 53
    )

    instrument, quote = _quote(postgres_session_factory, "RELIANCE")
    assert instrument.name == "Reliance Industries"
    assert instrument.kind == "stock"
    assert instrument.sector == ""
    assert quote.ltp == Decimal("1202.8000")
    assert quote.day_change == Decimal("-8.4000")
    assert quote.day_change_pct == Decimal("-0.690000")
    assert quote.prev_close == Decimal("1211.2000")
    assert quote.volume == 15138916
    assert quote.market_cap == Decimal("16276858601472.00")
    # No provider time was sent, so none was fabricated from the write time.
    assert quote.source_time is None
    assert quote.updated_at is not None


def test_missing_provider_rows_still_seed_the_53_symbol_universe(
    postgres_session_factory, monkeypatch
):
    monkeypatch.setattr(
        sync,
        "fetch_quotes",
        lambda tickers: {"RELIANCE.NS": _row(symbol="RELIANCE.NS")},
    )

    cached, missing = sync.sync_quotes(postgres_session_factory)

    assert cached == 1
    assert len(missing) == 52
    assert _instrument_count(postgres_session_factory) == 53
    assert (
        _instrument_count(postgres_session_factory, in_market_universe=True)
        == 53
    )
    reliance, quote = _quote(postgres_session_factory, "RELIANCE")
    missing_instrument, missing_quote = _quote(postgres_session_factory, "INFY")
    assert reliance is not None
    assert quote is not None
    assert missing_instrument.name == "Infosys"
    assert missing_quote is None


def test_repeated_market_syncs_do_not_duplicate_or_blank_metadata(
    postgres_session_factory, monkeypatch
):
    rows = _all_market_rows()
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)

    sync.sync_quotes(postgres_session_factory)
    _, first = _quote(postgres_session_factory, "RELIANCE")

    with postgres_session_factory() as session:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == "RELIANCE")
        )
        instrument.sector = "Energy"
        session.commit()
        created_at = instrument.created_at

    rows["RELIANCE.NS"]["regularMarketPrice"] = 1210.0
    sync.sync_quotes(postgres_session_factory)

    assert _instrument_count(postgres_session_factory) == 53
    with postgres_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(LatestQuote)) == 53

    instrument, refreshed = _quote(postgres_session_factory, "RELIANCE")
    assert instrument.sector == "Energy"
    assert instrument.created_at == created_at
    assert refreshed.ltp == Decimal("1210.0000")
    assert refreshed.updated_at >= first.updated_at


def test_source_time_is_the_provider_time_not_the_receipt_time(
    postgres_session_factory, monkeypatch
):
    provider_time = int(datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc).timestamp())
    rows = {
        "RELIANCE.NS": _row(regularMarketTime=provider_time),
        "^NSEI": _row(symbol="^NSEI", regularMarketPrice=22888.95),
    }
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)

    sync.sync_quotes(postgres_session_factory)

    _, reliance = _quote(postgres_session_factory, "RELIANCE")
    _, nifty = _quote(postgres_session_factory, "^NSEI")
    assert reliance.source_time == datetime(
        2026, 10, 25, 10, 0, tzinfo=timezone.utc
    )
    assert nifty.source_time is None


def test_missing_or_invalid_quote_keeps_the_previous_price(
    postgres_session_factory, monkeypatch
):
    rows = {"RELIANCE.NS": _row(regularMarketPrice=1202.8)}
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)
    sync.sync_quotes(postgres_session_factory)
    _, before = _quote(postgres_session_factory, "RELIANCE")

    for bad in (None, 0, -1.0, "not-a-number", True):
        rows["RELIANCE.NS"] = _row(regularMarketPrice=bad)
        cached, _missing = sync.sync_quotes(postgres_session_factory)
        assert cached == 0

        _, after = _quote(postgres_session_factory, "RELIANCE")
        assert after.ltp == before.ltp
        assert after.updated_at == before.updated_at


def test_a_missing_symbol_keeps_the_previous_quote(
    postgres_session_factory, monkeypatch
):
    monkeypatch.setattr(
        sync, "fetch_quotes", lambda tickers: {"RELIANCE.NS": _row()}
    )
    sync.sync_quotes(postgres_session_factory)
    _, before = _quote(postgres_session_factory, "RELIANCE")

    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: {})
    cached, missing = sync.sync_quotes(postgres_session_factory)

    assert cached == 0
    assert len(missing) == 53
    _, after = _quote(postgres_session_factory, "RELIANCE")
    assert after.ltp == before.ltp
    assert after.updated_at == before.updated_at


def test_an_older_source_time_does_not_overwrite_a_newer_quote(
    postgres_session_factory, monkeypatch
):
    newer = int(datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc).timestamp())
    older = int(datetime(2026, 10, 25, 9, 55, tzinfo=timezone.utc).timestamp())

    rows = {"RELIANCE.NS": _row(regularMarketPrice=1202.8, regularMarketTime=newer)}
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)
    sync.sync_quotes(postgres_session_factory)

    rows["RELIANCE.NS"] = _row(regularMarketPrice=999.0, regularMarketTime=older)
    sync.sync_quotes(postgres_session_factory)
    _, after_older = _quote(postgres_session_factory, "RELIANCE")
    assert after_older.ltp == Decimal("1202.8000")

    # A missing provider time refreshes the displayed price but clears the
    # canonical source time, because it cannot be attached to a provider time.
    rows["RELIANCE.NS"] = _row(regularMarketPrice=1210.0)
    sync.sync_quotes(postgres_session_factory)
    _, after_null = _quote(postgres_session_factory, "RELIANCE")
    assert after_null.ltp == Decimal("1210.0000")
    assert after_null.source_time is None


def test_a_provider_failure_does_not_clear_the_cache(
    postgres_session_factory, monkeypatch
):
    monkeypatch.setattr(
        sync, "fetch_quotes", lambda tickers: {"RELIANCE.NS": _row()}
    )
    sync.sync_quotes(postgres_session_factory)
    _, before = _quote(postgres_session_factory, "RELIANCE")

    def explode(tickers):
        raise market_data.MarketDataError("Yahoo is down")

    monkeypatch.setattr(sync, "fetch_quotes", explode)

    assert sync.sync_quotes(postgres_session_factory) == (0, [])
    _, after = _quote(postgres_session_factory, "RELIANCE")
    assert after.ltp == before.ltp
    assert after.updated_at == before.updated_at


def test_backfill_fills_only_pending_stock_instruments(
    postgres_session_factory, market_instrument_factory, monkeypatch
):
    # Instruments are seeded directly: a market sync would also register the
    # other 50 symbols of the universe, which are sector-less too and would
    # consume the batch cap. Backfill only reads instruments.
    market_instrument_factory(symbol="INFY", name="Infosys", quote=False)
    market_instrument_factory(symbol="TCS", name="TCS", quote=False)
    market_instrument_factory(
        symbol="^NSEI", name="NIFTY 50", kind="index", quote=False
    )

    sectors = {"INFY": "Technology", "TCS": ""}  # TCS has no profile
    asked = []
    monkeypatch.setattr(
        sync, "fetch_sector", lambda symbol: asked.append(symbol) or sectors[symbol]
    )

    assert sync.backfill_sectors(postgres_session_factory) == 1
    assert "INFY" in asked
    assert "^NSEI" not in asked  # an index is never asked

    instrument, _ = _quote(postgres_session_factory, "INFY")
    assert instrument.sector == "Technology"
    tcs, _ = _quote(postgres_session_factory, "TCS")
    assert tcs.sector == ""
    nifty, _ = _quote(postgres_session_factory, "^NSEI")
    assert nifty.sector == ""


def test_backfill_is_capped_per_run(
    postgres_session_factory, market_instrument_factory, monkeypatch
):
    for symbol, name in NIFTY50[:15]:
        market_instrument_factory(symbol=symbol, name=name, quote=False)
    monkeypatch.setattr(sync, "fetch_sector", lambda symbol: "Technology")

    assert sync.backfill_sectors(postgres_session_factory) == 10
    assert sync.backfill_sectors(postgres_session_factory) == 5


def test_backfill_logs_a_provider_error_and_keeps_going(
    postgres_session_factory, market_instrument_factory, monkeypatch
):
    market_instrument_factory(symbol="INFY", name="Infosys", quote=False)
    market_instrument_factory(symbol="TCS", name="TCS", quote=False)

    def flaky(symbol):
        if symbol == "INFY":
            raise market_data.MarketDataError("profile lookup failed")
        return "Technology"

    monkeypatch.setattr(sync, "fetch_sector", flaky)

    assert sync.backfill_sectors(postgres_session_factory) == 1
    infy, _ = _quote(postgres_session_factory, "INFY")
    tcs, _ = _quote(postgres_session_factory, "TCS")
    assert infy.sector == ""
    assert tcs.sector == "Technology"


def test_backfill_does_not_move_quote_freshness(
    postgres_session_factory, monkeypatch
):
    rows = {"INFY.NS": _row(symbol="INFY.NS")}
    monkeypatch.setattr(sync, "fetch_quotes", lambda tickers: rows)
    sync.sync_quotes(postgres_session_factory)
    _, before = _quote(postgres_session_factory, "INFY")

    monkeypatch.setattr(sync, "fetch_sector", lambda symbol: "Technology")
    sync.backfill_sectors(postgres_session_factory)

    _, after = _quote(postgres_session_factory, "INFY")
    assert after.updated_at == before.updated_at


# --------------------------------------------------------------------------
# market_sync gating
# --------------------------------------------------------------------------


def test_market_sync_skips_the_quote_refresh_when_closed_with_a_warm_cache(
    postgres_session_factory, monkeypatch
):
    monkeypatch.setattr(
        sync, "fetch_quotes", lambda tickers: {"INFY.NS": _row()}
    )
    sync.sync_quotes(postgres_session_factory)

    monkeypatch.setattr(sync, "is_market_open", lambda: False)
    monkeypatch.setattr(
        sync,
        "sync_quotes",
        lambda factory: pytest.fail("must not quote while closed"),
    )
    monkeypatch.setattr(sync, "backfill_sectors", lambda factory: 0)

    sync.market_sync(postgres_session_factory)  # no exception


def test_market_sync_syncs_a_cold_cache_even_when_closed(
    postgres_session_factory, monkeypatch
):
    monkeypatch.setattr(sync, "is_market_open", lambda: False)
    called = []
    monkeypatch.setattr(
        sync, "sync_quotes", lambda factory: called.append(factory) or (0, [])
    )
    monkeypatch.setattr(sync, "backfill_sectors", lambda factory: 0)

    sync.market_sync(postgres_session_factory)

    assert called == [postgres_session_factory]


def test_market_sync_survives_an_unexpected_error(
    postgres_session_factory, monkeypatch
):
    def explode(session):
        raise RuntimeError("boom")

    monkeypatch.setattr(sync, "count_market_quotes", explode)
    monkeypatch.setattr(sync, "backfill_sectors", lambda factory: 0)

    sync.market_sync(postgres_session_factory)  # logged, not raised

    # The lock must be released, or every later tick would be skipped.
    assert not sync._sync_lock.locked()


def test_market_sync_skips_a_tick_while_one_is_running(
    postgres_session_factory, monkeypatch
):
    entered = []

    def slow_sync(factory):
        entered.append(True)
        # A second tick arriving now must be refused.
        sync.market_sync(factory)
        return 0, []

    monkeypatch.setattr(sync, "count_market_quotes", lambda session: 0)
    monkeypatch.setattr(sync, "sync_quotes", slow_sync)
    monkeypatch.setattr(sync, "backfill_sectors", lambda factory: 0)

    sync.market_sync(postgres_session_factory)

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


def test_scheduler_runs_once_immediately_then_stops(monkeypatch):
    ticks = []
    sentinel = object()
    monkeypatch.setattr(scheduler, "market_sync", lambda factory: ticks.append(factory))

    instance = scheduler.MarketSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.stop()

    # The immediate tick populates a cold cache, like Express's call on connect.
    assert ticks == [sentinel]


def test_scheduler_does_not_start_twice(monkeypatch):
    ticks = []
    sentinel = object()
    monkeypatch.setattr(scheduler, "market_sync", lambda factory: ticks.append(factory))

    instance = scheduler.MarketSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.start()  # a second start must not spawn another thread
    instance.stop()

    assert len(ticks) == 1


def test_scheduler_survives_a_failing_tick(monkeypatch):
    calls = []
    sentinel = object()

    def flaky(factory):
        calls.append(factory)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "market_sync", flaky)

    instance = scheduler.MarketSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.stop()

    # The thread logged the failure instead of dying before stop() could join it.
    assert calls == [sentinel]
    assert instance._thread is None


def test_enabling_the_switch_starts_and_stops_the_scheduler(monkeypatch):
    """Startup wiring: the scheduler runs only when the switch is on."""
    from api.main import create_app

    monkeypatch.setenv("MARKET_SYNC_ENABLED", "true")
    started = []
    stopped = []
    monkeypatch.setattr(
        scheduler.MarketSyncScheduler, "start", lambda self: started.append("market")
    )
    monkeypatch.setattr(
        scheduler.MarketSyncScheduler, "stop", lambda self: stopped.append("market")
    )

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200

    assert started == ["market"]
    assert stopped == ["market"]
