"""Focused tests for the per-minute price sync and MIS exit settlement.

No network: the quote/provider seam is patched, and the market-hours gate is
forced open or closed per test. Dates are synthetic, so nothing depends on the
wall clock or on a real trading session. mongomock can run every write this job
uses (``update_one``, ``find_one_and_update`` with ``$inc``, upserts).
"""

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from api import scheduler
from api.jobs import price_sync
from api.main import create_app
from api.market_data import MarketDataError
from api.order_engine import apply_fill, settle_mis_exit


def _open_market(monkeypatch):
    monkeypatch.setattr(price_sync, "is_market_open", lambda: True)


def _closed_market(monkeypatch):
    monkeypatch.setattr(price_sync, "is_market_open", lambda: False)


def _quote(ltp, day_change_pct=0.0):
    return lambda symbol: {"ltp": ltp, "dayChangePct": day_change_pct}


def _quotes(monkeypatch, mapping):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return mapping.get(symbol)

    monkeypatch.setattr(price_sync, "fetch_quote", fetch)
    return calls


# --------------------------------------------------------------------------
# The market-hours gate and single-flight guard
# --------------------------------------------------------------------------


def test_closed_market_does_no_work(database, holdings_factory, monkeypatch):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, sector="Energy"))
    _closed_market(monkeypatch)
    calls = _quotes(monkeypatch, {"RELIANCE": {"ltp": 1.0, "dayChangePct": 1.0}})

    price_sync.sync_prices(database)

    assert calls == []
    assert database["holdings"].find_one({"user": user})["ltp"] == 2500.0


def test_a_tick_is_skipped_while_the_previous_run_holds_the_lock(
    database, holdings_factory, monkeypatch
):
    database["holdings"].insert_one(holdings_factory(ObjectId()))
    _open_market(monkeypatch)
    calls = _quotes(monkeypatch, {"RELIANCE": {"ltp": 2600.0, "dayChangePct": 1.0}})

    assert price_sync._sync_lock.acquire(blocking=False)
    try:
        price_sync.sync_prices(database)
    finally:
        price_sync._sync_lock.release()

    assert calls == []
    assert database["holdings"].find_one()["ltp"] == 2500.0


def test_the_lock_is_released_after_a_successful_run(database, monkeypatch):
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})

    price_sync.sync_prices(database)

    assert price_sync._sync_lock.acquire(blocking=False)
    price_sync._sync_lock.release()


# --------------------------------------------------------------------------
# Price refresh
# --------------------------------------------------------------------------


def test_open_tick_refreshes_holdings_positions_and_watchlist(
    database, holdings_factory, positions_factory, watchlist_factory, monkeypatch
):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, sector="Energy"))
    database["positions"].insert_one(positions_factory(user))
    database["watchlists"].insert_one(watchlist_factory(user))
    _open_market(monkeypatch)

    def fetch(symbol):
        return {"ltp": 111.5, "dayChangePct": -0.5}

    monkeypatch.setattr(price_sync, "fetch_quote", fetch)

    price_sync.sync_prices(database)

    holding = database["holdings"].find_one({"user": user})
    assert holding["ltp"] == 111.5
    assert holding["dayChangePct"] == -0.5
    assert holding["updatedAt"] > holding["createdAt"]
    assert holding["__v"] == 0  # save() does not bump the version key

    position = database["positions"].find_one({"user": user})
    assert position["ltp"] == 111.5
    # Positions only carry a price, never the day percentage.
    assert "dayChangePct" not in position

    watch = database["watchlists"].find_one({"user": user})
    assert watch["ltp"] == 111.5
    assert watch["dayChangePct"] == -0.5


def test_each_distinct_symbol_is_quoted_once(
    database, holdings_factory, positions_factory, watchlist_factory, orders_factory, monkeypatch
):
    user = ObjectId()
    # The same symbol appears in all four sources; the Map dedupes it.
    database["holdings"].insert_one(holdings_factory(user, symbol="INFY", sector="IT"))
    database["positions"].insert_one(positions_factory(user, symbol="INFY"))
    database["watchlists"].insert_one(watchlist_factory(user, symbol="INFY"))
    database["orders"].insert_one(orders_factory(user, symbol="INFY", price=1.0))
    _open_market(monkeypatch)
    calls = _quotes(monkeypatch, {"INFY": {"ltp": 1500.0, "dayChangePct": 0.0}})

    price_sync.run_sync(database)

    assert calls == ["INFY"]


