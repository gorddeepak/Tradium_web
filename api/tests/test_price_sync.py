"""Focused tests for the PostgreSQL price sync.

The provider seam is patched and the market-hours gate is forced open or
closed per test, so nothing here touches the network or the wall clock.
Price sync now owns only the canonical ``instruments``/``latest_quotes``
cache; holdings and positions read their prices through the join, so there is
no Mongo book row to mirror. Order matching lives in ``test_order_fills.py``.
"""

import secrets
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api import scheduler
from api.jobs import price_sync
from api.main import create_app
from api.market_data import MarketDataError
from api.postgres.models import Instrument, LatestQuote, Watchlist

NOW = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
CREATED = datetime(2026, 9, 1, 4, 15, 30, tzinfo=timezone.utc)
PROVIDER_TIME = 1792922400  # 2026-10-25 10:00:00 UTC


def _open_market(monkeypatch):
    monkeypatch.setattr(price_sync, "is_market_open", lambda: True)


def _closed_market(monkeypatch):
    monkeypatch.setattr(price_sync, "is_market_open", lambda: False)


def _row(ltp, day_change_pct=0.0, source_time=NOW, **overrides):
    row = {
        "regularMarketPrice": ltp,
        "regularMarketChangePercent": day_change_pct,
        "regularMarketTime": None if source_time is None else source_time.timestamp(),
    }
    row.update(overrides)
    return row


def _quotes(monkeypatch, mapping):
    """Patch the batch seam. ``mapping`` is keyed by Yahoo ticker."""
    calls = []

    def fetch(tickers):
        calls.append(list(tickers))
        return {ticker: mapping[ticker] for ticker in tickers if ticker in mapping}

    monkeypatch.setattr(price_sync, "fetch_quotes", fetch)
    return calls


def _run(monkeypatch, session_factory, mapping, *, now=NOW, sector=""):
    """Run one full tick with both provider seams offline."""
    calls = _quotes(monkeypatch, mapping)
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: sector)
    price_sync.run_sync(session_factory, now=now)
    return calls


def _quote(session_factory, symbol):
    with session_factory() as session:
        instrument = session.scalar(
            select(Instrument).where(Instrument.symbol == symbol)
        )
        if instrument is None:
            return None, None
        return instrument, session.get(LatestQuote, instrument.id)


@pytest.fixture
def book_watchlist_factory(book_session_factory):
    def _make(user_id, symbol="TCS", name=None, exchange="NSE"):
        watch = Watchlist(
            id=secrets.token_hex(12),
            user_id=user_id,
            symbol=symbol,
            name=name or symbol,
            exchange=exchange,
            created_at=CREATED,
            updated_at=CREATED,
            version=0,
        )
        with book_session_factory() as session:
            session.add(watch)
            session.commit()
        return watch

    return _make


# --------------------------------------------------------------------------
# The market-hours gate and single-flight guard
# --------------------------------------------------------------------------


def test_closed_market_does_no_work(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _closed_market(monkeypatch)
    calls = _quotes(monkeypatch, {"RELIANCE.NS": _row(1.0, 1.0)})

    price_sync.sync_prices(book_session_factory)

    assert calls == []
    assert _quote(book_session_factory, "RELIANCE") == (None, None)


def test_a_tick_is_skipped_while_the_previous_run_holds_the_lock(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)
    calls = _quotes(monkeypatch, {"RELIANCE.NS": _row(2600.0, 1.0)})

    assert price_sync._sync_lock.acquire(blocking=False)
    try:
        price_sync.sync_prices(book_session_factory)
    finally:
        price_sync._sync_lock.release()

    assert calls == []
    assert _quote(book_session_factory, "RELIANCE") == (None, None)


def test_the_lock_is_released_after_a_successful_run(
    book_session_factory, monkeypatch
):
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")

    price_sync.sync_prices(book_session_factory)

    assert price_sync._sync_lock.acquire(blocking=False)
    price_sync._sync_lock.release()


# --------------------------------------------------------------------------
# Canonical quote refresh
# --------------------------------------------------------------------------


def test_open_tick_refreshes_holdings_positions_watchlist_and_orders(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_position_factory,
    book_order_factory,
    book_watchlist_factory,
    monkeypatch,
):
    book_holding_factory(book_user, symbol="RELIANCE")
    book_position_factory(book_user, symbol="INFY", side="LONG")
    book_watchlist_factory(book_user, symbol="TCS")
    book_order_factory(book_user, symbol="HDFCBANK", price=1)
    _open_market(monkeypatch)

    calls = _run(
        monkeypatch,
        book_session_factory,
        {
            "RELIANCE.NS": _row(111.5, -0.5),
            "INFY.NS": _row(222.5, 0.5),
            "TCS.NS": _row(333.5, 1.5),
            "HDFCBANK.NS": _row(444.5, 2.5),
        },
    )

    assert len(calls) == 1
    assert sorted(calls[0]) == sorted(
        ["RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS"]
    )
    for symbol, ltp, pct in [
        ("RELIANCE", "111.5000", "0.500000"),
        ("INFY", "222.5000", "0.500000"),
        ("TCS", "333.5000", "1.500000"),
        ("HDFCBANK", "444.5000", "2.500000"),
    ]:
        _instrument, quote = _quote(book_session_factory, symbol)
        assert quote.ltp == Decimal(ltp)
        assert abs(quote.day_change_pct) == Decimal(pct)


def test_each_distinct_symbol_is_quoted_once(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_position_factory,
    book_order_factory,
    book_watchlist_factory,
    monkeypatch,
):
    # The same symbol appears in all four sources; the symbol map dedupes it.
    book_holding_factory(book_user, symbol="INFY")
    book_position_factory(book_user, symbol="INFY", side="LONG")
    book_watchlist_factory(book_user, symbol="INFY")
    book_order_factory(book_user, symbol="INFY", price=1)
    _open_market(monkeypatch)

    calls = _run(monkeypatch, book_session_factory, {"INFY.NS": _row(1500.0)})

    assert calls == [["INFY.NS"]]
    assert session_quote_count(book_session_factory) == 1


def session_quote_count(session_factory):
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(LatestQuote))


def test_all_distinct_symbols_are_fetched_in_one_batch(
    book_session_factory,
    book_user,
    book_holding_factory,
    book_position_factory,
    book_order_factory,
    book_watchlist_factory,
    monkeypatch,
):
    book_holding_factory(book_user, symbol="RELIANCE")
    book_position_factory(book_user, symbol="INFY")
    book_watchlist_factory(book_user, symbol="TCS")
    book_order_factory(book_user, symbol="HDFCBANK", price=1)
    _open_market(monkeypatch)

    calls = _run(
        monkeypatch,
        book_session_factory,
        {
            "RELIANCE.NS": _row(2600.0, 1.0),
            "INFY.NS": _row(1500.0, -0.5),
            "TCS.NS": _row(3200.0, 0.25),
            "HDFCBANK.NS": _row(1700.0),
        },
    )

    assert len(calls) == 1
    assert sorted(calls[0]) == sorted(
        ["RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS"]
    )
    assert _quote(book_session_factory, "RELIANCE")[1].ltp == Decimal("2600.0000")
    assert _quote(book_session_factory, "INFY")[1].ltp == Decimal("1500.0000")
    assert _quote(book_session_factory, "TCS")[1].ltp == Decimal("3200.0000")


def test_an_empty_database_does_not_call_the_provider(
    book_session_factory, monkeypatch
):
    _open_market(monkeypatch)
    calls = _quotes(monkeypatch, {})
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")

    price_sync.run_sync(book_session_factory, now=NOW)

    assert calls == []


def test_a_failed_batch_keeps_every_stored_quote(
    book_session_factory, book_user, book_holding_factory,
    market_instrument_factory, monkeypatch,
):
    book_holding_factory(book_user, symbol="RELIANCE")
    market_instrument_factory(
        symbol="RELIANCE", ltp=2500.0, day_change_pct=1.25, updated_at=CREATED
    )
    _open_market(monkeypatch)

    def fail(tickers):
        raise MarketDataError("Yahoo is down")

    monkeypatch.setattr(price_sync, "fetch_quotes", fail)
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")

    price_sync.run_sync(book_session_factory, now=NOW)  # must not raise

    _instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert quote.ltp == Decimal("2500.0000")
    assert quote.day_change_pct == Decimal("1.250000")
    assert quote.updated_at == CREATED