def test_a_symbol_without_a_quote_keeps_its_stored_price(
    database, holdings_factory, monkeypatch
):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, sector="Energy"))
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})  # provider answered "no usable price"

    price_sync.run_sync(database)

    assert database["holdings"].find_one({"user": user})["ltp"] == 2500.0


# --------------------------------------------------------------------------
# Sector backfill
# --------------------------------------------------------------------------


def test_sector_is_filled_only_for_holdings_without_one(
    database, holdings_factory, monkeypatch
):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, symbol="RELIANCE", sector=""))
    database["holdings"].insert_one(holdings_factory(user, symbol="TCS", sector="IT"))
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})

    fetched = []
    monkeypatch.setattr(
        price_sync,
        "fetch_sector",
        lambda symbol: fetched.append(symbol) or "Energy",
    )

    price_sync.run_sync(database)

    assert fetched == ["RELIANCE"]
    assert database["holdings"].find_one({"symbol": "RELIANCE"})["sector"] == "Energy"
    assert database["holdings"].find_one({"symbol": "TCS"})["sector"] == "IT"


def test_an_empty_sector_is_left_for_a_later_run(
    database, holdings_factory, monkeypatch
):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, symbol="^NSEI", sector=""))
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})
    monkeypatch.setattr(price_sync, "fetch_sector", lambda symbol: "")

    price_sync.run_sync(database)

    assert database["holdings"].find_one({"user": user})["sector"] == ""


def test_a_sector_provider_failure_does_not_abort_the_run(
    database, holdings_factory, monkeypatch
):
    user = ObjectId()
    database["holdings"].insert_one(holdings_factory(user, sector=""))
    _open_market(monkeypatch)
    _quotes(monkeypatch, {})

    def fail(symbol):
        raise MarketDataError("profile lookup failed")

    monkeypatch.setattr(price_sync, "fetch_sector", fail)

    price_sync.run_sync(database)  # must not raise

    assert database["holdings"].find_one({"user": user})["sector"] == ""


# --------------------------------------------------------------------------
# Order matching
# --------------------------------------------------------------------------


def test_limit_buy_fills_at_its_limit_price_not_the_quote(
    database, user_id, orders_factory, monkeypatch
):
    order = orders_factory(user_id, side="BUY", type="LIMIT", product="CNC", qty=5, price=100.0)
    database["orders"].insert_one(order)
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 99.5, "dayChangePct": -1.0}})

    price_sync.run_sync(database)

    claimed = database["orders"].find_one({"_id": order["_id"]})
    assert claimed["status"] == "EXECUTED"
    assert claimed["filled"] == 5
    assert claimed["price"] == 100.0  # the limit, not the 99.5 quote
    holding = database["holdings"].find_one({"user": user_id})
    assert holding["qty"] == 5
    assert holding["avgPrice"] == 100.0


def test_an_order_that_has_not_crossed_stays_open(
    database, user_id, orders_factory, monkeypatch
):
    order = orders_factory(user_id, side="BUY", type="LIMIT", product="CNC", qty=5, price=100.0)
    database["orders"].insert_one(order)
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 100.5, "dayChangePct": 0.0}})

    price_sync.run_sync(database)

    assert database["orders"].find_one({"_id": order["_id"]})["status"] == "OPEN"
    assert database["holdings"].count_documents({"user": user_id}) == 0


def test_limit_sell_credits_funds_and_records_the_settlement(
    database, user_id, holdings_factory, orders_factory, funds_factory, monkeypatch
):
    database["holdings"].insert_one(
        holdings_factory(user_id, symbol="INFY", qty=5, avg_price=1400.0, ltp=1500.0, sector="IT")
    )
    database["funds"].insert_one(funds_factory(user_id, available=0))
    order = orders_factory(user_id, side="SELL", type="LIMIT", product="CNC", qty=5, price=1500.0)
    database["orders"].insert_one(order)
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 1510.0, "dayChangePct": 1.0}})

    price_sync.run_sync(database)

    assert database["orders"].find_one({"_id": order["_id"]})["status"] == "EXECUTED"
    assert database["holdings"].count_documents({"user": user_id}) == 0
    assert database["funds"].find_one({"user": user_id})["available"] == 7500.0
    transaction = database["transactions"].find_one({"user": user_id, "kind": "SETTLEMENT"})
    assert transaction["method"] == "INFY sell"
    assert transaction["amount"] == 500.0  # (1500 - 1400) * 5