@pytest.mark.parametrize("price", [None, 0, -1.0, "2600.0", True])
def test_an_unusable_batch_price_keeps_the_stored_quote(
    book_session_factory, book_user, book_holding_factory,
    market_instrument_factory, monkeypatch, price,
):
    book_holding_factory(book_user, symbol="RELIANCE")
    market_instrument_factory(
        symbol="RELIANCE", ltp=2500.0, day_change_pct=1.25, updated_at=CREATED
    )
    _open_market(monkeypatch)

    _run(monkeypatch, book_session_factory, {"RELIANCE.NS": _row(price)})

    _instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert quote.ltp == Decimal("2500.0000")
    assert quote.day_change_pct == Decimal("1.250000")
    assert quote.updated_at == CREATED


def test_a_symbol_without_a_provider_row_keeps_its_stored_quote(
    book_session_factory, book_user, book_holding_factory,
    market_instrument_factory, monkeypatch,
):
    book_holding_factory(book_user, symbol="RELIANCE")
    market_instrument_factory(symbol="RELIANCE", ltp=2500.0, updated_at=CREATED)
    _open_market(monkeypatch)

    _run(monkeypatch, book_session_factory, {})  # provider skipped the symbol

    _instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert quote.ltp == Decimal("2500.0000")
    assert quote.updated_at == CREATED


def test_a_missing_day_change_percentage_becomes_zero(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)
    row = _row(2600.0)
    del row["regularMarketChangePercent"]

    _run(monkeypatch, book_session_factory, {"RELIANCE.NS": row})

    _instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert quote.ltp == Decimal("2600.0000")
    assert quote.day_change_pct == Decimal("0.000000")


# --------------------------------------------------------------------------
# Quote persistence shape and instrument ownership
# --------------------------------------------------------------------------


def test_price_sync_writes_the_canonical_quote(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)

    _run(
        monkeypatch,
        book_session_factory,
        {
            "RELIANCE.NS": _row(
                1600.0,
                0.5,
                source_time=None,
                regularMarketTime=PROVIDER_TIME,
                regularMarketChange=8.0,
                regularMarketPreviousClose=1592.0,
                regularMarketVolume=1234,
                marketCap=999999,
            )
        },
    )

    instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert instrument.name == "Reliance Industries"
    assert instrument.in_market_universe is False  # book-only until market sync
    assert quote.ltp == Decimal("1600.0000")
    assert quote.day_change_pct == Decimal("0.500000")
    # Price sync owns only LTP/pct/source/updated; richer fields stay at their
    # defaults until a market-sync tick writes them.
    assert quote.day_change == Decimal("0.0000")
    assert quote.prev_close == Decimal("0.0000")
    assert quote.volume == 0
    assert quote.market_cap == Decimal("0.00")
    assert quote.source_time is not None
    assert quote.source_time.astimezone(timezone.utc).isoformat() == (
        "2026-10-25T10:00:00+00:00"
    )
    assert quote.updated_at == NOW


def test_price_sync_preserves_a_universe_instrument(
    book_session_factory,
    book_user,
    book_holding_factory,
    market_instrument_factory,
    monkeypatch,
):
    instrument_id = market_instrument_factory(
        symbol="INFY",
        name="Infosys",
        sector="IT",
        in_market_universe=True,
        quote=False,
    )
    book_holding_factory(book_user, symbol="INFY")
    _open_market(monkeypatch)

    _run(monkeypatch, book_session_factory, {"INFY.NS": _row(1500.0, -0.5)})

    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Instrument)) == 1
        instrument = session.get(Instrument, instrument_id)
        assert instrument.in_market_universe is True
        assert instrument.name == "Infosys"
        assert instrument.sector == "IT"
        quote = session.get(LatestQuote, instrument_id)
        assert quote.ltp == Decimal("1500.0000")


def test_price_sync_repeated_runs_are_idempotent(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)

    _run(monkeypatch, book_session_factory, {"RELIANCE.NS": _row(1600.0, 0.5)})
    _run(monkeypatch, book_session_factory, {"RELIANCE.NS": _row(1600.0, 0.5)})

    with book_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Instrument)) == 1
        assert session.scalar(select(func.count()).select_from(LatestQuote)) == 1


def test_instrument_sectors_are_backfilled_in_postgres(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)

    _run(
        monkeypatch,
        book_session_factory,
        {"RELIANCE.NS": _row(1600.0, 0.5)},
        sector="Energy",
    )

    instrument, _quote_row = _quote(book_session_factory, "RELIANCE")
    assert instrument.sector == "Energy"