def test_slm_fills_at_the_live_price_and_adjusts_the_blocked_cash(
    database, user_id, orders_factory, funds_factory, monkeypatch
):
    # 5 * 100 was blocked at placement; the fill at 106 needs 30 more.
    database["funds"].insert_one(funds_factory(user_id, available=0))
    order = orders_factory(
        user_id, side="BUY", type="SL-M", product="CNC", qty=5, price=100.0, triggerPrice=105.0
    )
    database["orders"].insert_one(order)
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 106.0, "dayChangePct": 0.0}})

    price_sync.run_sync(database)

    claimed = database["orders"].find_one({"_id": order["_id"]})
    assert claimed["status"] == "EXECUTED"
    assert claimed["price"] == 106.0
    assert database["funds"].find_one({"user": user_id})["available"] == -30.0


def test_slm_exit_does_not_touch_the_blocked_cash_adjustment(
    database, user_id, orders_factory, funds_factory, positions_factory, monkeypatch
):
    database["funds"].insert_one(funds_factory(user_id, available=1000))
    database["positions"].insert_one(
        positions_factory(user_id, side="SHORT", entry=1500.0, ltp=1500.0)
    )
    # A SHORT is covered by a BUY stop above the market, so 1520 crosses 1500.
    order = orders_factory(
        user_id,
        side="BUY",
        type="SL-M",
        product="MIS",
        qty=5,
        price=1500.0,
        triggerPrice=1500.0,
        isExit=True,
        groupId="group-1",
    )
    database["orders"].insert_one(order)
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 1520.0, "dayChangePct": 0.0}})

    price_sync.run_sync(database)

    # Only settleMisExit's release (1500*5 - 20*5) lands; no SL-M adjustment.
    assert database["funds"].find_one({"user": user_id})["available"] == 8400.0


def test_mis_exit_fill_settles_the_position_and_cancels_its_sibling(
    database, user_id, positions_factory, orders_factory, funds_factory, monkeypatch
):
    database["funds"].insert_one(funds_factory(user_id, available=500))
    position = positions_factory(user_id, qty=10, entry=100.0, ltp=105.0)
    database["positions"].insert_one(position)
    exit_order = orders_factory(
        user_id,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=10,
        price=120.0,
        triggerPrice=0.0,
        isExit=True,
        groupId="group-1",
    )
    sibling = orders_factory(
        user_id,
        side="SELL",
        type="LIMIT",
        product="MIS",
        qty=10,
        price=130.0,
        triggerPrice=0.0,
        isExit=True,
        groupId="group-1",
    )
    database["orders"].insert_many([exit_order, sibling])
    _open_market(monkeypatch)
    _quotes(monkeypatch, {"INFY": {"ltp": 120.0, "dayChangePct": 0.0}})

    price_sync.run_sync(database)

    assert database["positions"].count_documents({"user": user_id}) == 0
    # 500 + (100*10 + (120-100)*10)
    assert database["funds"].find_one({"user": user_id})["available"] == 1700.0
    transaction = database["transactions"].find_one({"user": user_id})
    assert transaction["method"] == "INFY MIS exit"
    assert transaction["amount"] == 200
    assert database["orders"].find_one({"_id": sibling["_id"]})["status"] == "CANCELLED"


def test_one_bad_order_does_not_stop_the_others(
    database, user_id, orders_factory, monkeypatch
):
    first = orders_factory(user_id, symbol="INFY", side="BUY", type="LIMIT", qty=1, price=100.0)
    second = orders_factory(user_id, symbol="TCS", side="BUY", type="LIMIT", qty=1, price=200.0)
    database["orders"].insert_many([first, second])
    _open_market(monkeypatch)
    _quotes(
        monkeypatch,
        {
            "INFY": {"ltp": 90.0, "dayChangePct": 0.0},
            "TCS": {"ltp": 190.0, "dayChangePct": 0.0},
        },
    )

    def flaky(db, order):
        if order["symbol"] == "INFY":
            raise RuntimeError("boom")
        return apply_fill(db, order)

    monkeypatch.setattr(price_sync, "apply_fill", flaky)

    price_sync.run_sync(database)  # must not raise

    assert database["orders"].find_one({"_id": first["_id"]})["status"] == "EXECUTED"
    assert database["orders"].find_one({"_id": second["_id"]})["status"] == "EXECUTED"
    assert database["holdings"].count_documents({"symbol": "TCS"}) == 1


# --------------------------------------------------------------------------
# settle_mis_exit (the function the fill loop delegates to)
# --------------------------------------------------------------------------