def test_an_empty_instrument_sector_is_left_for_a_later_run(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)

    _run(
        monkeypatch,
        book_session_factory,
        {"RELIANCE.NS": _row(1600.0, 0.5)},
        sector="",
    )

    instrument, _quote_row = _quote(book_session_factory, "RELIANCE")
    assert instrument.sector == ""


# --------------------------------------------------------------------------
# The PostgreSQL watchlist is the only watchlist source
# --------------------------------------------------------------------------


def test_postgres_watchlist_symbols_are_quoted(
    book_session_factory,
    book_user,
    book_watchlist_factory,
    monkeypatch,
):
    book_watchlist_factory(book_user, symbol="INFY")
    _open_market(monkeypatch)

    calls = _run(monkeypatch, book_session_factory, {"INFY.NS": _row(1500.25, 0.5)})

    assert calls == [["INFY.NS"]]
    _instrument, quote = _quote(book_session_factory, "INFY")
    assert quote.ltp == Decimal("1500.2500")
    assert quote.day_change_pct == Decimal("0.500000")


def test_a_watchlist_read_failure_still_refreshes_the_book(
    book_session_factory, book_user, book_holding_factory, monkeypatch
):
    book_holding_factory(book_user, symbol="RELIANCE")
    _open_market(monkeypatch)

    def broken(session_factory):
        raise RuntimeError("watchlists unavailable")

    monkeypatch.setattr(price_sync, "_watchlists", broken)

    _run(monkeypatch, book_session_factory, {"RELIANCE.NS": _row(1600.0, 0.5)})

    _instrument, quote = _quote(book_session_factory, "RELIANCE")
    assert quote.ltp == Decimal("1600.0000")


# --------------------------------------------------------------------------
# Scheduler ownership
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_trading_switch_accepts_the_documented_truthy_values(monkeypatch, value):
    monkeypatch.setenv("TRADING_JOBS_ENABLED", value)

    assert scheduler.trading_jobs_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_trading_switch_is_off_for_anything_else(monkeypatch, value):
    monkeypatch.setenv("TRADING_JOBS_ENABLED", value)

    assert scheduler.trading_jobs_enabled() is False


def test_trading_switch_defaults_to_off(monkeypatch):
    monkeypatch.delenv("TRADING_JOBS_ENABLED", raising=False)

    assert scheduler.trading_jobs_enabled() is False


def test_price_scheduler_runs_once_immediately_then_stops(monkeypatch):
    ticks = []
    sentinel = object()
    monkeypatch.setattr(scheduler, "sync_prices", lambda factory: ticks.append(factory))

    instance = scheduler.PriceSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.stop()

    # Express calls syncPrices() on connect as well as on the cron, and the
    # PostgreSQL job needs only the session factory.
    assert ticks == [sentinel]
    assert instance._thread is None


def test_price_scheduler_does_not_start_twice(monkeypatch):
    ticks = []
    sentinel = object()
    monkeypatch.setattr(scheduler, "sync_prices", lambda factory: ticks.append(factory))

    instance = scheduler.PriceSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.start()
    instance.stop()

    assert len(ticks) == 1


def test_price_scheduler_survives_a_failing_tick(monkeypatch):
    calls = []
    sentinel = object()

    def flaky(factory):
        calls.append(factory)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "sync_prices", flaky)

    instance = scheduler.PriceSyncScheduler(interval_seconds=60, session_factory=sentinel)
    instance.start()
    instance.stop()

    assert calls == [sentinel]
    assert instance._thread is None


def test_enabling_trading_jobs_starts_and_stops_both_schedulers(monkeypatch):
    """Startup wiring: one switch owns price sync and the daily snapshot."""
    monkeypatch.setenv("TRADING_JOBS_ENABLED", "true")
    started = []
    stopped = []
    monkeypatch.setattr(
        scheduler.PriceSyncScheduler, "start", lambda self: started.append("price")
    )
    monkeypatch.setattr(
        scheduler.PortfolioSnapshotScheduler,
        "start",
        lambda self: started.append("snapshot"),
    )
    monkeypatch.setattr(
        scheduler.PriceSyncScheduler, "stop", lambda self: stopped.append("price")
    )
    monkeypatch.setattr(
        scheduler.PortfolioSnapshotScheduler,
        "stop",
        lambda self: stopped.append("snapshot"),
    )

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200

    assert started == ["price", "snapshot"]
    assert stopped == ["price", "snapshot"]