def _exit_order(user_id, orders_factory, **overrides):
    values = dict(
        side="SELL",
        type="SL-M",
        product="MIS",
        qty=10,
        price=110.0,
        triggerPrice=110.0,
        isExit=True,
        groupId="group-1",
        status="EXECUTED",
    )
    values.update(overrides)
    return orders_factory(user_id, **values)


def test_settle_long_releases_entry_plus_profit(
    database, user_id, positions_factory, orders_factory, funds_factory
):
    database["positions"].insert_one(
        positions_factory(user_id, side="LONG", qty=10, entry=100.0, ltp=105.0)
    )
    database["funds"].insert_one(funds_factory(user_id, available=0))
    order = _exit_order(user_id, orders_factory, qty=10, price=110.0)

    settle_mis_exit(database, order)

    assert database["positions"].count_documents({}) == 0
    assert database["funds"].find_one({"user": user_id})["available"] == 1100.0
    assert database["transactions"].find_one({})["amount"] == 100


def test_settle_short_pnl_sign_is_inverted(
    database, user_id, positions_factory, orders_factory, funds_factory
):
    # Short 10 at 100, covered at 90 -> +100 profit.
    database["positions"].insert_one(
        positions_factory(user_id, side="SHORT", qty=10, entry=100.0, ltp=95.0)
    )
    database["funds"].insert_one(funds_factory(user_id, available=0))
    order = _exit_order(user_id, orders_factory, side="BUY", qty=10, price=90.0)

    settle_mis_exit(database, order)

    assert database["funds"].find_one({"user": user_id})["available"] == 1100.0
    assert database["transactions"].find_one({})["amount"] == 100


def test_settle_without_a_position_cancels_the_order_and_siblings(
    database, user_id, orders_factory
):
    order = _exit_order(user_id, orders_factory)
    sibling = _exit_order(user_id, orders_factory, status="OPEN")
    database["orders"].insert_many([order, sibling])

    settle_mis_exit(database, order)

    assert database["orders"].find_one({"_id": order["_id"]})["status"] == "CANCELLED"
    assert database["orders"].find_one({"_id": sibling["_id"]})["status"] == "CANCELLED"
    assert database["funds"].count_documents({}) == 0


def test_settle_releases_only_the_open_quantity(
    database, user_id, positions_factory, orders_factory, funds_factory
):
    # The order asks for 10 but only 4 are still open; min() protects the cash
    # release. Express then removes the position regardless (see the job).
    database["positions"].insert_one(
        positions_factory(user_id, side="LONG", qty=4, entry=100.0, ltp=100.0)
    )
    database["funds"].insert_one(funds_factory(user_id, available=0))
    order = _exit_order(user_id, orders_factory, qty=10, price=110.0)

    settle_mis_exit(database, order)

    assert database["funds"].find_one({"user": user_id})["available"] == 440.0
    assert database["transactions"].find_one({})["amount"] == 40
    assert database["positions"].count_documents({}) == 0


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


def test_price_scheduler_runs_once_immediately_then_stops(database, monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "sync_prices", lambda db: ticks.append(db))

    instance = scheduler.PriceSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.stop()

    # Express calls syncPrices() on connect as well as on the cron.
    assert ticks == [database]
    assert instance._thread is None


def test_price_scheduler_does_not_start_twice(database, monkeypatch):
    ticks = []
    monkeypatch.setattr(scheduler, "sync_prices", lambda db: ticks.append(db))

    instance = scheduler.PriceSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.start()
    instance.stop()

    assert len(ticks) == 1


def test_price_scheduler_survives_a_failing_tick(database, monkeypatch):
    calls = []

    def flaky(db):
        calls.append(db)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "sync_prices", flaky)

    instance = scheduler.PriceSyncScheduler(database, interval_seconds=60)
    instance.start()
    instance.stop()

    assert calls == [database]
    assert instance._thread is None


def test_injected_test_database_never_starts_trading_jobs(database, monkeypatch):
    monkeypatch.setenv("TRADING_JOBS_ENABLED", "true")
    started = []
    monkeypatch.setattr(
        scheduler.PriceSyncScheduler, "start", lambda self: started.append("price")
    )
    monkeypatch.setattr(
        scheduler.PortfolioSnapshotScheduler,
        "start",
        lambda self: started.append("snapshot"),
    )

    with TestClient(create_app(database=database)) as client:
        assert client.get("/api/health").status_code == 200

    assert started == []
